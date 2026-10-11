"""Synthetic threat tests for the real verifier's fail-closed boundaries."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from athenz.verification import (fingerprint_snapshot, isolated_unittest,
                                 snapshot_files, validate_mount_source)
from athenz.worker import WorktreeError


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], check=True,
                          text=True, capture_output=True).stdout.strip()


class SandboxThreatTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'private'
        self.home.mkdir()
        self.repo = Path(self.tmp.name) / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init')
        git(self.repo, 'config', 'user.name', 'Synthetic Tester')
        git(self.repo, 'config', 'user.email', 'synthetic@example.invalid')
        (self.repo / 'calc.py').write_text('x=1\n')
        (self.repo / 'tests').mkdir()
        (self.repo / 'tests' / 'test_one.py').write_text(
            'import unittest\nclass Test(unittest.TestCase):\n    def test_ok(self): assert 1 == 1\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'synthetic baseline')

    def test_snapshot_can_be_remeasured_and_additions_detected(self):
        with tempfile.TemporaryDirectory() as dest:
            dest = Path(dest)
            expected = snapshot_files(self.repo, dest)
            self.assertEqual(fingerprint_snapshot(dest), expected)
            (dest / 'injected.py').write_text('print("not approved")')
            self.assertNotEqual(fingerprint_snapshot(dest), expected)

    def test_snapshot_rejects_symlink_injection(self):
        with tempfile.TemporaryDirectory() as dest:
            dest = Path(dest)
            snapshot_files(self.repo, dest)
            try:
                (dest / 'bad').symlink_to(dest / 'calc.py')
            except (NotImplementedError, OSError):
                self.skipTest('Symlinks unavailable on filesystem')
            with self.assertRaisesRegex(WorktreeError, 'symlink'):
                fingerprint_snapshot(dest)

    def test_rejects_comma_and_newline_mount_sources(self):
        for name in ('some,path', 'some\npath', 'some\rpath'):
            with self.subTest(name=name), self.assertRaisesRegex(WorktreeError, 'bind-mount'):
                validate_mount_source(Path(name))
        self.assertIsNone(validate_mount_source(Path('/tmp/safe-path')))
        with tempfile.TemporaryDirectory(prefix='athenz,bad') as path:
            home = Path(path) / 'private'
            home.mkdir()
            with mock.patch('athenz.verification.shutil.which', return_value='/usr/bin/docker'), \
                 mock.patch('athenz.verification.subprocess.run') as run:
                with self.assertRaisesRegex(WorktreeError, 'bind-mount'):
                    isolated_unittest(self.repo, image='python@sha256:' + 'a'*64, home=home)
                run.assert_not_called()

    def test_mutation_during_container_run_invalidates_success(self):
        actual_run = subprocess.run
        def simulated(argv, *args, **kwargs):
            if argv[0] == 'docker':
                src = next(x for x in argv if x.startswith('type=bind,src='))
                folder = Path(src.split('src=', 1)[1].split(',dst=', 1)[0])
                (folder / 'calc.py').chmod(0o644)
                (folder / 'calc.py').write_text('TAMPERED = True\n')
                return subprocess.CompletedProcess(argv, 0, 'passed', '')
            return actual_run(argv, *args, **kwargs)
        with mock.patch('athenz.verification.shutil.which', return_value='/usr/bin/docker'), \
             mock.patch('athenz.verification.subprocess.run', side_effect=simulated):
            r = isolated_unittest(self.repo, image='python@sha256:' + 'a'*64,
                                  home=self.home)
        self.assertEqual(r['returncode'], 125)
        self.assertIn('integrity FAILED', r['output'])

    def test_nonzero_docker_result_remains_nonzero(self):
        actual_run = subprocess.run
        def simulated(argv, *args, **kwargs):
            if argv[0] == 'docker':
                return subprocess.CompletedProcess(argv, 3, '', 'synthetic test failure')
            return actual_run(argv, *args, **kwargs)
        with mock.patch('athenz.verification.shutil.which', return_value='/usr/bin/docker'), \
             mock.patch('athenz.verification.subprocess.run', side_effect=simulated):
            r = isolated_unittest(self.repo, image='python@sha256:' + 'a'*64,
                                  home=self.home)
        self.assertEqual(r['returncode'], 3)
        self.assertEqual(r['cleanup'], 'docker --rm (normal exit)')


if __name__ == '__main__':
    unittest.main()
