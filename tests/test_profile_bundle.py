"""Tests of selected private archive integrity and bounded scope using synthetic files."""
from pathlib import Path
import tempfile
import unittest

from athenz.backup import BackupError
from athenz.experience import ExperienceStore
from athenz.profile_bundle import (create_bundle, verify_bundle,
                                   inspect_bundle_scope, _secure_name)


class ProfileBundleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / 'private'
        store = ExperienceStore(self.home)
        store.propose('style', 'Synthetic original data', source='owner', approved=True)
        store.close()
        (self.home/'datasets').mkdir()
        (self.home/'datasets'/'synthetic.jsonl').write_bytes(b'DATA_ONLY\n')
        (self.home/'runs'/'r1'/'adapter').mkdir(parents=True)
        (self.home/'runs'/'r1'/'adapter'/'adapter_model.safetensors').write_bytes(b'synthetic weights')
        (self.home/'worktrees').mkdir()
        (self.home/'worktrees'/'untrusted.py').write_text('SHOULD_NOT_INCLUDE')
        (self.home/'backups').mkdir()
        (self.home/'backups'/'old-data').write_text('OLD_BACKUP')

    def test_bounded_unencrypted_bundle_verifies(self):
        with self.assertRaisesRegex(BackupError, 'confirm'):
            create_bundle(self.home)
        bundle = create_bundle(self.home, confirmed=True)
        self.assertFalse(bundle['encrypted'])
        checked = verify_bundle(self.home, bundle['id'])
        self.assertEqual(checked['files'], 3)
        import zipfile
        with zipfile.ZipFile(self.home/'bundles'/f"bundle-{bundle['id']}.zip") as zf:
            self.assertEqual(zf.read('datasets/synthetic.jsonl'), b'DATA_ONLY\n')
            self.assertNotIn('worktrees/untrusted.py', zf.namelist())
            self.assertNotIn('backups/old-data', zf.namelist())

    def test_malformed_signed_zip_manifest_fails_closed(self):
        import hashlib
        import json
        import zipfile
        b = create_bundle(self.home, confirmed=True)
        path = self.home / 'bundles' / f"bundle-{b['id']}.zip"
        sidecar = self.home / 'bundles' / f"bundle-{b['id']}.manifest.json"
        with zipfile.ZipFile(path) as zf:
            original = [(item.filename, zf.read(item)) for item in zf.infolist()]
        original_manifest = json.loads(dict(original)['manifest.json'])
        for manifest in (
                [],
                {**original_manifest, 'files': [
                    {**original_manifest['files'][0], 'path': None},
                    *original_manifest['files'][1:]]},
                {**original_manifest, 'files': [
                    {**original_manifest['files'][0], 'path': 123},
                    *original_manifest['files'][1:]]},
                {**original_manifest, 'files': [
                    {**original_manifest['files'][0], 'bytes': True},
                    *original_manifest['files'][1:]]},
        ):
            with self.subTest(malformed=str(manifest)[:50]):
                scratch = path.with_suffix('.tmp')
                with zipfile.ZipFile(scratch, 'w', compression=zipfile.ZIP_STORED) as zf:
                    for filename, contents in original:
                        zf.writestr(filename, (json.dumps(manifest).encode('utf-8')
                                              if filename == 'manifest.json'
                                              else contents))
                scratch.replace(path)
                data = path.read_bytes()
                marker = {'schema': 1, 'id': b['id'],
                          'sha256': hashlib.sha256(data).hexdigest(),
                          'bytes': len(data), 'encrypted': False}
                sidecar.write_text(json.dumps(marker))
                with self.assertRaises(BackupError):
                    verify_bundle(self.home, b['id'])

    def test_readonly_scope_inspection_reports_counts_not_private_names(self):
        import json
        report = inspect_bundle_scope(self.home)
        self.assertTrue(report['profile_found'])
        self.assertEqual(report['selected_artifact_count'], 2)
        self.assertTrue(report['sqlite_present'])
        self.assertTrue(report['plaintext_warning'])
        self.assertFalse(report['reads_file_contents'])
        self.assertFalse(report['creates_files'])
        self.assertNotIn('synthetic.jsonl', json.dumps(report))
        self.assertNotIn('untrusted.py', json.dumps(report))
        self.assertIn('release-acceptance.sqlite3', report['excludes'])

    def test_missing_profile_inspection_does_not_create_files(self):
        missing = self.root / 'never-created-private-profile'
        report = inspect_bundle_scope(missing)
        self.assertFalse(report['profile_found'])
        self.assertEqual(report['estimated_plaintext_total_bytes'], 0)
        self.assertFalse(missing.exists())
        import json
        from unittest.mock import patch
        from athenz.profile_bundle import main
        with patch('builtins.print') as display:
            main(['--home', str(missing), 'inspect'])
        result = json.loads(display.call_args.args[0])
        self.assertFalse(result['profile_found'])
        self.assertFalse(missing.exists())

    def test_scope_inspection_rejects_symlinked_selected_file(self):
        path = self.home / 'datasets' / 'outside-link'
        try:
            path.symlink_to(self.home / 'identity.sqlite3')
        except (OSError, NotImplementedError):
            self.skipTest('No symlink privilege on runner')
        with self.assertRaisesRegex(BackupError, 'Symlinked'):
            inspect_bundle_scope(self.home)

    def test_invalid_outer_bundle_sidecar_is_refused_without_private_output(self):
        import json
        b = create_bundle(self.home, confirmed=True)
        sidecar = self.home/'bundles'/f"bundle-{b['id']}.manifest.json"
        original = json.loads(sidecar.read_text())
        for corrupt in ([], 'PRIVATE-SECRET', None,
                        {**original, 'bytes': True},
                        {**original, 'sha256': 12},
                        {**original, 'schema': True}):
            with self.subTest(malformed=repr(corrupt)[:50]):
                sidecar.write_text(json.dumps(corrupt))
                with self.assertRaises(BackupError) as caught:
                    verify_bundle(self.home, b['id'])
                self.assertNotIn('PRIVATE-SECRET', str(caught.exception))
        sidecar.write_text(json.dumps(original))
        self.assertTrue(verify_bundle(self.home, b['id'])['valid'])

    def test_tamper_archive_detected(self):
        bundle = create_bundle(self.home, confirmed=True)
        path = self.home/'bundles'/f"bundle-{bundle['id']}.zip"
        path.write_bytes(path.read_bytes()[:-10] + b'changedzip')
        with self.assertRaisesRegex(BackupError, 'changed'):
            verify_bundle(self.home, bundle['id'])

    def test_symlinked_artifact_refused(self):
        try:
            (self.home/'datasets'/'link').symlink_to(self.home/'identity.sqlite3')
        except (OSError, NotImplementedError):
            self.skipTest('No symlink privilege on runner')
        with self.assertRaisesRegex(BackupError, 'Symlinked'):
            create_bundle(self.home, confirmed=True)

    def test_no_git_checkout_or_profile_extras(self):
        (self.root/'.git').mkdir()
        with self.assertRaisesRegex(BackupError, 'Git checkout'):
            create_bundle(self.home, confirmed=True)

    def test_unsafe_member_name_rejected(self):
        for name in ('/tmp/file', '../datasets/x', 'datasets/../key', 'datasets/CON.txt',
                     'datasets/x\\y', 'datasets/x:stream', 'runs//file', 'elsewhere/a'):
            with self.subTest(name=name):
                with self.assertRaises(BackupError):
                    _secure_name(name)

    def test_case_collisions_block_windows_unsafe_bundle(self):
        candidate = self.home/'datasets'/'SYNTHETIC.jsonl'
        if candidate.exists():
            self.skipTest('Case-insensitive Windows filesystem cannot represent both names')
        candidate.write_text('different')
        with self.assertRaisesRegex(BackupError, 'Case-colliding'):
            create_bundle(self.home, confirmed=True)


if __name__=='__main__':
    unittest.main()

# Extended end-to-end new-profile recovery tests.
class BundleRecoveryTests(ProfileBundleTests):
    def test_restores_selected_files_into_new_disarmed_profile(self):
        from athenz.profile_bundle import restore_bundle_new
        store = ExperienceStore(self.home)
        store.checkpoint('ollama_runtime', 'routing', {'active_tag': 'bad-old-choice'}, status='paused')
        store.checkpoint('old-job', 'run', {'scope': 'external'}, status='running')
        store.close()
        result = create_bundle(self.home, confirmed=True)
        restored = self.root/'isolated'
        with self.assertRaisesRegex(BackupError, 'confirm'):
            restore_bundle_new(self.home, result['id'], restored)
        report = restore_bundle_new(self.home, result['id'], restored, confirmed=True)
        self.assertEqual(report['files_restored'], 3)
        self.assertEqual((restored/'datasets'/'synthetic.jsonl').read_text(), 'DATA_ONLY\n')
        self.assertEqual((restored/'runs'/'r1'/'adapter'/'adapter_model.safetensors').read_bytes(), b'synthetic weights')
        self.assertFalse((restored/'worktrees').exists())
        recovered = ExperienceStore(restored)
        self.assertIsNone(recovered.get_checkpoint('ollama_runtime'))
        self.assertEqual(recovered.get_checkpoint('old-job')['status'], 'paused')
        recovered.close()
        original = ExperienceStore(self.home)
        self.assertIsNotNone(original.get_checkpoint('ollama_runtime'))
        original.close()

    def test_rejects_existing_target_without_changing_it(self):
        from athenz.profile_bundle import restore_bundle_new
        result = create_bundle(self.home, confirmed=True)
        target = self.root/'exists'
        target.mkdir()
        (target/'marker').write_text('DONOTCHANGE')
        with self.assertRaisesRegex(BackupError, 'must not exist'):
            restore_bundle_new(self.home, result['id'], target, confirmed=True)
        self.assertEqual((target/'marker').read_text(), 'DONOTCHANGE')

    def test_tampered_archive_not_restored(self):
        from athenz.profile_bundle import restore_bundle_new
        result = create_bundle(self.home, confirmed=True)
        archive = self.home/'bundles'/f"bundle-{result['id']}.zip"
        archive.write_bytes(archive.read_bytes()+b'changed')
        dest = self.root/'not-created'
        with self.assertRaises(BackupError):
            restore_bundle_new(self.home, result['id'], dest, confirmed=True)
        self.assertFalse(dest.exists())

class BundleBoundaries(ProfileBundleTests):
    def test_verifier_rejects_extra_unlisted_file_even_when_sidecar_rehashed(self):
        import hashlib
        import json
        import zipfile
        result = create_bundle(self.home, confirmed=True)
        archive = self.home/'bundles'/f"bundle-{result['id']}.zip"
        sidecar = self.home/'bundles'/f"bundle-{result['id']}.manifest.json"
        with zipfile.ZipFile(archive, mode='a', compression=zipfile.ZIP_STORED) as zf:
            zf.writestr('../UNSAFE', 'no')
        manifest = json.loads(sidecar.read_text())
        payload = archive.read_bytes()
        manifest['sha256'] = hashlib.sha256(payload).hexdigest()
        manifest['bytes'] = len(payload)
        sidecar.write_text(json.dumps(manifest))
        with self.assertRaises(BackupError):
            verify_bundle(self.home, result['id'])

    def test_verifier_rejects_unapproved_expansion_to_other_root(self):
        import hashlib
        import json
        import zipfile
        result = create_bundle(self.home, confirmed=True)
        archive = self.home/'bundles'/f"bundle-{result['id']}.zip"
        sidecar = self.home/'bundles'/f"bundle-{result['id']}.manifest.json"
        tmp = self.root/'other.zip'
        with zipfile.ZipFile(archive) as old, zipfile.ZipFile(tmp,'w',compression=zipfile.ZIP_STORED) as new:
            manifest = json.loads(old.read('manifest.json'))
            for info in old.infolist():
                if info.filename != 'manifest.json':
                    new.writestr(info.filename, old.read(info.filename))
            name='arbitrary/secrets'
            fake=b'synthetic not a private file'
            new.writestr(name, fake)
            manifest['files'].append({'path':name,'bytes':len(fake),'sha256':hashlib.sha256(fake).hexdigest()})
            new.writestr('manifest.json',json.dumps(manifest))
        archive.write_bytes(tmp.read_bytes())
        record=json.loads(sidecar.read_text());record['sha256']=hashlib.sha256(archive.read_bytes()).hexdigest();record['bytes']=archive.stat().st_size
        sidecar.write_text(json.dumps(record))
        with self.assertRaises(BackupError):
            verify_bundle(self.home,result['id'])
