"""Portable test that catches CRLF byte loss even on Linux runners."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from athenz.coding import change_status, propose, read_exact
from athenz.experience import ExperienceStore
from athenz.worker import Worker


def git(repo, *argv):
    return subprocess.run(['git', '-C', str(repo), *argv], check=True,
                          capture_output=True, text=True).stdout.strip()


class StubModel:
    def generate(self, messages, **kwargs):
        return json.dumps({'summary': 'Synthetic change', 'changes': [
            {'path': 'file.py', 'new_content': 'def number():\n    return 2\n'}]})


class LineEndingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init')
        git(self.repo, 'config', 'user.name', 'Synthetic')
        git(self.repo, 'config', 'user.email', 'synthetic@example.invalid')
        # Use an explicit setting so the test exercises unmodified CRLF even
        # if the machine globally sets core.autocrlf=true.
        git(self.repo, 'config', 'core.autocrlf', 'false')
        self.file = self.repo / 'file.py'
        self.original = b'def number():\r\n    return 1\r\n'
        self.file.write_bytes(self.original)
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'synthetic CRLF fixture')
        self.store = ExperienceStore(Path(self.tmp.name) / 'private')
        self.addCleanup(self.store.close)

    def test_roundtrip_restores_exact_crlf_bytes(self):
        self.assertIn('\r\n', read_exact(self.file))
        pid = propose(self.store, StubModel(), str(self.repo), 'Update number', ['file.py'])
        self.assertEqual(change_status(self.store, pid), 1)
        self.assertEqual(self.file.read_bytes(), b'def number():\n    return 2\n')
        self.assertEqual(change_status(self.store, pid, undo=True), 1)
        self.assertEqual(self.file.read_bytes(), self.original)
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')

    def test_worker_retry_restores_clean_crlf_checkout(self):
        worker = Worker(self.store)
        worker.begin('crlf', self.repo, 'Update number')
        pid = worker.propose('crlf', StubModel(), ['file.py'])
        worker.apply('crlf')
        self.assertEqual(worker.retry('crlf'), 1)
        ws = Path(worker.resume('crlf')['state']['workspace'])
        self.assertEqual((ws / 'file.py').read_bytes(), self.original)
        self.assertEqual(git(ws, 'status', '--porcelain=v1'), '')
        worker.cleanup('crlf')
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')


if __name__ == '__main__':
    unittest.main()
