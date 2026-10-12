"""Synthetic health inspections; no real user profile or network access."""
from __future__ import annotations

from contextlib import closing, redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from athenz.profile_health import ProfileHealthError, inspect_profile, main


class ProfileHealthTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.parent = Path(temp.name)
        self.home = self.parent / 'private'

    def _make_database(self):
        self.home.mkdir(mode=0o700)
        db = self.home / 'identity.sqlite3'
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute('PRAGMA user_version=5')
            conn.execute('CREATE TABLE secrets (private_text TEXT)')
            conn.execute("INSERT INTO secrets VALUES ('DO-NOT-REVEAL-ME')")
        if os.name != 'nt':
            db.chmod(0o600)
        return db

    def test_requires_confirm_before_accessing_filesystem(self):
        with patch('athenz.profile_health._home_location', side_effect=AssertionError('access')):
            with self.assertRaisesRegex(ProfileHealthError, 'confirm'):
                inspect_profile(self.home)

    def test_no_profile_is_not_initialized_and_does_not_create_it(self):
        result = inspect_profile(self.home, confirmed=True)
        self.assertEqual(result['status'], 'not-initialized')
        self.assertFalse(result['database_present'])
        self.assertFalse(self.home.exists())
        self.assertFalse(result['deploy_authorized'])

    def test_readonly_integrity_never_exposes_private_rows(self):
        db = self._make_database()
        before = db.read_bytes()
        result = inspect_profile(self.home, confirmed=True)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['schema_version'], 5)
        self.assertFalse(result['private_data_collected'])
        self.assertFalse(result['recovery_validated'])
        self.assertNotIn('DO-NOT-REVEAL-ME', json.dumps(result))
        self.assertEqual(db.read_bytes(), before)

    def test_invalid_database_is_reported_without_leaking_sqlite_error(self):
        self.home.mkdir(mode=0o700)
        (self.home / 'identity.sqlite3').write_bytes(b'not a SQLite database')
        result = inspect_profile(self.home, confirmed=True)
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn(str(self.home), str(result))

    def test_refuses_unsafe_sqlite_sidecars(self):
        self._make_database()
        target = self.parent / 'external'
        target.write_text('private', encoding='utf-8')
        try:
            (self.home / 'identity.sqlite3-wal').symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation not permitted on this system')
        with self.assertRaisesRegex(ProfileHealthError, 'symlinked SQLite'):
            inspect_profile(self.home, confirmed=True)
        self.assertEqual(target.read_text(), 'private')

    def test_refuses_symlinked_parent_and_git_checkout(self):
        target = self.parent / 'external'
        target.mkdir()
        link = self.parent / 'alias'
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            pass  # Git-checkout refusal below still needs coverage on Windows.
        else:
            with self.assertRaisesRegex(ProfileHealthError, 'symlinked private profile'):
                inspect_profile(link / 'subdir', confirmed=True)
        repo = self.parent / 'repo'
        repo.mkdir()
        (repo / '.git').mkdir()
        with self.assertRaisesRegex(ProfileHealthError, 'outside any Git'):
            inspect_profile(repo / 'private', confirmed=True)

    def test_refuses_shared_home_on_posix(self):
        if os.name == 'nt':
            self.skipTest('POSIX directory permissions only')
        self.home.mkdir(mode=0o700)
        self.home.chmod(0o755)
        with self.assertRaisesRegex(ProfileHealthError, 'accessible to others'):
            inspect_profile(self.home, confirmed=True)

    def test_timeout_must_be_bounded(self):
        for value in (0, 16, True, 1.5):
            with self.assertRaisesRegex(ProfileHealthError, 'timeout'):
                inspect_profile(self.home, confirmed=True, timeout_seconds=value)

    def test_cli_json_is_sanitized(self):
        self._make_database()
        buf = io.StringIO()
        with redirect_stdout(buf):
            main(['--home', str(self.home), '--confirm'])
        result = json.loads(buf.getvalue())
        self.assertEqual(result['status'], 'ok')
        self.assertNotIn('DO-NOT-REVEAL-ME', buf.getvalue())
        self.assertNotIn(str(self.home), buf.getvalue())

    def test_wal_live_reader_does_not_mutate_records(self):
        self._make_database()
        db = self.home / 'identity.sqlite3'
        with closing(sqlite3.connect(db)) as writer, writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute("INSERT INTO secrets VALUES ('WAL-private-value')")
            result = inspect_profile(self.home, confirmed=True)
            self.assertIn(result['status'], ('ok', 'unavailable'))
            self.assertNotIn('WAL-private-value', json.dumps(result))
            saved = writer.execute('SELECT count(*) FROM secrets').fetchone()[0]
            self.assertEqual(saved, 2)


if __name__ == '__main__':
    unittest.main()
