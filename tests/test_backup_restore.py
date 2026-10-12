"""Synthetic offline recovery tests: strict no-clobber and authority disarming."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from athenz.backup import BackupError, create_backup, restore_to_new_profile
from athenz.experience import ExperienceStore


class OfflineRestoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'private'
        with_store = ExperienceStore(self.home)
        with_store.propose('preference', 'Synthetic approved preference', source='owner', approved=True)
        with_store.checkpoint('ollama_runtime', 'Routing', {'active_tag': 'old-tag'}, status='paused')
        with_store.checkpoint('job', 'Task', {'repo': 'not-copied'}, status='running')
        with with_store.db:
            with_store.db.execute('''CREATE TABLE proposal_schedule (
                task_key TEXT PRIMARY KEY, state TEXT NOT NULL, lease TEXT,
                last_result TEXT NOT NULL DEFAULT '')''')
            with_store.db.execute("INSERT INTO proposal_schedule VALUES ('job','armed','old-lease','active')")
        with_store.close()
        self.backup = create_backup(self.home, confirmed=True)
        self.dest = self.root / 'recovered'

    def test_recovery_requires_confirmation_and_preserves_source(self):
        with self.assertRaisesRegex(BackupError, 'confirm'):
            restore_to_new_profile(self.home, self.backup['id'], self.dest)
        outcome = restore_to_new_profile(self.home, self.backup['id'], self.dest, confirmed=True)
        self.assertFalse(outcome['external_files_restored'])
        self.assertTrue((self.dest / 'recovery.json').is_file())
        with closing(sqlite3.connect(self.dest / 'identity.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT text FROM identity').fetchone()[0], 'Synthetic approved preference')
            self.assertEqual(db.execute("SELECT count(*) FROM checkpoints WHERE task_key='ollama_runtime'").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT status FROM checkpoints WHERE task_key='job'").fetchone()[0], 'paused')
            self.assertEqual(db.execute('SELECT state,lease FROM proposal_schedule').fetchone(), ('paused', None))
        with closing(sqlite3.connect(self.home / 'identity.sqlite3')) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM checkpoints WHERE task_key='ollama_runtime'").fetchone()[0], 1)
        self.assertTrue((self.home / 'backups' / f"profile-{self.backup['id']}.sqlite3").is_file())

    def test_existing_profile_never_overwritten(self):
        self.dest.mkdir()
        (self.dest / 'identity.sqlite3').write_text('sentinel')
        with self.assertRaisesRegex(BackupError, 'must not exist'):
            restore_to_new_profile(self.home, self.backup['id'], self.dest, confirmed=True)
        self.assertEqual((self.dest / 'identity.sqlite3').read_text(), 'sentinel')

    def test_invalid_or_tampered_backup_leaves_no_destination(self):
        snapshot = self.home / 'backups' / f"profile-{self.backup['id']}.sqlite3"
        snapshot.write_bytes(b'corrupted')
        with self.assertRaises(BackupError):
            restore_to_new_profile(self.home, self.backup['id'], self.dest, confirmed=True)
        self.assertFalse(self.dest.exists())

    def test_git_destination_refused(self):
        repo = self.root / 'repo'
        repo.mkdir()
        (repo / '.git').mkdir()
        with self.assertRaisesRegex(BackupError, 'Git checkout'):
            restore_to_new_profile(self.home, self.backup['id'], repo / 'recovery', confirmed=True)

    def test_symlink_destination_refused(self):
        try:
            (self.root / 'alias').symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlinks unavailable on this runner')
        with self.assertRaisesRegex(BackupError, 'symlink'):
            restore_to_new_profile(self.home, self.backup['id'], self.root / 'alias' / 'recovery', confirmed=True)

    def test_source_inside_dest_and_dest_inside_source_refused(self):
        with self.assertRaisesRegex(BackupError, 'outside'):
            restore_to_new_profile(self.home, self.backup['id'], self.home / 'recovered', confirmed=True)
        with self.assertRaisesRegex(BackupError, 'must not exist'):
            restore_to_new_profile(self.home, self.backup['id'], self.root, confirmed=True)


if __name__ == '__main__':
    unittest.main()
