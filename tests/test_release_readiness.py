"""Synthetic acceptance status tests: no real hardware, model or network."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.release_readiness import (CHECKS, ReadinessError, acceptance_plan,
                                      main, record, status_report)


class ReleaseReadinessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / 'private'

    def test_plan_is_public_pure_readonly_and_not_certified(self):
        p = acceptance_plan()
        self.assertFalse(p['starts_work'])
        self.assertFalse(p['runs_hardware_tests'])
        self.assertFalse(p['automated_attestation'])
        self.assertGreaterEqual(len(p['requirements']), 8)
        self.assertFalse(self.home.exists())

    def test_status_does_not_create_database_and_not_ready(self):
        report = status_report(self.home)
        self.assertEqual(report['recorded'], 0)
        self.assertFalse(report['release_certified'])
        self.assertFalse(report['all_owner_reported_passed'])
        self.assertFalse(self.home.exists())

    def test_explicit_record_and_restart_idempotent(self):
        key = CHECKS[0][0]
        with self.assertRaisesRegex(ReadinessError, 'confirm'):
            record(self.home, key, 'passed')
        self.assertFalse(self.home.exists())
        changed = record(self.home, key, 'failed', confirmed=True)
        self.assertFalse(changed['independently_attested'])
        self.assertEqual(status_report(self.home)['requirements'][0]['status'], 'failed')
        record(self.home, key, 'passed', confirmed=True)
        report = status_report(self.home)
        self.assertEqual(report['recorded'], 1)
        self.assertEqual(report['requirements'][0]['status'], 'passed')
        self.assertFalse(report['release_certified'])
        self.assertFalse(report['model_deployment_authorized'])

    def test_all_manually_passed_never_certifies_hardware(self):
        for key, _ in CHECKS:
            record(self.home, key, 'passed', confirmed=True)
        report = status_report(self.home)
        self.assertTrue(report['all_owner_reported_passed'])
        self.assertFalse(report['release_certified'])
        self.assertFalse(report['hardware_independently_validated'])

    def test_invalid_record_never_touches_disk(self):
        for key, status in [('not-a-check', 'passed'), (CHECKS[0][0], 'verified')]:
            with self.subTest(key=key, status=status):
                with self.assertRaises(ReadinessError):
                    record(self.home, key, status, confirmed=True)
        self.assertFalse(self.home.exists())

    def test_rejects_private_home_inside_git_and_symlink(self):
        repo = self.home.parent / 'repo'
        repo.mkdir()
        (repo / '.git').mkdir()
        with self.assertRaisesRegex(ReadinessError, 'Git checkout'):
            record(repo / 'private', CHECKS[0][0], 'passed', confirmed=True)
        symlink = self.home.parent / 'symlink'
        symlink.symlink_to(repo, target_is_directory=True)
        with self.assertRaisesRegex(ReadinessError, 'symlink'):
            status_report(symlink)
        self.assertFalse((repo / 'private').exists())

    def test_refuses_existing_shared_private_directory_on_posix(self):
        import os
        if os.name == 'nt':
            self.skipTest('POSIX directory permission checks')
        self.home.mkdir(mode=0o700)
        self.home.chmod(0o755)
        with self.assertRaisesRegex(ReadinessError, 'group or other'):
            record(self.home, CHECKS[0][0], 'passed', confirmed=True)
        self.assertFalse((self.home / 'release-acceptance.sqlite3').exists())

    def test_refuses_symlinked_database(self):
        self.home.mkdir(mode=0o700)
        out = self.home.parent / 'other.db'
        out.write_bytes(b'secret')
        (self.home / 'release-acceptance.sqlite3').symlink_to(out)
        with self.assertRaisesRegex(ReadinessError, 'Unsafe'):
            status_report(self.home)
        with self.assertRaisesRegex(ReadinessError, 'Unsafe'):
            record(self.home, CHECKS[0][0], 'passed', confirmed=True)
        self.assertEqual(out.read_bytes(), b'secret')

    def test_cli_plan_does_not_probe_communicate_or_create_files(self):
        with patch('athenz.release_readiness.sqlite3.connect', side_effect=AssertionError('no database calls')), \
             patch('athenz.release_readiness.os.system', side_effect=AssertionError('no shell')):
            with patch('builtins.print') as display:
                main(['--home', str(self.home), 'plan'])
        obj = json.loads(display.call_args.args[0])
        self.assertFalse(obj['launches_models'])
        self.assertFalse(self.home.exists())


if __name__ == '__main__':
    unittest.main()
