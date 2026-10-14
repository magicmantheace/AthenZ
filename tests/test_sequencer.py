"""Synthetic-only sequential review workflow, no Ollama/Docker/network calls."""
import hashlib
import json
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from athenz.experience import ExperienceStore
from athenz.sequencer import SequenceController, SequenceError
from athenz.worker import Worker


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class Model:
    def __init__(self):
        self.prompts = []
        self.invalid = False

    def generate(self, messages, **kwargs):
        data = json.loads(messages[-1]['content'])
        self.prompts.append(data)
        changes = []
        for path in data['files']:
            if path == 'calc.py':
                content = 'def add(a,b):\n    return a + b\n'
            elif self.invalid:
                content = 'def broken(:\n'
            else:
                content = 'def sub(a,b):\n    return a - b\n'
            changes.append({'path': path, 'new_content': content})
        return json.dumps({'summary': 'synthetic change', 'changes': changes})


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'source'
        self.repo.mkdir()
        git(self.repo, 'init')
        git(self.repo, 'config', 'user.name', 'Synthetic')
        git(self.repo, 'config', 'user.email', 'synthetic@example.invalid')
        (self.repo / 'calc.py').write_text('def add(a,b):\n    return a - b\n')
        (self.repo / 'util.py').write_text('def sub(a,b):\n    return a + b\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'baseline')
        self.store = ExperienceStore(self.root / 'private')
        self.addCleanup(self.store.close)
        self.controller = SequenceController(Worker(self.store))
        self.model = Model()
        self.controller.start('task', self.repo, 'Fix functions', [['calc.py'], ['util.py']])

    def _reviewed(self):
        proposal = self.controller.prepare('task', self.model)
        self.assertEqual(self.controller.apply('task', proposal['sha256']), 1)
        return proposal

    def test_crlf_source_and_crlf_patch_preserve_exact_review_hashes(self):
        self.controller.cancel('task')
        # Force bytes to survive Git checkout even on Windows runners with
        # a global core.autocrlf preference.
        git(self.repo, 'config', 'core.autocrlf', 'false')
        (self.repo / 'calc.py').write_bytes(
            b'def add(a,b):\r\n    return a - b\r\n')
        # On Windows a prior Git autocrlf setting can leave util.py with
        # checkout CRLF bytes that differ from its earlier committed LF blob.
        # After opting out of autocrlf, re-stage the entire synthetic fixture
        # so the owner-worktree cleanliness gate is exercised honestly.
        git(self.repo, 'add', '--all')
        git(self.repo, 'commit', '-m', 'synthetic CRLF source and clean fixture')
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')
        self.controller.start('crlf', self.repo, 'Correct CRLF arithmetic', [['calc.py']])
        class CrLfModel:
            def generate(self, messages, **kwargs):
                return json.dumps({'summary': 'Preserve CRLF byte layout', 'changes': [
                    {'path': 'calc.py',
                     'new_content': 'def add(a,b):\r\n    return a + b\r\n'}]})
        review = self.controller.prepare('crlf', CrLfModel())
        self.assertEqual(self.controller.apply('crlf', review['sha256']), 1)
        result = self.controller.syntax('crlf')
        self.assertTrue(result['passed'])
        self.assertEqual(self.controller.advance('crlf')['phase'], 'complete')
        checkout = Path(self.controller.worker.resume('crlf')['state']['workspace'])
        self.assertEqual((checkout / 'calc.py').read_bytes(),
                         b'def add(a,b):\r\n    return a + b\r\n')
        self.controller.cancel('crlf', discard_changes=True)

    def test_manual_checkpoint_failure_rolls_back_proposal(self):
        # Foreground tasks need the same atomic proposal/checkpoint boundary
        # as scheduler-driven tasks: a failed save must not leak a proposal.
        with mock.patch.object(ExperienceStore, 'checkpoint',
                               side_effect=RuntimeError('synthetic disk write failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic disk write failure'):
                self.controller.prepare('task', self.model)
        self.assertEqual(self.controller.status('task')['phase'], 'ready')
        self.assertEqual(self.store.db.execute(
            'SELECT count(*) FROM proposals').fetchone()[0], 0)
        review = self.controller.prepare('task', self.model)
        self.assertEqual(self.controller.review('task')['sha256'], review['sha256'])
        self.assertEqual(self.store.db.execute(
            'SELECT count(*) FROM proposals').fetchone()[0], 1)

    def test_foreground_inference_rejects_changed_checkpoint(self):
        store = self.store
        class InterferingModel(Model):
            def generate(inner, messages, **kwargs):
                original = store.get_checkpoint('task')
                changed = dict(original['state'])
                changed['attempts'] += 1
                store.checkpoint('task', original['task'], changed, status='paused',
                                 expected_revision=original['revision'])
                return super().generate(messages, **kwargs)
        with self.assertRaisesRegex(SequenceError, 'checkpoint changed'):
            self.controller.prepare('task', InterferingModel())
        self.assertEqual(self.store.db.execute(
            'SELECT count(*) FROM proposals').fetchone()[0], 0)
        self.assertEqual(self.controller.status('task')['phase'], 'ready')

    def test_foreground_inference_rejects_dirty_worktree(self):
        workspace = Path(self.controller.worker.resume('task')['state']['workspace'])
        class DirtyModel(Model):
            def generate(inner, messages, **kwargs):
                (workspace / 'unexpected.txt').write_text('synthetic change')
                return super().generate(messages, **kwargs)
        try:
            with self.assertRaises(SequenceError):
                self.controller.prepare('task', DirtyModel())
            self.assertEqual(self.store.db.execute(
                'SELECT count(*) FROM proposals').fetchone()[0], 0)
        finally:
            (workspace / 'unexpected.txt').unlink(missing_ok=True)

    def test_two_steps_keep_prior_changes_and_export_combined_patch(self):
        first = self._reviewed()
        self.assertTrue(self.controller.syntax('task')['passed'])
        # Static syntax is not behavioral test evidence and cannot become
        # an approved procedural lesson, even when syntax parsing succeeds.
        pending = self.store.list_items('experiences', 'pending')
        self.assertEqual(len(pending), 1)
        with self.assertRaisesRegex(ValueError, 'Syntax parsing'):
            self.store.set_review('experiences', pending[0]['id'], 'approved')
        self.assertEqual(self.controller.advance('task')['stage'], 2)
        ws = Path(self.controller.worker.resume('task')['state']['workspace'])
        self.assertIn('a + b', (ws / 'calc.py').read_text())
        self.assertIn('a - b', (self.repo / 'calc.py').read_text())
        next_review = self.controller.prepare('task', self.model)
        self.assertNotEqual(first['sha256'], next_review['sha256'])
        self.assertIn('return a + b', (ws / 'calc.py').read_text())
        with self.assertRaises(SequenceError):
            self.controller.apply('task', first['sha256'])
        self.controller.apply('task', next_review['sha256'])
        self.assertTrue(self.controller.syntax('task')['passed'])
        self.assertEqual(self.controller.advance('task')['phase'], 'complete')
        artifact = self.controller.export('task')
        self.assertEqual(artifact['stages'], 2)
        self.assertEqual(artifact['verification'], 'syntax-only')
        patch = Path(artifact['path'])
        self.assertEqual(hashlib.sha256(patch.read_bytes()).hexdigest(), artifact['sha256'])
        self.assertIn('calc.py', patch.read_text())
        self.assertIn('util.py', patch.read_text())
        self.assertEqual(artifact, self.controller.export('task'))
        subprocess.run(['git', '-C', str(self.repo), 'apply', '--check', str(patch)], check=True)
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')
        self.controller.cancel('task', discard_changes=True)
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')

    def test_failure_rolls_back_only_current_stage_and_survives_restart(self):
        self._reviewed()
        self.controller.syntax('task')
        self.controller.advance('task')
        self.model.invalid = True
        self._reviewed()
        outcome = self.controller.syntax('task')
        self.assertEqual(outcome['phase'], 'ready')
        self.assertEqual(self.controller.status('task')['failures'], 1)
        ws = Path(self.controller.worker.resume('task')['state']['workspace'])
        self.assertIn('a + b', (ws/'calc.py').read_text())
        self.assertIn('a + b', (ws/'util.py').read_text())
        reopened = ExperienceStore(self.root / 'private')
        self.addCleanup(reopened.close)
        recovered = SequenceController(Worker(reopened))
        self.assertEqual(recovered.recover('task')['phase'], 'ready')
        self.model.invalid = False
        new = recovered.prepare('task', self.model)
        recovered.apply('task', new['sha256'])
        self.assertTrue(recovered.syntax('task')['passed'])
        recovered.advance('task')
        recovered.cancel('task', discard_changes=True)

    def test_untracked_or_modified_files_block_every_transition(self):
        ws = Path(self.controller.worker.resume('task')['state']['workspace'])
        (ws/'untracked.txt').write_text('unexpected')
        with self.assertRaises(SequenceError):
            self.controller.prepare('task', self.model)
        (ws/'untracked.txt').unlink()
        review = self.controller.prepare('task', self.model)
        (ws/'calc.py').write_text('evil=1\n')
        with self.assertRaises(SequenceError):
            self.controller.apply('task', review['sha256'])
        self.assertEqual(self.controller.status('task')['phase'], 'awaiting_review')
        self.controller.cancel('task', discard_changes=True)

    def test_refused_cancellation_preserves_reviewed_evidence(self):
        self._reviewed()
        self.controller.syntax('task')
        self.controller.advance('task')
        first_id = self.controller.worker.resume('task')['state']['sequence']['approved'][0]['proposal_id']
        self.store.record_test(first_id, 'docker:isolated unittest', 0, 'passed', 'hash', 'lesson')
        eid = self.store.list_items('experiences')[0]['id']
        self.store.set_review('experiences', eid, 'approved')
        with self.assertRaisesRegex(SequenceError, '--discard-changes'):
            self.controller.cancel('task')
        self.assertEqual(len(self.store.list_items('experiences', 'approved')), 1)
        self.controller.cancel('task', discard_changes=True)
        self.assertEqual(self.store.list_items('experiences', 'approved'), [])

    def test_crash_during_rollback_recovers_and_preserves_prior_step(self):
        self._reviewed()
        self.controller.syntax('task')
        self.controller.advance('task')
        self.model.invalid = True
        self._reviewed()
        item, seq = self.controller._load('task')
        seq['phase'] = 'rollback_pending'
        seq['failures'] = 1
        self.controller._save('task', item, seq)
        from athenz.coding import change_status
        change_status(self.store, seq['current'], undo=True)
        self.assertEqual(self.controller.recover('task')['phase'], 'ready')
        self.assertIn('a + b', (Path(item['state']['workspace'])/'calc.py').read_text())
        self.controller.cancel('task', discard_changes=True)

    def test_final_patch_rejects_tampered_verified_stage(self):
        self._reviewed()
        self.controller.syntax('task')
        self.controller.advance('task')
        ws = Path(self.controller.worker.resume('task')['state']['workspace'])
        (ws/'calc.py').write_text('tampering=True\n')
        with self.assertRaises(SequenceError):
            self.controller.prepare('task', self.model)
        self.controller.cancel('task', discard_changes=True)

    def test_second_stage_can_change_same_file_with_fresh_approval(self):
        # An overlapping file is allowed, but the second step's base is
        # the *approved* first-step content rather than the original checkout.
        self.controller.cancel('task')
        self.controller.start('overlap', self.repo, 'Improve implementation',
                              [['calc.py'], ['calc.py']])
        first = self.controller.prepare('overlap', self.model)
        self.controller.apply('overlap', first['sha256'])
        self.controller.syntax('overlap')
        self.controller.advance('overlap')
        class Refine:
            def generate(self, messages, **kwargs):
                return json.dumps({'summary': 'Improve naming', 'changes': [{
                    'path': 'calc.py', 'new_content': 'def add(left, right):\n    return left + right\n'}]})
        second = self.controller.prepare('overlap', Refine())
        self.assertNotEqual(first['sha256'], second['sha256'])
        self.controller.apply('overlap', second['sha256'])
        self.assertTrue(self.controller.syntax('overlap')['passed'])
        self.controller.advance('overlap')
        output = self.controller.export('overlap')
        self.assertEqual(output['files'], ['calc.py'])
        self.assertEqual(output['stages'], 2)
        self.controller.cancel('overlap', discard_changes=True)

    def test_cancel_revokes_earlier_success_evidence(self):
        self._reviewed()
        self.controller.syntax('task')
        self.controller.advance('task')
        first_id = self.controller.worker.resume('task')['state']['sequence']['approved'][0]['proposal_id']
        # Synthetic reviewed behavioral evidence to exercise revocation.
        self.store.record_test(first_id, 'docker:isolated unittest', 0, 'pass', 'hash', 'lesson')
        eid = self.store.list_items('experiences')[0]['id']
        self.store.set_review('experiences', eid, 'approved')
        self.assertEqual(self.store.list_items('experiences', 'approved')[0]['id'], eid)
        self.controller.cancel('task', discard_changes=True)
        self.assertEqual(self.store.list_items('experiences', 'approved'), [])
        self.assertEqual(self.store.get_proposal(first_id)['status'], 'undone')

    def test_no_progress_without_approval_and_invalid_stage_scope(self):
        first = self.controller.prepare('task', self.model)
        with self.assertRaises(SequenceError):
            self.controller.syntax('task')
        with self.assertRaises(SequenceError):
            self.controller.apply('task', 'f'*64)
        with self.assertRaises(SequenceError):
            self.controller.advance('task')
        self.assertEqual(len(self.store.list_items('test_runs')), 0)
        self.controller.cancel('task')
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')
        with self.assertRaises(ValueError):
            self.controller.start('bad', self.repo, 'task', [['../unsafe.py']])


if __name__ == '__main__':
    unittest.main()
