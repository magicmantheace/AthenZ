"""Synthetic full-task behavior evidence; Docker invocations are mocked."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from athenz.experience import ExperienceStore
from athenz.sequencer import SequenceController, SequenceError
from athenz.verification import snapshot_files
from athenz.worker import Worker, WorktreeError


def git(repo, *argv):
    return subprocess.run(['git', '-C', str(repo), *argv], capture_output=True,
                          text=True, check=True).stdout.strip()


class Model:
    def generate(self, messages, **kwargs):
        files = json.loads(messages[-1]['content'])['files']
        changes = [{'path': rel, 'new_content': f'def {rel[:-3]}():\n    return 42\n'}
                   for rel in files]
        return json.dumps({'summary': 'Synthetic edits', 'changes': changes})


IMAGE = 'python@sha256:' + 'a' * 64


class FullTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init')
        git(self.repo, 'config', 'user.name', 'Unit Tester')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        (self.repo / 'calc.py').write_text('x = 1\n')
        (self.repo / 'util.py').write_text('y = 2\n')
        (self.repo / 'tests').mkdir()
        (self.repo / 'tests' / 'test_numbers.py').write_text('import unittest\nclass T(unittest.TestCase):\n    def test_one(self): self.assertTrue(True)\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-m', 'baseline')
        self.store = ExperienceStore(self.root / 'private')
        self.addCleanup(self.store.close)
        self.ctl = SequenceController(Worker(self.store))
        self.ctl.start('math', self.repo, 'Fix helpers', [['calc.py'], ['util.py']])

    def finish(self):
        for _ in range(2):
            r = self.ctl.prepare('math', Model())
            self.ctl.apply('math', r['sha256'])
            self.assertTrue(self.ctl.syntax('math')['passed'])
            self.ctl.advance('math')
        self.assertEqual(self.ctl.status('math')['phase'], 'complete')

    def mocked_docker(self, code=0):
        original = subprocess.run
        def stub(argv, *args, **kwargs):
            if argv[0] == 'docker':
                self.assertEqual(argv[1], 'run')
                self.assertIn('--network', argv)
                self.assertIn('none', argv)
                self.assertIn('--read-only', argv)
                self.assertIn('--pull', argv)
                self.assertIn('never', argv)
                self.assertEqual(argv[-7:], ['python', '-m', 'unittest', 'discover', '-s', 'tests', '-v'])
                mount = argv[argv.index('--mount')+1]
                snapshot = Path(mount.split('src=')[1].split(',dst=')[0])
                self.assertTrue((snapshot / 'calc.py').is_file())
                self.assertTrue((snapshot / 'util.py').is_file())
                self.assertFalse((snapshot / '.git').exists())
                self.assertEqual((snapshot / 'calc.py').read_text(), 'def calc():\n    return 42\n')
                return subprocess.CompletedProcess(argv, code, 'Ran 1 test', '')
            return original(argv, *args, **kwargs)
        return stub

    def test_snapshot_integrity_error_never_echoes_private_path(self):
        from athenz.verification import isolated_unittest, fingerprint_snapshot
        calls = {'n': 0}
        def tampered_late(path):
            calls['n'] += 1
            if calls['n'] == 2:
                raise OSError('PRIVATE-SOURCE-REPO-PATH')
            return fingerprint_snapshot(path)
        with mock.patch('athenz.verification.shutil.which', return_value='/usr/bin/docker'), \
             mock.patch('athenz.verification.subprocess.run',
                        return_value=subprocess.CompletedProcess(['docker'], 0, '', '')), \
             mock.patch('athenz.verification.fingerprint_snapshot',
                        side_effect=tampered_late):
            result = isolated_unittest(self.repo, image=IMAGE, home=self.store.home)
        self.assertEqual(calls['n'], 2)
        self.assertEqual(result['returncode'], 125)
        self.assertIn('Snapshot integrity FAILED', result['output'])
        self.assertNotIn('PRIVATE-SOURCE', json.dumps(result))


    def test_isolated_unittest_rejects_boolean_timeout_without_docker_probe(self):
        from athenz.verification import isolated_unittest
        with mock.patch('athenz.verification.shutil.which',
                        side_effect=AssertionError('must not query Docker')):
            with self.assertRaisesRegex(ValueError, 'Timeout'):
                isolated_unittest(self.repo, image=IMAGE, home=self.root, timeout=True)

    def test_full_sequence_evidence_and_export(self):
        self.finish()
        with mock.patch('athenz.verification.shutil.which', return_value='/usr/bin/docker'), \
             mock.patch('athenz.verification.subprocess.run', side_effect=self.mocked_docker()):
            evidence = self.ctl.verify_container('math', image=IMAGE)
        self.assertEqual(evidence['returncode'], 0)
        self.assertEqual(evidence['runner'], 'docker-local-observation')
        self.assertEqual(evidence['tracked_files'], 3)
        self.assertEqual(evidence['output_sha256'], hashlib.sha256('Ran 1 test\n'.encode()).hexdigest())
        self.assertEqual(len(self.store.list_items('test_runs')), 3)
        self.assertEqual(self.ctl._load('math')[1]['behavioral_evidence']['stored_excerpt_sha256'],
                         self.store.db.execute('SELECT output_sha256 FROM test_runs ORDER BY id DESC LIMIT 1').fetchone()[0])
        bundle = self.ctl.export('math')
        self.assertEqual(bundle['verification'], 'container-tests-observed')
        self.assertEqual(bundle['behavioral_evidence']['snapshot_sha256'], evidence['snapshot_sha256'])
        self.assertEqual(git(self.repo, 'status', '--porcelain=v1'), '')
        self.ctl.cancel('math', discard_changes=True)

    def test_failure_is_never_reported_as_verified_success(self):
        self.finish()
        with mock.patch('athenz.verification.shutil.which', return_value='/usr/bin/docker'), \
             mock.patch('athenz.verification.subprocess.run', side_effect=self.mocked_docker(code=1)):
            evidence = self.ctl.verify_container('math', image=IMAGE)
        self.assertEqual(evidence['returncode'], 1)
        bundle = self.ctl.export('math')
        self.assertEqual(bundle['verification'], 'container-tests-failed')
        self.ctl.cancel('math', discard_changes=True)

    def test_missing_docker_fails_closed_and_no_auto_learning(self):
        self.finish()
        with mock.patch('athenz.verification.shutil.which', return_value=None):
            with self.assertRaisesRegex(WorktreeError, 'Docker is unavailable'):
                self.ctl.verify_container('math', image=IMAGE)
        self.assertIsNone(self.ctl._load('math')[1].get('behavioral_evidence'))
        self.assertEqual(self.ctl.export('math')['verification'], 'syntax-only')
        self.ctl.cancel('math', discard_changes=True)

    def test_reject_image_bad_phase_and_tampered_source(self):
        with self.assertRaises(SequenceError):
            self.ctl.verify_container('math', image=IMAGE)
        self.finish()
        with self.assertRaises(ValueError):
            self.ctl.verify_container('math', image='python:latest')
        worktree = Path(self.ctl.worker.resume('math')['state']['workspace'])
        (worktree / 'util.py').write_text('changed unexpectedly\n')
        with self.assertRaises(SequenceError):
            self.ctl.verify_container('math', image=IMAGE)
        self.ctl.cancel('math', discard_changes=True)

    def test_sensitive_variants_are_not_copied_into_docker_snapshot(self):
        self.ctl.cancel('math')
        for sensitive in ('.env.production', 'secrets.yaml', 'credentials.json',
                          'archive/owner.sqlite3', '.aws/credentials'):
            with self.subTest(name=sensitive):
                path = self.repo / sensitive
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('SYNTHETIC_NEVER_COPY', encoding='utf-8')
                git(self.repo, 'add', sensitive)
                git(self.repo, 'commit', '-m', 'synthetic protected path')
                with tempfile.TemporaryDirectory() as folder:
                    with self.assertRaisesRegex(WorktreeError, 'Sensitive'):
                        snapshot_files(self.repo, Path(folder))

    def test_hardlinked_tracked_file_is_refused_in_docker_snapshot(self):
        import os
        self.ctl.cancel('math')
        external = self.root / 'private-synthetic-file'
        external.write_text('secret')
        linked = self.repo / 'ordinary.py'
        try:
            os.link(external, linked)
        except (OSError, NotImplementedError):
            self.skipTest('Host does not support synthetic hard links')
        git(self.repo, 'add', 'ordinary.py')
        git(self.repo, 'commit', '-m', 'test hardlink')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(WorktreeError, 'hard-linked'):
                snapshot_files(self.repo, Path(tmp))

    def test_sensitive_tracked_file_disallows_snapshot(self):
        self.ctl.cancel('math')
        (self.repo / '.env').write_text('SYNTHETIC=1')
        git(self.repo, 'add', '.env')
        git(self.repo, 'commit', '-m', 'fake secret')
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(WorktreeError):
                snapshot_files(self.repo, Path(t))


if __name__ == '__main__':
    unittest.main()
