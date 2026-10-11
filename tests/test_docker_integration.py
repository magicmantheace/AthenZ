"""Opt-in actual-Docker tests; never executes the synthetic repository on host.

CI resolves a trusted Python image to its immutable registry SHA-256 digest
before calling this suite. Not run by default on a developer's computer.
"""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from athenz.verification import isolated_unittest

IMAGE = os.environ.get('ATHENZ_TEST_IMAGE', '')
ENABLE = os.environ.get('ATHENZ_INTEGRATION_DOCKER') == '1'


def git(repo, *args):
    subprocess.run(['git', '-C', str(repo), *args], check=True,
                   capture_output=True, text=True)


@unittest.skipUnless(ENABLE, 'Opt-in actual Docker test only')
class DockerIntegrationTests(unittest.TestCase):
    def setUp(self):
        if shutil.which('docker') is None:
            self.fail('Real Docker was requested but is unavailable')
        if not re.fullmatch(r'[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}', IMAGE):
            self.fail('ATHENZ_TEST_IMAGE must use an immutable image digest')
        self.temp = tempfile.TemporaryDirectory(prefix='athenz-integration-')
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        self.repo = home / 'repo'
        self.private = home / 'private'
        self.repo.mkdir()
        self.private.mkdir()
        git(self.repo, 'init')
        git(self.repo, 'config', 'user.name', 'Synthetic Fixture')
        git(self.repo, 'config', 'user.email', 'fixture@example.invalid')
        (self.repo / 'subject.py').write_text('def answer():\n    return 42\n')
        (self.repo / 'tests').mkdir()
        self.test_path = self.repo / 'tests' / 'test_subject.py'
        self.test_path.write_text(
            'import os\nfrom pathlib import Path\nimport unittest\nfrom subject import answer\n'
            'class Test(unittest.TestCase):\n'
            '    def test_answer(self): self.assertEqual(answer(), 42)\n'
            '    def test_read_only(self):\n'
            '        with self.assertRaises(OSError):\n'
            '            Path("subject.py").write_text("tampering")\n'
            '        self.assertFalse(Path(".git").exists())\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'synthetic fixture')

    def test_actual_container_pass_with_readonly_source(self):
        result = isolated_unittest(self.repo, image=IMAGE, home=self.private, timeout=120)
        self.assertEqual(result['returncode'], 0, result['output'])
        self.assertEqual(result['tracked_files'], 2)
        self.assertEqual(result['cleanup'], 'docker --rm (normal exit)')
        self.assertEqual(result['runner'], 'docker-local-observation')
        self.assertIsNotNone(result['snapshot_sha256'])
        self.assertEqual((self.repo / 'subject.py').read_text(),
                         'def answer():\n    return 42\n')

    def test_actual_container_failure_never_passes(self):
        self.test_path.write_text(self.test_path.read_text().replace('answer(), 42', 'answer(), 0'))
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'synthetic failing fixture')
        result = isolated_unittest(self.repo, image=IMAGE, home=self.private, timeout=120)
        self.assertNotEqual(result['returncode'], 0)
        self.assertIn('FAIL', result['output'])
        self.assertEqual(result['cleanup'], 'docker --rm (normal exit)')


if __name__ == '__main__':
    unittest.main()
