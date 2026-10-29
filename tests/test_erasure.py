"""Erasure threat tests: forgotten personal content must not survive in the
raw SQLite database, its write-ahead log, or later backups. Synthetic only."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from athenz.backup import create_backup, verify_backup
from athenz.experience import ExperienceStore


def raw_profile_bytes(home: Path) -> bytes:
    """Every byte a forensic reader of the profile directory could scan."""
    data = b''
    for name in ('identity.sqlite3', 'identity.sqlite3-wal'):
        path = home / name
        if path.exists():
            data += path.read_bytes()
    return data


class ErasureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / 'private'
        self.store = ExperienceStore(self.home)
        self.addCleanup(self.store.close)

    def test_secure_delete_pragma_is_enabled(self):
        self.assertEqual(
            self.store.db.execute('PRAGMA secure_delete').fetchone()[0], 1)

    def test_deleted_identity_and_its_revisions_leave_no_bytes(self):
        marker_old = 'ERASURE-MARKER-OLD-51af'
        marker_new = 'ERASURE-MARKER-NEW-51af'
        item = self.store.propose('preference', marker_old, source='owner')
        self.store.revise(item, marker_new, 'synthetic correction')
        before = raw_profile_bytes(self.home)
        self.assertIn(marker_old.encode(), before)  # sanity: test not vacuous
        self.assertIn(marker_new.encode(), before)
        self.assertTrue(self.store.delete('identity', item))
        after = raw_profile_bytes(self.home)
        self.assertNotIn(marker_old.encode(), after)
        self.assertNotIn(marker_new.encode(), after)
        self.assertEqual(self.store.list_items('identity'), [])

    def test_purged_source_leaves_no_bytes_and_other_sources_survive(self):
        marker = 'ERASURE-MARKER-PURGE-77b2'
        self.store.propose('knowledge', marker, source='import-x', source_ref='doc1')
        self.store.add_sample(marker, source='import-x', source_ref='doc1')
        keeper = self.store.propose('knowledge', 'synthetic keeper text',
                                    source='owner')
        self.assertIn(marker.encode(), raw_profile_bytes(self.home))
        counts = self.store.purge_source('import-x', 'doc1')
        self.assertEqual(counts['identity'], 1)
        self.assertEqual(counts['writing_samples'], 1)
        self.assertNotIn(marker.encode(), raw_profile_bytes(self.home))
        rows = self.store.list_items('identity')
        self.assertEqual([r['id'] for r in rows], [keeper])

    def test_forgotten_episode_leaves_no_bytes(self):
        marker = 'ERASURE-MARKER-EPISODE-03cd'
        episode = self.store.observe('synthetic topic', marker,
                                     tags=['synthetic'], source='owner')
        self.assertIn(marker.encode(), raw_profile_bytes(self.home))
        self.assertTrue(self.store.forget_episode(episode))
        self.assertNotIn(marker.encode(), raw_profile_bytes(self.home))

    def test_deleted_session_messages_leave_no_bytes(self):
        marker = 'ERASURE-MARKER-SESSION-9e10'
        self.store.add_message('synthetic-session', 'agent', 'user', marker)
        self.assertIn(marker.encode(), raw_profile_bytes(self.home))
        self.assertEqual(self.store.delete_session('synthetic-session'), 1)
        self.assertNotIn(marker.encode(), raw_profile_bytes(self.home))

    def test_backup_taken_after_erasure_contains_no_marker(self):
        marker = 'ERASURE-MARKER-BACKUP-64d8'
        item = self.store.propose('preference', marker, source='owner')
        self.store.delete('identity', item)
        created = create_backup(self.home, confirmed=True)
        self.assertTrue(verify_backup(self.home, created['id'])['valid'])
        snapshot = self.home / 'backups' / f"profile-{created['id']}.sqlite3"
        self.assertNotIn(marker.encode(), snapshot.read_bytes())


if __name__ == '__main__':
    unittest.main()
