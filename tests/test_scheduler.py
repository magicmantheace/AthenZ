"""Synthetic supervised-queue tests. Never use live Ollama or host project code."""
from __future__ import annotations

import json
import threading
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from athenz.desktop_tasks import DesktopTasks
from athenz.experience import ExperienceStore
from athenz.scheduler import ProposalScheduler, SchedulerError
from athenz.schedule_cli import parser


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


class Model:
    calls = 0
    def generate(self, messages, **kwargs):
        self.calls += 1
        scope = json.loads(messages[-1]['content'])['files']
        return json.dumps({'summary': 'Synthesized proposal', 'changes': [
            {'path': p, 'new_content': 'def value():\n    return 99\n'} for p in scope]})


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.repo = self.base / 'source'
        self.repo.mkdir()
        git(self.repo, 'init')
        git(self.repo, 'config', 'user.name', 'Synthetic')
        git(self.repo, 'config', 'user.email', 'synthetic@example.invalid')
        for p in ['calc.py', 'util.py']:
            (self.repo / p).write_text('def value():\n    return 1\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'seed')
        self.home = self.base / 'private'
        self.ui = DesktopTasks(self.home)
        self.ui.create('demo', self.repo, 'Fix a synthetic example',
                       [['calc.py'], ['util.py']], confirmed=True)
        self.scheduler = ProposalScheduler(self.home)

    def add(self):
        self.scheduler.register('demo', model='synthetic:local', confirmed=True)

    def tearDown(self):
        try:
            self.ui.cancel('demo', discard_changes=True, confirmed=True)
        except Exception:
            pass

    def test_no_autostart_unarmed_and_confirmation(self):
        self.assertEqual(self.scheduler.list(), [])
        with self.assertRaisesRegex(SchedulerError, 'confirmation'):
            self.scheduler.register('demo', model='synthetic:local')
        self.add()
        self.assertEqual(self.scheduler.get('demo')['state'], 'paused')
        with self.assertRaisesRegex(SchedulerError, 'approval'):
            self.scheduler.arm('demo')
        with self.assertRaisesRegex(SchedulerError, 'confirm'):
            self.scheduler.run_once()
        self.assertEqual(self.scheduler.run_once(confirmed=True)['status'], 'idle')
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')

    def test_one_proposal_stops_at_review_and_cannot_autoapply(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        m = Model()
        outcome = self.scheduler.run_once(confirmed=True, model_factory=lambda name: m)
        self.assertEqual(m.calls, 1)
        self.assertEqual(outcome['status'], 'review')
        self.assertEqual(self.scheduler.get('demo')['state'], 'review')
        self.assertEqual(self.ui.detail('demo')['phase'], 'awaiting_review')
        self.assertEqual(self.scheduler.run_once(confirmed=True)['status'], 'idle')
        self.assertEqual(m.calls, 1)
        self.assertEqual(git(self.repo, 'status', '--porcelain'), '')
        self.assertEqual(self.ui.review('demo')['sha256'], outcome['result']['sha256'])

    def test_each_new_stage_requires_owner_rearm(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        one = self.scheduler.run_once(confirmed=True, model_factory=lambda _: Model())
        digest = one['result']['sha256']
        self.ui.apply('demo', digest, confirmed=True)
        self.assertTrue(self.ui.syntax('demo')['passed'])
        self.ui.advance('demo', confirmed=True)
        self.assertEqual(self.scheduler.run_once(confirmed=True)['status'], 'idle')
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')
        self.scheduler.arm('demo', confirmed=True)
        two = self.scheduler.run_once(confirmed=True, model_factory=lambda _: Model())
        self.assertEqual(two['result']['stage'], 2)
        self.assertEqual(self.scheduler.get('demo')['state'], 'review')

    def test_pause_blocks_tick_and_is_persistent(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        self.scheduler.pause('demo')
        self.assertEqual(ProposalScheduler(self.home).run_once(confirmed=True)['status'], 'idle')
        self.assertEqual(self.scheduler.get('demo')['state'], 'paused')
        self.scheduler.arm('demo', confirmed=True)
        self.assertEqual(self.scheduler.get('demo')['state'], 'armed')

    def test_concurrent_tick_claims_only_once(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        second = ProposalScheduler(self.home)
        calls = []
        def factory(_):
            calls.append(second.run_once(confirmed=True))
            return Model()
        self.scheduler.run_once(confirmed=True, model_factory=factory)
        self.assertEqual(calls, [{'status': 'idle', 'proposals': 0}])

    def test_pause_during_inference_not_rearmed_and_no_auto_retry(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        def factory(_):
            self.scheduler.pause('demo')
            with self.assertRaises(SchedulerError):
                self.scheduler.arm('demo', confirmed=True)
            return Model()
        outcome = self.scheduler.run_once(confirmed=True, model_factory=factory)
        self.assertEqual(outcome['status'], 'paused')
        self.assertEqual(self.scheduler.get('demo')['state'], 'paused')
        self.assertIsNone(self.scheduler.get('demo')['lease'])
        # Once a pause wins before inference completes, the generated reply
        # must never become an owner-reviewable proposal or new checkpoint.
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')
        with self.scheduler._open() as store:
            self.assertEqual(store.db.execute('SELECT count(*) FROM proposals').fetchone()[0], 0)
        self.assertEqual(self.scheduler.run_once(confirmed=True)['status'], 'idle')

    def test_pause_during_model_initialization_blocks_outbound_prompt(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        scheduler = self.scheduler
        model = Model()
        def pause_in_factory(_):
            scheduler.pause('demo')
            return model
        result = scheduler.run_once(confirmed=True, model_factory=pause_in_factory)
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(model.calls, 0)
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')
        self.assertEqual(scheduler.get('demo')['state'], 'paused')
        with scheduler._open() as store:
            self.assertEqual(store.db.execute('SELECT count(*) FROM proposals').fetchone()[0], 0)

    def test_pausing_from_inside_model_generation_discards_response(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        scheduler = self.scheduler
        class SlowModel(Model):
            def generate(self, messages, **kwargs):
                scheduler.pause('demo')
                return super().generate(messages, **kwargs)
        result = scheduler.run_once(confirmed=True, model_factory=lambda _: SlowModel())
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(scheduler.get('demo')['state'], 'paused')
        self.assertIsNone(scheduler.get('demo')['lease'])
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')
        with scheduler._open() as store:
            self.assertEqual(store.db.execute('SELECT count(*) FROM proposals').fetchone()[0], 0)

    def test_revoked_lease_discards_generation_without_write(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        scheduler = self.scheduler
        class ReplacedLeaseModel(Model):
            def generate(self, messages, **kwargs):
                with scheduler._open() as store:
                    with store.db:
                        store.db.execute('BEGIN IMMEDIATE')
                        store.db.execute("UPDATE proposal_schedule SET lease=? WHERE task_key='demo'", ('other-process',))
                return super().generate(messages, **kwargs)
        result = scheduler.run_once(confirmed=True, model_factory=lambda _: ReplacedLeaseModel())
        self.assertEqual(result['status'], 'paused')
        with scheduler._open() as store:
            self.assertEqual(store.db.execute('SELECT count(*) FROM proposals').fetchone()[0], 0)
            self.assertEqual(store.db.execute("SELECT lease FROM proposal_schedule WHERE task_key='demo'").fetchone()[0], 'other-process')

    def test_scope_change_during_generation_discards_proposal(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        scheduler = self.scheduler
        class ScopeChangingModel(Model):
            def generate(self, messages, **kwargs):
                with scheduler._open() as store:
                    item = store.get_checkpoint('demo')
                    changed = dict(item['state'])
                    changed['sequence'] = dict(changed['sequence'])
                    changed['sequence']['stages'] = [['util.py']]
                    store.checkpoint('demo', item['task'], changed,
                        status='paused', expected_revision=item['revision'])
                return super().generate(messages, **kwargs)
        result = scheduler.run_once(confirmed=True, model_factory=lambda _: ScopeChangingModel())
        self.assertEqual(result['status'], 'paused')
        with scheduler._open() as store:
            self.assertEqual(store.db.execute('SELECT count(*) FROM proposals').fetchone()[0], 0)

    def test_failed_checkpoint_rolls_back_new_proposal(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        # The proposal INSERT succeeds but the later checkpoint fails.
        with mock.patch.object(ExperienceStore, 'checkpoint',
                               side_effect=RuntimeError('synthetic write failure')):
            result = self.scheduler.run_once(
                confirmed=True, model_factory=lambda _: Model())
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')
        with self.scheduler._open() as store:
            self.assertEqual(store.db.execute(
                'SELECT count(*) FROM proposals').fetchone()[0], 0)
        self.scheduler.arm('demo', confirmed=True)
        fresh = self.scheduler.run_once(confirmed=True, model_factory=lambda _: Model())
        self.assertEqual(fresh['status'], 'review')
        with self.scheduler._open() as store:
            self.assertEqual(store.db.execute(
                'SELECT count(*) FROM proposals').fetchone()[0], 1)

    def test_cross_thread_pause_during_generation_discards_response(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        entered, release = threading.Event(), threading.Event()
        results = []
        class BlockingModel(Model):
            def generate(self, messages, **kwargs):
                entered.set()
                if not release.wait(10):
                    raise RuntimeError('synthetic model timed out')
                return super().generate(messages, **kwargs)
        worker = threading.Thread(target=lambda: results.append(
            ProposalScheduler(self.home).run_once(
                confirmed=True, model_factory=lambda _: BlockingModel())))
        worker.start()
        try:
            self.assertTrue(entered.wait(5), 'generation did not begin')
            self.scheduler.pause('demo')
        finally:
            release.set()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]['status'], 'paused')
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')
        self.assertIsNone(self.scheduler.get('demo')['lease'])
        with self.scheduler._open() as store:
            self.assertEqual(store.db.execute(
                'SELECT count(*) FROM proposals').fetchone()[0], 0)

    def test_recovered_old_worker_cannot_overwrite_new_arm(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        entered, release = threading.Event(), threading.Event()
        results = []
        class BlockingModel(Model):
            def generate(self, messages, **kwargs):
                entered.set()
                if not release.wait(10):
                    raise RuntimeError('synthetic model timed out')
                return super().generate(messages, **kwargs)
        old = threading.Thread(target=lambda: results.append(
            ProposalScheduler(self.home).run_once(
                confirmed=True, model_factory=lambda _: BlockingModel())))
        old.start()
        try:
            self.assertTrue(entered.wait(5), 'generation did not begin')
            # Simulate mistaken owner recovery while old inference is alive.
            recovered = self.scheduler.recover('demo', confirmed=True)
            self.assertEqual(recovered['state'], 'paused')
            self.scheduler.arm('demo', confirmed=True)
        finally:
            release.set()
            old.join(timeout=10)
        self.assertFalse(old.is_alive())
        self.assertEqual(results[0]['status'], 'paused')
        self.assertEqual(self.scheduler.get('demo')['state'], 'armed')
        with self.scheduler._open() as store:
            self.assertEqual(store.db.execute(
                'SELECT count(*) FROM proposals').fetchone()[0], 0)
        fresh = self.scheduler.run_once(confirmed=True, model_factory=lambda _: Model())
        self.assertEqual(fresh['status'], 'review')
        self.assertEqual(self.ui.detail('demo')['phase'], 'awaiting_review')

    def test_manual_proposal_wins_over_inflight_scheduled_request(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        entered, release, results = threading.Event(), threading.Event(), []
        class HeldModel(Model):
            def generate(self, messages, **kwargs):
                entered.set()
                if not release.wait(10):
                    raise RuntimeError('synthetic inference timeout')
                return super().generate(messages, **kwargs)
        worker = threading.Thread(target=lambda: results.append(
            ProposalScheduler(self.home).run_once(
                confirmed=True, model_factory=lambda _: HeldModel())))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            manual = self.ui.prepare('demo', model=Model())
        finally:
            release.set()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]['status'], 'paused')
        self.assertEqual(self.scheduler.get('demo')['state'], 'paused')
        self.assertEqual(self.ui.review('demo')['sha256'], manual['sha256'])
        with self.scheduler._open() as store:
            self.assertEqual(store.db.execute(
                'SELECT count(*) FROM proposals').fetchone()[0], 1)

    def test_scheduled_proposal_wins_over_inflight_manual_request(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        entered, release, results = threading.Event(), threading.Event(), []
        class HeldModel(Model):
            def generate(self, messages, **kwargs):
                entered.set()
                if not release.wait(10):
                    raise RuntimeError('synthetic inference timeout')
                return super().generate(messages, **kwargs)
        def foreground():
            try:
                results.append(('ok', self.ui.prepare('demo', model=HeldModel())))
            except Exception as exc:
                results.append(('error', type(exc).__name__))
        worker = threading.Thread(target=foreground)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            scheduled = self.scheduler.run_once(
                confirmed=True, model_factory=lambda _: Model())
        finally:
            release.set()
            worker.join(timeout=10)
        self.assertFalse(worker.is_alive())
        self.assertEqual(scheduled['status'], 'review')
        self.assertEqual(results, [('error', 'SequenceError')])
        self.assertEqual(self.ui.review('demo')['sha256'], scheduled['result']['sha256'])
        with self.scheduler._open() as store:
            self.assertEqual(store.db.execute(
                'SELECT count(*) FROM proposals').fetchone()[0], 1)

    def test_pause_after_proposal_commit_reports_paused_queue(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        from athenz.sequencer import SequenceController
        actual_prepare = SequenceController.prepare
        def paused_after_commit(ctl, *args, **kwargs):
            result = actual_prepare(ctl, *args, **kwargs)
            self.scheduler.pause('demo')
            return result
        with mock.patch('athenz.scheduler.SequenceController.prepare',
                        new=paused_after_commit):
            outcome = self.scheduler.run_once(
                confirmed=True, model_factory=lambda _: Model())
        self.assertEqual(outcome['status'], 'paused')
        self.assertEqual(self.scheduler.get('demo')['state'], 'paused')
        self.assertIsNone(self.scheduler.get('demo')['lease'])
        self.assertEqual(self.ui.detail('demo')['phase'], 'awaiting_review')
        self.assertEqual(outcome['result']['sha256'],
                         self.ui.review('demo')['sha256'])
        self.assertEqual(self.scheduler.run_once(confirmed=True)['status'], 'idle')

    def test_model_failure_does_not_expose_private_exception_text(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        secret = 'PRIVATE-OWNER-SCENARIO-MODEL-EXCEPTION'
        class LeakyModel(Model):
            def generate(self, messages, **kwargs):
                raise RuntimeError(secret)
        result = self.scheduler.run_once(
            confirmed=True, model_factory=lambda _: LeakyModel())
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(result['result']['error'], 'local-proposal-failed')
        self.assertNotIn(secret, json.dumps(result))
        self.assertNotIn(secret, json.dumps(self.scheduler.get('demo')))
        with self.scheduler._open() as store:
            status = store.db.execute(
                "SELECT last_result FROM proposal_schedule WHERE task_key='demo'"
            ).fetchone()['last_result']
        self.assertNotIn(secret, status)
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')

    def test_foreground_poll_rejects_boolean_bounds(self):
        self.add()
        with self.assertRaises(SchedulerError):
            self.scheduler.serve(confirmed=True, ticks=True)
        with self.assertRaises(SchedulerError):
            self.scheduler.serve(confirmed=True, ticks=1, interval=True)

    def test_model_failure_does_not_loop_or_run_host_commands(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        def bad(_): raise RuntimeError('synthetic GPU error')
        result = self.scheduler.run_once(confirmed=True, model_factory=bad)
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(self.scheduler.get('demo')['state'], 'paused')
        self.assertEqual(self.scheduler.run_once(confirmed=True)['status'], 'idle')
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')

    def test_interrupted_lease_only_recovers_manually_without_inference(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        with self.scheduler._open() as store:
            with store.db:
                store.db.execute("UPDATE proposal_schedule SET state='running',lease='dead-job' WHERE task_key='demo'")
        self.assertEqual(self.scheduler.run_once(confirmed=True)['status'], 'idle')
        with self.assertRaisesRegex(SchedulerError, 'Confirm'):
            self.scheduler.recover('demo')
        with self.assertRaises(SchedulerError):
            self.scheduler.arm('demo', confirmed=True)
        recovered = ProposalScheduler(self.home).recover('demo', confirmed=True)
        self.assertEqual(recovered['state'], 'paused')
        self.assertIsNone(recovered['lease'])
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')

    def test_recover_without_lease_has_no_sequence_side_effects(self):
        self.add()
        # Recovery must refuse an idle job BEFORE SequenceController.recover,
        # which might otherwise finish an unrelated rollback.
        with mock.patch('athenz.scheduler.SequenceController.recover') as recovered:
            with self.assertRaisesRegex(SchedulerError, 'No interrupted job'):
                self.scheduler.recover('demo', confirmed=True)
        recovered.assert_not_called()

    def test_recovery_fences_lease_replaced_mid_reconciliation(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        with self.scheduler._open() as store:
            with store.db:
                store.db.execute(
                    "UPDATE proposal_schedule SET state='running',lease='old-worker' "
                    "WHERE task_key='demo'")
        def replace_lease(*_args):
            with self.scheduler._open() as store:
                with store.db:
                    store.db.execute(
                        "UPDATE proposal_schedule SET state='running',lease='new-worker' "
                        "WHERE task_key='demo'")
        with mock.patch('athenz.scheduler.SequenceController.recover',
                        side_effect=replace_lease):
            with self.assertRaisesRegex(SchedulerError, 'lease changed'):
                self.scheduler.recover('demo', confirmed=True)
        state = self.scheduler.get('demo')
        self.assertEqual(state['state'], 'running')
        self.assertEqual(state['lease'], 'new-worker')
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')

    def test_recovery_refuses_scope_change_before_sequence_side_effects(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        with self.scheduler._open() as store:
            with store.db:
                store.db.execute(
                    "UPDATE proposal_schedule SET state='running',lease='old-worker',"
                    "scope_sha256=? WHERE task_key='demo'", ('0' * 64,))
        with mock.patch('athenz.scheduler.SequenceController.recover') as recovered:
            with self.assertRaisesRegex(SchedulerError, 'authority changed'):
                self.scheduler.recover('demo', confirmed=True)
        recovered.assert_not_called()

    def test_scope_tamper_prevents_inference(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        with self.scheduler._open() as store:
            item = store.get_checkpoint('demo')
            state = dict(item['state'])
            state['sequence'] = dict(state['sequence'])
            state['sequence']['stages'] = [['util.py']]
            store.checkpoint('demo', item['task'], state, status='paused', expected_revision=item['revision'])
        m = Model()
        refused = self.scheduler.run_once(confirmed=True, model_factory=lambda _: m)
        self.assertEqual(refused['status'], 'paused')
        self.assertEqual(m.calls, 0)

    def test_unexpected_worktree_change_prevents_proposal(self):
        self.add(); self.scheduler.arm('demo', confirmed=True)
        p = Path(self.ui.detail('demo')['workspace']) / 'unexpected.txt'
        p.write_text('no')
        result = self.scheduler.run_once(confirmed=True, model_factory=lambda _: Model())
        self.assertEqual(result['status'], 'paused')
        self.assertEqual(self.scheduler.get('demo')['state'], 'paused')

    def test_bounded_serve_only_when_explicit(self):
        self.add()
        with self.assertRaises(SchedulerError):
            self.scheduler.serve(confirmed=True, ticks=121)
        with self.assertRaises(SchedulerError):
            self.scheduler.serve(ticks=1)
        with mock.patch('athenz.scheduler.time.sleep') as sleep:
            events = self.scheduler.serve(confirmed=True, ticks=3, interval=5)
        self.assertEqual(len(events), 3)
        self.assertEqual(sleep.call_count, 2)

    def test_removal_requires_pause_and_leaves_worktree_untouched(self):
        self.add()
        with self.assertRaisesRegex(SchedulerError, 'confirmation'):
            self.scheduler.remove('demo')
        self.scheduler.arm('demo', confirmed=True)
        with self.assertRaisesRegex(SchedulerError, 'Pause'):
            self.scheduler.remove('demo', confirmed=True)
        self.scheduler.pause('demo')
        self.assertTrue(self.scheduler.remove('demo', confirmed=True))
        self.assertFalse(self.scheduler.remove('demo', confirmed=True))
        self.assertIsNone(self.scheduler.get('demo'))
        self.assertEqual(self.ui.detail('demo')['phase'], 'ready')
        self.add()

    def test_model_alias_is_validated_before_saving(self):
        with self.assertRaisesRegex(SchedulerError, 'tag'):
            self.scheduler.register('demo', model='valid\nunsafe', confirmed=True)
        self.assertEqual(self.scheduler.list(), [])

    def test_cli_available_but_never_automatically_armed(self):
        commands = parser()._subparsers._group_actions[0].choices
        self.assertEqual(set(commands), {'list', 'show', 'add', 'arm', 'pause', 'remove', 'recover', 'tick', 'serve'})
        self.assertFalse(parser().parse_args(['tick']).confirm)
