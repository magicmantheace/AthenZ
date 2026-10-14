"""Synthetic acceptance status tests: no real hardware, model or network."""
from __future__ import annotations
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.release_readiness import (CHECKS, ReadinessError, acceptance_plan,
                                      main, record, status_report, history_report)


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

    def test_owner_status_changes_keep_non_authorizing_local_history(self):
        import sqlite3
        check = CHECKS[0][0]
        record(self.home, check, 'failed', confirmed=True)
        record(self.home, check, 'blocked', confirmed=True)
        record(self.home, check, 'passed', confirmed=True)
        report = status_report(self.home)
        self.assertEqual(report['owner_observation_history_events'], 3)
        self.assertEqual(report['requirements'][0]['status'], 'passed')
        self.assertFalse(report['release_certified'])
        with closing(sqlite3.connect(self.home / 'release-acceptance.sqlite3')) as db:
            history = db.execute(
                'SELECT status FROM observation_history WHERE check_id=? ORDER BY id',
                (check,)).fetchall()
        self.assertEqual(history, [('failed',), ('blocked',), ('passed',)])

    def test_invalid_database_status_fails_closed(self):
        import sqlite3
        check = CHECKS[0][0]
        record(self.home, check, 'passed', confirmed=True)
        with closing(sqlite3.connect(self.home / 'release-acceptance.sqlite3')) as db, db:
            db.execute('UPDATE observations SET status=? WHERE check_id=?',
                       ('unverified-external-certification', check))
        with self.assertRaisesRegex(ReadinessError, 'observations are invalid'):
            status_report(self.home)

    def test_current_status_cannot_disagree_with_latest_owner_history(self):
        import sqlite3
        key = CHECKS[0][0]
        record(self.home, key, 'failed', confirmed=True)
        with closing(sqlite3.connect(self.home / 'release-acceptance.sqlite3')) as db, db:
            db.execute('UPDATE observations SET status=? WHERE check_id=?',
                       ('passed', key))
        with self.assertRaisesRegex(ReadinessError, 'history disagrees'):
            status_report(self.home)
        # A subsequent explicit owner record becomes a new, reviewable event.
        record(self.home, key, 'passed', confirmed=True)
        report = status_report(self.home)
        self.assertEqual(report['requirements'][0]['status'], 'passed')
        self.assertEqual(report['owner_observation_history_events'], 2)

    def test_legacy_unanchored_acceptance_row_remains_readable(self):
        import sqlite3
        key = CHECKS[0][0]
        record(self.home, key, 'blocked', confirmed=True)
        with closing(sqlite3.connect(self.home / 'release-acceptance.sqlite3')) as db, db:
            db.execute('DELETE FROM observation_history WHERE check_id=?', (key,))
        report = status_report(self.home)
        self.assertEqual(report['requirements'][0]['status'], 'blocked')
        self.assertEqual(report['owner_observation_history_events'], 0)

    def test_history_is_read_only_bounded_and_keeps_status_order(self):
        check = CHECKS[0][0]
        self.assertEqual(history_report(self.home), {
            'schema': 1, 'events': [], 'count': 0,
            'independently_attested': False, 'release_certified': False})
        self.assertFalse(self.home.exists())
        for status in ('failed', 'blocked', 'passed'):
            record(self.home, check, status, confirmed=True)
        history = history_report(self.home, limit=2)
        self.assertEqual([x['status'] for x in history['events']],
                         ['passed', 'blocked'])
        self.assertEqual(history['count'], 2)
        self.assertFalse(history['independently_attested'])
        self.assertEqual(status_report(self.home)['requirements'][0]['status'],
                         'passed')

    def test_history_cli_is_read_only_and_limit_checked(self):
        with patch('builtins.print') as printer:
            main(['--home', str(self.home), 'history', '--limit', '5'])
        output = json.loads(printer.call_args.args[0])
        self.assertEqual(output['events'], [])
        self.assertFalse(self.home.exists())
        for invalid in (0, -1, 101, True):
            with self.subTest(limit=invalid):
                with self.assertRaisesRegex(ReadinessError, 'History limit'):
                    history_report(self.home, limit=invalid)

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


    def test_deleted_current_row_cannot_hide_prior_failed_acceptance(self):
        import sqlite3
        key = CHECKS[0][0]
        record(self.home, key, 'failed', confirmed=True)
        with closing(sqlite3.connect(self.home / 'release-acceptance.sqlite3')) as db, db:
            db.execute('DELETE FROM observations WHERE check_id=?', (key,))
        with self.assertRaisesRegex(ReadinessError, 'history disagrees'):
            status_report(self.home)

    def test_corrupted_older_history_is_not_ignored_when_latest_is_valid(self):
        import sqlite3
        key = CHECKS[0][0]
        record(self.home, key, 'failed', confirmed=True)
        record(self.home, key, 'passed', confirmed=True)
        with closing(sqlite3.connect(self.home / 'release-acceptance.sqlite3')) as db, db:
            db.execute("UPDATE observation_history SET source='synthetic-forgery' "
                       "WHERE id=(SELECT MIN(id) FROM observation_history)")
        with self.assertRaisesRegex(ReadinessError, 'history is invalid'):
            status_report(self.home)

    def test_rejects_hardlinked_acceptance_database_without_modifying_source(self):
        import os
        if os.name == 'nt':
            self.skipTest('Hardlink fixture depends on POSIX filesystem semantics')
        self.home.mkdir(mode=0o700)
        external = self.home.parent / 'other-database'
        external.write_bytes(b'private-fixture-contents')
        external.chmod(0o600)
        os.link(external, self.home / 'release-acceptance.sqlite3')
        with self.assertRaisesRegex(ReadinessError, 'Unsafe private acceptance database'):
            status_report(self.home)
        with self.assertRaisesRegex(ReadinessError, 'Unsafe private acceptance database'):
            record(self.home, CHECKS[0][0], 'passed', confirmed=True)
        self.assertEqual(external.read_bytes(), b'private-fixture-contents')

    def test_rejects_existing_world_readable_acceptance_database_on_posix(self):
        import os
        if os.name == 'nt':
            self.skipTest('POSIX permission modes')
        self.home.mkdir(mode=0o700)
        unsafe = self.home / 'release-acceptance.sqlite3'
        unsafe.write_bytes(b'synthetic')
        unsafe.chmod(0o644)
        with self.assertRaisesRegex(ReadinessError, 'Unsafe private acceptance database'):
            status_report(self.home)
        self.assertEqual(unsafe.read_bytes(), b'synthetic')

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
