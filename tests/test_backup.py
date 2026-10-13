"""Backups of synthetic private records only; no cloud services or restore."""
import json
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from athenz.backup import BackupError, create_backup, verify_backup, delete_backup, list_backups
from athenz.experience import ExperienceStore


class BackupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / 'home'
        store = ExperienceStore(self.home)
        store.propose('preference', 'Synthetic local data', source='owner', approved=True)
        store.close()

    def test_backup_is_explicit_complete_private_and_verifiable(self):
        with self.assertRaisesRegex(BackupError, 'confirm'):
            create_backup(self.home)
        created = create_backup(self.home, confirmed=True)
        self.assertEqual(created['scope'], 'sqlite-only')
        self.assertFalse(created['encrypted'])
        self.assertTrue(verify_backup(self.home, created['id'])['valid'])
        self.assertEqual(list_backups(self.home), [created['id']])
        snapshot = self.home / 'backups' / f"profile-{created['id']}.sqlite3"
        # Test a separate SQLite reader can recover the reviewed record.
        import sqlite3
        with closing(sqlite3.connect(snapshot)) as db:
            self.assertEqual(db.execute('SELECT text FROM identity').fetchone()[0], 'Synthetic local data')

    def test_backup_consistent_when_live_connection_uses_wal(self):
        store = ExperienceStore(self.home)
        try:
            store.propose('identity', 'Synthetic recent WAL committed row', source='owner')
            latest = create_backup(self.home, confirmed=True)
            self.assertTrue(verify_backup(self.home, latest['id'])['valid'])
            import sqlite3
            with closing(sqlite3.connect(self.home/'backups'/f"profile-{latest['id']}.sqlite3")) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM identity').fetchone()[0], 2)
        finally:
            store.close()

    def test_tamper_is_rejected_and_no_auto_restore(self):
        b = create_backup(self.home, confirmed=True)
        snapshot = self.home / 'backups' / f"profile-{b['id']}.sqlite3"
        snapshot.write_bytes(b'changed')
        with self.assertRaisesRegex(BackupError, 'changed'):
            verify_backup(self.home, b['id'])
        source = ExperienceStore(self.home)
        try:
            self.assertEqual(source.db.execute('SELECT count(*) FROM identity').fetchone()[0], 1)
        finally:
            source.close()

    def test_corrupt_outer_manifest_has_only_sanitized_backup_errors(self):
        b = create_backup(self.home, confirmed=True)
        manifest = self.home/'backups'/f"profile-{b['id']}.manifest.json"
        original = json.loads(manifest.read_text())
        for corrupt in ([], 'PRIVATE-SECRET', None, True,
                        {**original, 'size': True},
                        {**original, 'sqlite_schema': True},
                        {**original, 'sha256': 123},
                        {**original, 'schema': True}):
            with self.subTest(case=repr(corrupt)[:50]):
                manifest.write_text(json.dumps(corrupt))
                with self.assertRaisesRegex(BackupError, 'manifest'):
                    verify_backup(self.home, b['id'])
        manifest.write_text(json.dumps(original))
        self.assertTrue(verify_backup(self.home, b['id'])['valid'])

    def test_manifest_edit_and_invalid_id_rejected(self):
        b = create_backup(self.home, confirmed=True)
        manifest = self.home/'backups'/f"profile-{b['id']}.manifest.json"
        record = json.loads(manifest.read_text())
        record['restore_authorized'] = True
        manifest.write_text(json.dumps(record))
        with self.assertRaisesRegex(BackupError, 'manifest'):
            verify_backup(self.home, b['id'])
        with self.assertRaises(BackupError):
            verify_backup(self.home, '../outside')

    def test_symlinked_backup_folder_rejected(self):
        try:
            (self.home/'backups').symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Windows runner does not permit user symlinks')
        with self.assertRaisesRegex(BackupError, 'symlink'):
            create_backup(self.home, confirmed=True)

    def test_backups_refuse_git_home(self):
        (self.root/'.git').mkdir()
        with self.assertRaisesRegex(ValueError, 'Git checkout'):
            create_backup(self.home, confirmed=True)

    def test_deletion_explicit_scoped_and_idempotent(self):
        b = create_backup(self.home, confirmed=True)
        with self.assertRaisesRegex(BackupError, 'confirm'):
            delete_backup(self.home, b['id'])
        self.assertTrue(verify_backup(self.home, b['id'])['valid'])
        self.assertTrue(delete_backup(self.home, b['id'], confirmed=True))
        self.assertFalse(delete_backup(self.home, b['id'], confirmed=True))
        self.assertEqual(list_backups(self.home), [])


if __name__ == '__main__':
    unittest.main()
