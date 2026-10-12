"""Unsigned package integrity and traversal protections, synthetic ZIPs only."""
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile
from athenz.portable_integrity import PortableArchiveError, verify_portable_zip, _safe_name


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.path = self.root/'artifact.zip'

    def pack(self, entries):
        with zipfile.ZipFile(self.path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name, content in entries:
                z.writestr(name, content)
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_matching_checksum_and_no_extraction(self):
        sha = self.pack([('AthenZ/', b''), ('AthenZ/AthenZ.exe', b'mock'), ('AthenZ/_internal/lib.dat', b'data')])
        self.assertEqual(verify_portable_zip(self.path, sha)['entries'], 3)
        self.assertFalse(verify_portable_zip(self.path, sha)['authenticity_verified'])
        self.assertFalse((self.root/'AthenZ').exists())

    def test_digest_mismatch_and_malformed_digest(self):
        self.pack([('AthenZ/AthenZ.exe', b'a')])
        with self.assertRaisesRegex(PortableArchiveError, 'differs'):
            verify_portable_zip(self.path, '0'*64)
        with self.assertRaisesRegex(PortableArchiveError, 'expected'):
            verify_portable_zip(self.path, 'fake')

    def test_refuses_traversal_and_windows_unsafe_names(self):
        for name in ('AthenZ/../evil.exe', 'AthenZ/CON.txt',
                     'AthenZ/bad:stream', 'AthenZ/space. ', '/AthenZ/fake.exe'):
            with self.subTest(name=name):
                sha = self.pack([('AthenZ/AthenZ.exe', b'a'), (name, b'x')])
                with self.assertRaises(PortableArchiveError):
                    verify_portable_zip(self.path, sha)

    def test_backslash_rejected_independently_of_zip_writer_normalization(self):
        # Python's Windows zipfile normalizes native backslashes when writing.
        with self.assertRaises(PortableArchiveError):
            _safe_name('AthenZ/dir\\hack')

    def test_case_collision_and_missing_executable(self):
        sha = self.pack([('AthenZ/AthenZ.exe', b'a'), ('AthenZ/LIB', b'a'), ('AthenZ/lib', b'b')])
        with self.assertRaisesRegex(PortableArchiveError, 'colliding'):
            verify_portable_zip(self.path, sha)
        sha = self.pack([('AthenZ/README.txt', b'a')])
        with self.assertRaisesRegex(PortableArchiveError, 'missing'):
            verify_portable_zip(self.path, sha)

    def test_rejects_zip_symlink_and_zip_bomb(self):
        link = zipfile.ZipInfo('AthenZ/elsewhere')
        link.create_system = 3
        link.external_attr = (0o120777 << 16)
        with zipfile.ZipFile(self.path, 'w') as z:
            z.writestr('AthenZ/AthenZ.exe', b'fake')
            z.writestr(link, '/tmp/private')
        sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(PortableArchiveError, 'symlink'):
            verify_portable_zip(self.path, sha)
        sha = self.pack([('AthenZ/AthenZ.exe', b'fake'), ('AthenZ/bomb', b'0' * 1000000)])
        with self.assertRaisesRegex(PortableArchiveError, 'expansion'):
            verify_portable_zip(self.path, sha)


if __name__ == '__main__':
    unittest.main()
