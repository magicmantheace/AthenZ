"""Worktree isolation, strict checkpoint recovery, and non-executing checks."""
import json
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
