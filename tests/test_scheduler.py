"""Synthetic supervised-queue tests. Never use live Ollama or host project code."""
from __future__ import annotations

import json
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
        self.scheduler.run_once(confirmed=True, model_factory=factory)
        self.assertEqual(self.scheduler.get('demo')['state'], 'paused')
        self.assertIsNone(self.scheduler.get('demo')['lease'])
        self.assertEqual(self.ui.detail('demo')['phase'], 'awaiting_review')
        with self.assertRaisesRegex(SchedulerError, 'ready'):
            self.scheduler.arm('demo', confirmed=True)

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
