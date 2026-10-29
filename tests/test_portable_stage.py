"""Synthetic offline Windows portable side-by-side stage/rollback boundaries."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from athenz.portable_integrity import PortableArchiveError
from athenz.portable_stage import stage_portable_zip, verify_staged_portable, main


class StageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.src = self.root/'build.zip'
        self.destination = self.root/'versions'
        self.destination.mkdir()
        self.sha = self.pack([('AthenZ/', b''), ('AthenZ/AthenZ.exe', b'fake binary'),
                              ('AthenZ/_internal/runtime.dat', b'data')])

    def pack(self, items):
        with zipfile.ZipFile(self.src, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for p, data in items:
                archive.writestr(p, data)
        return hashlib.sha256(self.src.read_bytes()).hexdigest()

    def stage(self, name='AthenZ-v060'):
        return stage_portable_zip(self.src, self.sha, self.destination, name=name, confirmed=True)

    def test_confirm_and_offline_stage_never_runs_or_mutates_private_profile(self):
        profile = self.root/'.athenz'
        profile.mkdir()
        (profile/'identity.sqlite3').write_bytes(b'synthetic private value')
        with self.assertRaisesRegex(PortableArchiveError, 'confirm'):
            stage_portable_zip(self.src, self.sha, self.destination, name='AthenZ-v060')
        with mock.patch('subprocess.run', side_effect=AssertionError('execution forbidden')), \
             mock.patch('subprocess.Popen', side_effect=AssertionError('execution forbidden')):
            result = self.stage()
        self.assertFalse(result['activated'])
        self.assertFalse(result['publisher_authenticated'])
        self.assertEqual((profile/'identity.sqlite3').read_bytes(), b'synthetic private value')
        path = Path(result['path'])
        self.assertEqual((path/'AthenZ/AthenZ.exe').read_bytes(), b'fake binary')
        self.assertFalse((path/'incoming.zip').exists())
        self.assertTrue(verify_staged_portable(path)['valid'])

    def test_old_stage_preserved_and_new_version_separate(self):
        old = self.stage('AthenZ-old')
        fresh = self.stage('AthenZ-new')
        self.assertNotEqual(old['path'], fresh['path'])
        self.assertTrue(verify_staged_portable(Path(old['path']))['valid'])
        with self.assertRaisesRegex(PortableArchiveError, 'already exists'):
            self.stage('AthenZ-old')
        self.assertTrue(verify_staged_portable(Path(fresh['path']))['valid'])

    def test_case_collision_is_refused_even_on_linux(self):
        self.stage('AthenZ-Beta')
        with self.assertRaisesRegex(PortableArchiveError, 'already exists'):
            self.stage('AthenZ-beta')

    def test_bad_sha_and_path_traversal_refused_without_final_directory(self):
        with self.assertRaisesRegex(PortableArchiveError, 'differs'):
            stage_portable_zip(self.src, '0'*64, self.destination, name='AthenZ-fail', confirmed=True)
        self.assertFalse((self.destination/'AthenZ-fail').exists())
        self.sha = self.pack([('AthenZ/AthenZ.exe', b'a'), ('AthenZ/../bad.exe', b'bad')])
        with self.assertRaises(PortableArchiveError):
            self.stage('AthenZ-traversal')
        self.assertFalse((self.destination/'AthenZ-traversal').exists())

    def test_tampering_and_extra_file_detected(self):
        stage = Path(self.stage()['path'])
        exe = stage/'AthenZ/AthenZ.exe'
        exe.write_bytes(b'evil payload')
        with self.assertRaisesRegex(PortableArchiveError, 'size has changed'):
            verify_staged_portable(stage)
        exe.write_bytes(b'fake binary')
        (stage/'AthenZ/unexpected.txt').write_text('bad')
        with self.assertRaisesRegex(PortableArchiveError, 'unexpected'):
            verify_staged_portable(stage)

    def test_same_size_tamper_and_extra_directory_detected(self):
        stage = Path(self.stage()['path'])
        (stage/'AthenZ/AthenZ.exe').write_bytes(b'FAKE BINARY')
        with self.assertRaisesRegex(PortableArchiveError, 'fingerprint'):
            verify_staged_portable(stage)
        (stage/'AthenZ/AthenZ.exe').write_bytes(b'fake binary')
        (stage/'AthenZ/extra-empty').mkdir()
        with self.assertRaisesRegex(PortableArchiveError, 'directory inventory'):
            verify_staged_portable(stage)

    def test_refuses_symlinked_destination_root_when_supported(self):
        link = self.root/'linked'
        try:
            link.symlink_to(self.destination, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest('OS disallows symlinks')
        with self.assertRaisesRegex(PortableArchiveError, 'Symlinked'):
            stage_portable_zip(self.src, self.sha, link, name='AthenZ-test', confirmed=True)

    def test_missing_manifest_and_stage_file_rejected(self):
        stage = Path(self.stage()['path'])
        (stage/'AthenZ/_internal/runtime.dat').unlink()
        with self.assertRaisesRegex(PortableArchiveError, 'missing'):
            verify_staged_portable(stage)
        (stage/'.athenz-stage.json').unlink()
        with self.assertRaisesRegex(PortableArchiveError, 'manifest'):
            verify_staged_portable(stage)

    def test_rejects_bad_destinations_and_untrusted_locations(self):
        for name in ['AthenZ-..', 'AthenZ-CON.', 'not-athenz', 'AthenZ-']:
            with self.subTest(name=name):
                with self.assertRaises(PortableArchiveError):
                    self.stage(name)
        private = self.root/'.athenz'/'binaries'
        private.mkdir(parents=True)
        with self.assertRaisesRegex(PortableArchiveError, 'private'):
            stage_portable_zip(self.src, self.sha, private, name='AthenZ-test', confirmed=True)
        risky = self.root/'repo'; risky.mkdir(); (risky/'.git').mkdir()
        with self.assertRaisesRegex(PortableArchiveError, 'Git'):
            stage_portable_zip(self.src, self.sha, risky, name='AthenZ-test', confirmed=True)

    def test_extraction_failure_never_replaces_prior_version(self):
        original = Path(self.stage('AthenZ-original')['path'])
        with mock.patch('athenz.portable_stage.verify_portable_zip', side_effect=PortableArchiveError('broken')):
            with self.assertRaisesRegex(PortableArchiveError, 'broken'):
                self.stage('AthenZ-new')
        self.assertTrue(verify_staged_portable(original)['valid'])
        self.assertFalse((self.destination/'AthenZ-new').exists())

    def test_two_version_upgrade_tamper_and_rollback_verification(self):
        # A realistic portable payload: dozens of files across nested
        # directories, including one large module, staged as two versions.
        def payload(version):
            items = [('AthenZ/', b''), ('AthenZ/AthenZ.exe', b'fake binary ' + version)]
            for i in range(40):
                items.append((f'AthenZ/_internal/pkg/mod{i:02d}.py',
                              f'# synthetic module {i} {version.decode()}\n'.encode()))
            for d in ('data', 'data/locale', 'assets/icons'):
                items.append((f'AthenZ/_internal/{d}/blob.bin', bytes(range(256)) * 8))
            big = b''.join(hashlib.sha256(f'synthetic-block-{i}'.encode()).digest()
                           for i in range(32768))
            items.append(('AthenZ/_internal/big.dat', big))
            return items
        old_sha = self.pack(payload(b'v1'))
        old = Path(stage_portable_zip(self.src, old_sha, self.destination,
                                      name='AthenZ-v1', confirmed=True)['path'])
        new_sha = self.pack(payload(b'v2'))
        new = Path(stage_portable_zip(self.src, new_sha, self.destination,
                                      name='AthenZ-v2', confirmed=True)['path'])
        verify_staged_portable(old)
        verify_staged_portable(new)
        # Upgrade turns out bad: a staged file in v2 is tampered with.
        (new / 'AthenZ' / '_internal' / 'pkg' / 'mod07.py').write_bytes(b'# tampered\n')
        with self.assertRaises(PortableArchiveError):
            verify_staged_portable(new)
        # Rollback target is untouched: the v1 stage still verifies exactly.
        verify_staged_portable(old)

    def test_cli_has_explicit_stage_and_verify_only(self):
        from athenz.portable_stage import STAGE_NAME
        self.assertTrue(STAGE_NAME.fullmatch('AthenZ-build123'))
        self.assertFalse(STAGE_NAME.fullmatch('../other'))


if __name__ == '__main__':
    unittest.main()
