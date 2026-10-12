"""Check private memory cannot accidentally live inside Git or unsafe links."""
from __future__ import annotations
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from athenz.store import IdentityStore, private_home_path


class PrivateProfileGuards(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_private_home_inside_checkout_rejected_without_creating_data(self):
        repo = self.root / 'repo'
        repo.mkdir()
        (repo/'.git').mkdir()
        home = repo/'build'/'private'
        with self.assertRaisesRegex(ValueError, 'inside a Git checkout'):
            IdentityStore(home)
        self.assertFalse(home.exists())

    def test_git_worktree_marker_file_is_also_rejected(self):
        checkout = self.root/'worktree'; checkout.mkdir()
        (checkout/'.git').write_text('gitdir: elsewhere', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'inside a Git checkout'):
            private_home_path(checkout/'sensitive')
        self.assertFalse((checkout/'sensitive').exists())

    def test_existing_symlink_parent_rejected_without_following_it(self):
        actual = self.root/'actual'; actual.mkdir()
        alias = self.root/'alias'
        try:
            alias.symlink_to(actual, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation unavailable here')
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            IdentityStore(alias/'private')
        self.assertFalse((actual/'private').exists())

    def test_existing_database_symlink_rejected_before_connection(self):
        home=self.root/'private'; home.mkdir()
        external=self.root/'untouched';external.write_bytes(b'original')
        try:
            (home/'identity.sqlite3').symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation unavailable')
        with self.assertRaisesRegex(ValueError, 'sidecar cannot be a pointer'):
            IdentityStore(home)
        self.assertEqual(external.read_bytes(), b'original')

    def test_existing_wal_symlink_rejected_even_if_database_not_initialized(self):
        home=self.root/'private';home.mkdir()
        external=self.root/'outside'; external.write_bytes(b'private')
        try:
            (home/'identity.sqlite3-wal').symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation unavailable')
        with self.assertRaisesRegex(ValueError, 'sidecar cannot be a pointer'):
            IdentityStore(home)
        self.assertFalse((home/'identity.sqlite3').exists())

    def test_normal_standalone_private_directory_remains_operational(self):
        home=self.root/'owner-private'
        with patch.dict(os.environ, {'ATHENZ_HOME':str(home)}):
            store=IdentityStore()
            try:
                row=store.propose('preference','Synthetic approved value',source='owner',approved=True)
                self.assertGreater(row,0)
            finally: store.close()
        self.assertTrue((home/'identity.sqlite3').is_file())
        if os.name!='nt':
            self.assertEqual(home.stat().st_mode & 0o077,0)

if __name__=='__main__':
    unittest.main()
