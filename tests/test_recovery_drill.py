"""Disposable SQLite recovery rehearsal: private inputs, synthetic records only."""
from __future__ import annotations

import json
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.backup import create_backup
from athenz.experience import ExperienceStore
from athenz.recovery_drill import (RecoveryDrillError, rehearse_sqlite_backup,
                                   MAX_SNAPSHOT, MIN_FREE_MARGIN, main)


class RecoveryDrillTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.base = Path(t.name)
        self.home = self.base / 'private'
        self.scratch = self.base / 'scratch'
        self.scratch.mkdir()

    def _backup(self):
        store = ExperienceStore(self.home)
        try:
            store.propose('preference', 'synthetic do-not-print private preference',
                          source='synthetic', approved=True)
            store.checkpoint('ollama_runtime', 'synthetic', {'example': True})
            store.checkpoint('active-worker', 'synthetic', {'paused': False}, status='running')
        finally:
            store.close()
        # Deliberately seed a stale active lease. A recovered profile must
        # never inherit this execution authority.
        store = ExperienceStore(self.home)
        try:
            with store.db:
                store.db.execute("""CREATE TABLE proposal_schedule (
                    task_key TEXT PRIMARY KEY, scope_sha256 TEXT NOT NULL,
                    model_name TEXT NOT NULL, state TEXT NOT NULL, lease TEXT,
                    last_result TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
                store.db.execute("""INSERT INTO proposal_schedule
                    (task_key,scope_sha256,model_name,state,lease,created_at,updated_at)
                    VALUES ('synthetic-task',?,'synthetic-model','running',?, ?, ?)""",
                    ('0'*64, 'f'*32, '2026-01-01', '2026-01-01'))
        finally:
            store.close()
        return create_backup(self.home, confirmed=True)['id']

    def test_selected_bundle_recovery_rehearsal_disarms_and_deletes_copy(self):
        from athenz.profile_bundle import create_bundle
        from athenz.recovery_drill import rehearse_profile_bundle
        store = ExperienceStore(self.home)
        try:
            store.propose('style', 'PRIVATE-BUNDLE-OWNER-RECORD',
                          source='synthetic', approved=True)
            store.checkpoint('ollama_runtime', 'synthetic', {'active_tag': 'unsafe'})
            store.checkpoint('active-worker', 'synthetic', {'secret': 'not-displayed'},
                             status='running')
            with store.db:
                store.db.execute("""CREATE TABLE proposal_schedule (
                    task_key TEXT PRIMARY KEY, scope_sha256 TEXT NOT NULL,
                    model_name TEXT NOT NULL, state TEXT NOT NULL, lease TEXT,
                    last_result TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
                store.db.execute("""INSERT INTO proposal_schedule
                    (task_key,scope_sha256,model_name,state,lease,created_at,updated_at)
                    VALUES ('synthetic-bundle-task',?,'test-model','running',?, ?, ?)""",
                    ('0'*64, 'f'*32, '2026-01-01', '2026-01-01'))
        finally:
            store.close()
        (self.home / 'datasets').mkdir()
        (self.home / 'datasets' / 'synthetic.jsonl').write_bytes(b'PRIVATE-DATA')
        (self.home / 'runs' / 'local' / 'adapter').mkdir(parents=True)
        (self.home / 'runs' / 'local' / 'adapter' / 'adapter_model.safetensors').write_bytes(
            b'PRIVATE-ADAPTER')
        bundle = create_bundle(self.home, confirmed=True)
        original_archive = (self.home / 'bundles' / f"bundle-{bundle['id']}.zip").read_bytes()
        with self.assertRaisesRegex(RecoveryDrillError, 'confirm'):
            rehearse_profile_bundle(self.home, bundle['id'], scratch_root=self.scratch)
        result = rehearse_profile_bundle(self.home, bundle['id'], confirmed=True,
                                         scratch_root=self.scratch)
        self.assertTrue(result['rehearsal_passed'])
        self.assertEqual(result['selected_files_verified'], 3)
        self.assertTrue(result['temp_profile_deleted'])
        self.assertTrue(result['scheduler_disarmed'])
        self.assertTrue(result['model_routing_reset'])
        self.assertFalse(result['externally_installed_models_restored'])
        self.assertFalse(result['live_profile_replaced'])
        self.assertNotIn('PRIVATE', json.dumps(result))
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertEqual((self.home / 'bundles' / f"bundle-{bundle['id']}.zip").read_bytes(),
                         original_archive)
        with patch('builtins.print') as shown:
            main([bundle['id'], '--bundle', '--home', str(self.home),
                  '--scratch', str(self.scratch), '--confirm'])
        cli = json.loads(shown.call_args.args[0])
        self.assertEqual(cli['backup_type'], 'selected-profile-bundle')
        self.assertNotIn(str(self.home), json.dumps(cli))

    def test_bundle_rehearsal_sanitizes_failed_temporary_restore(self):
        from athenz.profile_bundle import create_bundle
        from athenz.recovery_drill import rehearse_profile_bundle
        store = ExperienceStore(self.home)
        store.close()
        bundle = create_bundle(self.home, confirmed=True)
        with patch('athenz.recovery_drill.restore_bundle_new',
                   side_effect=OSError('PRIVATE-OWNER-PATH-OR-PROMPT')):
            with self.assertRaisesRegex(RecoveryDrillError, 'Temporary private bundle') as caught:
                rehearse_profile_bundle(self.home, bundle['id'], confirmed=True,
                                        scratch_root=self.scratch)
        self.assertNotIn('PRIVATE-OWNER', str(caught.exception))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_bundle_rehearsal_refuses_git_scoped_scratch_location(self):
        from athenz.profile_bundle import create_bundle
        from athenz.recovery_drill import rehearse_profile_bundle
        store = ExperienceStore(self.home)
        store.close()
        bundle = create_bundle(self.home, confirmed=True)
        (self.scratch / '.git').mkdir()
        with self.assertRaisesRegex(RecoveryDrillError, 'Git checkout'):
            rehearse_profile_bundle(self.home, bundle['id'], confirmed=True,
                                    scratch_root=self.scratch)
        self.assertEqual(sorted(p.name for p in self.scratch.iterdir()), ['.git'])

    def test_bundle_rehearsal_missing_source_has_no_side_effects(self):
        from athenz.recovery_drill import rehearse_profile_bundle
        missing = self.base / 'unknown-profile'
        with self.assertRaisesRegex(RecoveryDrillError, 'Existing private profile'):
            rehearse_profile_bundle(missing, 'f' * 32, confirmed=True,
                                    scratch_root=self.scratch)
        self.assertFalse(missing.exists())
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_no_consent_means_no_private_backup_read(self):
        with patch('athenz.recovery_drill.verify_backup', side_effect=AssertionError('read')):
            with self.assertRaisesRegex(RecoveryDrillError, 'confirm'):
                rehearse_sqlite_backup(self.home, 'a' * 32)

    def test_recovery_rehearsal_disarms_and_erases_copy(self):
        ident = self._backup()
        original = (self.home/'identity.sqlite3').read_bytes()
        result = rehearse_sqlite_backup(self.home, ident, confirmed=True,
                                         scratch_root=self.scratch)
        self.assertTrue(result['rehearsal_passed'])
        self.assertTrue(result['model_routing_reset'])
        self.assertTrue(result['scheduler_disarmed'])
        self.assertTrue(result['running_checkpoints_paused'])
        self.assertTrue(result['temp_profile_deleted'])
        self.assertFalse(result['live_profile_replaced'])
        self.assertFalse(result['full_profile_recovery_validated'])
        self.assertFalse(result['independent_hardware_validation'])
        self.assertNotIn('synthetic do-not-print', json.dumps(result))
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertEqual((self.home/'identity.sqlite3').read_bytes(), original)

    def test_cli_outputs_only_sanitized_technical_status(self):
        ident = self._backup()
        output = io.StringIO()
        with redirect_stdout(output):
            main([ident, '--home', str(self.home), '--scratch', str(self.scratch), '--confirm'])
        payload = json.loads(output.getvalue())
        self.assertTrue(payload['rehearsal_passed'])
        self.assertNotIn(str(self.home), output.getvalue())
        self.assertNotIn(ident, output.getvalue())
        self.assertNotIn('synthetic do-not-print', output.getvalue())

    def test_invalid_id_before_read(self):
        with patch('athenz.recovery_drill.verify_backup', side_effect=AssertionError('called')):
            with self.assertRaisesRegex(RecoveryDrillError, 'identifier'):
                rehearse_sqlite_backup(self.home, '../archive', confirmed=True)

    def test_refuses_scratch_in_checkout_and_inside_private_home(self):
        ident = self._backup()
        gitdir = self.base/'git'
        gitdir.mkdir()
        (gitdir/'.git').mkdir()
        with self.assertRaisesRegex(RecoveryDrillError, 'Git checkout'):
            rehearse_sqlite_backup(self.home, ident, confirmed=True, scratch_root=gitdir)
        nested = self.home/'nested'
        nested.mkdir()
        with self.assertRaisesRegex(RecoveryDrillError, 'separate'):
            rehearse_sqlite_backup(self.home, ident, confirmed=True, scratch_root=nested)

    def test_capacity_check_before_creating_temporary_copy(self):
        ident = self._backup()
        disk = type('DiskUsage', (), {'free': MIN_FREE_MARGIN})()
        with patch('athenz.recovery_drill.shutil.disk_usage', return_value=disk):
            with self.assertRaisesRegex(RecoveryDrillError, 'Insufficient'):
                rehearse_sqlite_backup(self.home, ident, confirmed=True, scratch_root=self.scratch)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_snapshot_size_bound(self):
        ident = self._backup()
        with patch('athenz.recovery_drill.verify_backup', return_value={
            'valid': True, 'scope': 'sqlite-only', 'size': MAX_SNAPSHOT+1}):
            with self.assertRaisesRegex(RecoveryDrillError, 'size'):
                rehearse_sqlite_backup(self.home, ident, confirmed=True, scratch_root=self.scratch)

    def test_unexpected_restore_failure_cleans_scratch(self):
        ident = self._backup()
        with patch('athenz.recovery_drill.restore_to_new_profile',
                   side_effect=RuntimeError('synthetic interruption')):
            with self.assertRaisesRegex(RuntimeError, 'interruption'):
                rehearse_sqlite_backup(self.home, ident, confirmed=True,
                                        scratch_root=self.scratch)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_refuses_symlinked_scratch_parent(self):
        ident = self._backup()
        alias = self.base / 'alias'
        try:
            alias.symlink_to(self.scratch, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('Symlink creation is not permitted')
        with self.assertRaisesRegex(RecoveryDrillError, 'real existing'):
            rehearse_sqlite_backup(self.home, ident, confirmed=True,
                                    scratch_root=alias)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_unavailable_snapshot_does_not_create_destination(self):
        with self.assertRaises(Exception):
            rehearse_sqlite_backup(self.home, 'f' * 32, confirmed=True, scratch_root=self.scratch)
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertFalse(self.home.exists(), 'Missing backup must not initialize a profile')


if __name__ == '__main__':
    unittest.main()
