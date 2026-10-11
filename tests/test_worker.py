"""Worktree isolation, strict checkpoint recovery, and non-executing checks."""
import json
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from athenz.experience import ExperienceStore
from athenz.worker import Worker, WorktreeError


def git(repo, *argv):
    return subprocess.run(['git', '-C', str(repo), *argv], check=True,
                          capture_output=True, text=True).stdout.strip()


class StubModel:
    def generate(self, messages, **kwargs):
        return json.dumps({'summary': 'Synthetic fix', 'changes': [
            {'path': 'calc.py', 'new_content': 'def add(a, b):\n    return a + b\n'},
            {'path': 'util.py', 'new_content': 'def sub(a, b):\n    return a - b\n'}]})


class WorktreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'source'
        self.repo.mkdir()
        git(self.repo, 'init')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        git(self.repo, 'config', 'user.name', 'Synthetic Tester')
        (self.repo / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
        (self.repo / 'util.py').write_text('def sub(a, b):\n    return a + b\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'fixture')
        self.store = ExperienceStore(self.root / 'private')
        self.addCleanup(self.store.close)
        self.worker = Worker(self.store)

    def test_multifile_isolated_proposal_restart_and_review(self):
        begun = self.worker.begin('work1', self.repo, 'Fix arithmetic helpers')
        path = Path(begun['state']['workspace'])
        self.assertEqual((path / 'calc.py').read_text(), (self.repo / 'calc.py').read_text())
        pid = self.worker.propose('work1', StubModel(), ['calc.py', 'util.py'])
        self.assertIn('return a - b', (path / 'calc.py').read_text())
        self.assertEqual(self.worker.apply('work1'), 2)
        self.assertIn('return a + b', (path / 'calc.py').read_text())
        self.assertIn('return a - b', (self.repo / 'calc.py').read_text())
        reloaded = Worker(ExperienceStore(self.root / 'private'))
        self.addCleanup(reloaded.store.close)
        self.assertEqual(reloaded.resume('work1')['state']['proposal_id'], pid)
        result = reloaded.syntax_check('work1')
        self.assertEqual(result['returncode'], 0)
        lesson = reloaded.store.list_items('experiences')[0]
        reloaded.store.set_review('experiences', lesson['id'], 'approved')
        self.assertEqual(len(reloaded.store.approved_experiences(query='Fix arithmetic')), 1)
        self.assertIn('util.py', reloaded.diff('work1'))
        with self.assertRaises(WorktreeError):
            reloaded.cleanup('work1')
        reloaded.cleanup('work1', discard_changes=True)
        self.assertFalse(path.exists())
        self.assertEqual(self.store.get_checkpoint('work1')['status'], 'complete')
        self.assertEqual(self.store.approved_experiences(), [])
        self.assertIn('return a - b', (self.repo / 'calc.py').read_text())

    def test_export_review_private_and_not_overclaimed(self):
        self.worker.begin('bundle', self.repo, 'Fix arithmetic helpers')
        self.worker.propose('bundle', StubModel(), ['calc.py', 'util.py'])
        with self.assertRaises(WorktreeError):
            self.worker.export_review('bundle')
        self.worker.apply('bundle')
        review = self.worker.export_review('bundle')
        path = Path(review['path'])
        self.assertTrue(path.is_relative_to(self.store.home / 'reviews'))
        self.assertEqual(review['verification'], 'not-verified')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), review['sha256'])
        self.assertIn('return a + b', path.read_text())
        self.assertFalse(review['test_run_id'])
        with self.assertRaises(WorktreeError):
            self.worker.export_review('bundle')
        self.worker.cleanup('bundle', discard_changes=True)
        self.assertTrue(path.exists())
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')

    def test_review_bundle_syntax_not_unit_test_and_reject_extra_files(self):
        self.worker.begin('bundle2', self.repo, 'Fix arithmetic helpers')
        self.worker.propose('bundle2', StubModel(), ['calc.py', 'util.py'])
        self.worker.apply('bundle2')
        workspace = Path(self.worker.resume('bundle2')['state']['workspace'])
        (workspace / 'untracked.txt').write_text('not approved')
        with self.assertRaises(WorktreeError):
            self.worker.export_review('bundle2')
        (workspace / 'untracked.txt').unlink()
        self.assertEqual(self.worker.syntax_check('bundle2')['returncode'], 0)
        review = self.worker.export_review('bundle2')
        self.assertEqual(review['verification'], 'syntax-only')
        self.assertIsInstance(review['test_run_id'], int)
        self.worker.cleanup('bundle2', discard_changes=True)

    def test_invalid_workspace_and_no_host_fallback(self):
        (self.repo / 'untracked').touch()
        with self.assertRaises(WorktreeError):
            self.worker.begin('dirty', self.repo, 'Work')
        (self.repo / 'untracked').unlink()
        self.worker.begin('x', self.repo, 'Safe synthetic task')
        with self.assertRaises(WorktreeError):
            self.worker.begin('x', self.repo, 'Cannot overwrite checkpoint')
        self.worker.propose('x', StubModel(), ['calc.py', 'util.py'])
        self.worker.apply('x')
        with self.assertRaises(ValueError):
            self.worker.container_tests('x', image='python:latest')
        self.worker.cleanup('x', discard_changes=True)

    def test_source_stays_clean_and_syntax_failure_records_failed_evidence(self):
        self.worker.begin('x', self.repo, 'Check Python files')
        class Invalid:
            def generate(self, *args, **kwargs):
                return json.dumps({'summary': 'bad', 'changes': [
                    {'path': 'calc.py', 'new_content': 'def broken(:\n  pass\n'}]})
        self.worker.propose('x', Invalid(), ['calc.py'])
        self.worker.apply('x')
        result = self.worker.syntax_check('x')
        self.assertEqual(result['returncode'], 1)
        self.assertEqual(self.store.list_items('experiences')[0]['outcome'], 'test_fail')
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')
        self.worker.cleanup('x', discard_changes=True)


if __name__ == '__main__':
    unittest.main()


class RetryTests(unittest.TestCase):
    setUp = WorktreeTests.setUp
    def test_manual_retry_reverts_and_is_capped(self):
        self.worker.begin('retry1', self.repo, 'Correct arithmetic')
        for i in range(3):
            self.worker.propose('retry1', StubModel(), ['calc.py', 'util.py'])
            self.worker.apply('retry1')
            self.assertEqual(self.worker.retry('retry1'), i + 1)
            self.assertIn('return a - b', (Path(self.worker.resume('retry1')['state']['workspace']) / 'calc.py').read_text())
        self.worker.propose('retry1', StubModel(), ['calc.py', 'util.py'])
        with self.assertRaises(WorktreeError):
            self.worker.retry('retry1')
        self.worker.cleanup('retry1')
        self.assertEqual(self.store.get_checkpoint('retry1')['state']['disposition'], 'released')

    def test_retry_dismisses_unapplied_proposal_and_cancel_is_terminal(self):
        self.worker.begin('cancel1', self.repo, 'Change helpers')
        pid = self.worker.propose('cancel1', StubModel(), ['calc.py', 'util.py'])
        self.assertEqual(self.worker.retry('cancel1'), 1)
        with self.assertRaises(ValueError):
            self.store.get_proposal(pid)
        self.worker.cleanup('cancel1', disposition='cancelled')
        self.assertEqual(self.store.get_checkpoint('cancel1')['state']['disposition'], 'cancelled')
        with self.assertRaises(WorktreeError):
            self.worker.resume('cancel1')
