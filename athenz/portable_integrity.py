"""Offline ZIP integrity checks for unsigned portable builds (not authentication)."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import zipfile

MAX_ZIP = 2 * 1024**3
MAX_UNPACKED = 4 * 1024**3
MAX_ENTRIES = 20000
HEX = re.compile(r'[0-9a-fA-F]{64}\Z')
FORBIDDEN = set('<>:"\\|?*')
DEVICES = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)}


class PortableArchiveError(ValueError):
    """Invalid archive, layout, or owner-supplied checksum."""


def _safe_name(name: str) -> str:
    if (not name or name.startswith('/') or '\\' in name or
            any(ord(ch) < 32 for ch in name)):
        raise PortableArchiveError('Unsafe archive path')
    if name == 'AthenZ/':
        return 'athenz/'
    base = name[:-1] if name.endswith('/') else name
    parts = base.split('/')
    if (len(parts) < 2 or parts[0] != 'AthenZ' or
            any(not part or part in ('.', '..') or part.endswith((' ', '.')) or
                any(ch in FORBIDDEN for ch in part) or
                part.split('.')[0].upper() in DEVICES for part in parts)):
        raise PortableArchiveError('Path is invalid for Windows portable package')
    return base.casefold()


def verify_portable_zip(path: Path, expected_sha256: str) -> dict:
    """Validate exact ZIP bytes and contents without ever extracting or running it."""
    if not isinstance(expected_sha256, str) or not HEX.fullmatch(expected_sha256):
        raise PortableArchiveError('Supply a complete expected SHA-256 (64 hex characters)')
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise PortableArchiveError('ZIP must be a regular non-symlink file')
    if not 0 < path.stat().st_size <= MAX_ZIP:
        raise PortableArchiveError('ZIP size is outside supported limits')
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    measured = digest.hexdigest()
    if measured != expected_sha256.lower():
        raise PortableArchiveError('ZIP SHA-256 differs from the supplied expected digest')
    seen = set()
    size = 0
    exe_found = False
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if not 1 <= len(members) <= MAX_ENTRIES:
                raise PortableArchiveError('ZIP entry count is not supported')
            for info in members:
                normalized = _safe_name(info.filename)
                if normalized in seen:
                    raise PortableArchiveError('Duplicate or Windows case-colliding paths')
                seen.add(normalized)
                if info.flag_bits & 1:
                    raise PortableArchiveError('ZIP contains an encrypted entry')
                if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                    raise PortableArchiveError('ZIP uses unsupported compression')
                if stat.S_ISLNK((info.external_attr >> 16) & 0xffff):
                    raise PortableArchiveError('ZIP contains a symlink')
                if not info.is_dir():
                    size += info.file_size
                    if size > MAX_UNPACKED:
                        raise PortableArchiveError('ZIP expansion exceeds safety limit')
                    if info.file_size > 1000 * max(1, info.compress_size):
                        raise PortableArchiveError('Suspicious ZIP expansion ratio')
                    exe_found |= info.filename == 'AthenZ/AthenZ.exe'
            if not exe_found:
                raise PortableArchiveError('Portable AthenZ.exe is missing')
            if archive.testzip() is not None:
                raise PortableArchiveError('ZIP failed CRC integrity check')
    except (zipfile.BadZipFile, OSError, EOFError) as exc:
        raise PortableArchiveError('ZIP could not be read safely') from exc
    # Detect a mutable input changing between checksum and archive inspection.
    again = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            again.update(chunk)
    if again.hexdigest() != measured:
        raise PortableArchiveError('ZIP content changed during verification')
    return {'sha256': measured, 'entries': len(members),
            'expanded_bytes': size, 'hash_verified': True,
            'extracted': False, 'authenticity_verified': False}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description='Offline unsigned AthenZ ZIP verification (not code signing)')
    p.add_argument('zip_file', type=Path)
    p.add_argument('--sha256', required=True, help='Full expected digest from a trusted separate channel')
    args = p.parse_args(argv)
    print(json.dumps(verify_portable_zip(args.zip_file, args.sha256), indent=2))


if __name__ == '__main__':
    main()
