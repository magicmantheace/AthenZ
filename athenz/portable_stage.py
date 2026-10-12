"""Owner-invoked, offline side-by-side staging of an unsigned Windows ZIP.

Never upgrades in place, changes a current profile, launches code, or installs
anything in the OS. A staged build is NOT publisher-authenticated or trusted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from .portable_integrity import (MAX_ZIP, PortableArchiveError, _safe_name,
                                 verify_portable_zip)

CHUNK = 1024 * 1024
STAGE_NAME = re.compile(r'AthenZ-[A-Za-z0-9][A-Za-z0-9._-]{0,55}\Z')
STAGE_SCHEMA = 1
MARKER = '.athenz-stage.json'


def _digest_stream(stream) -> tuple[str, int]:
    value = hashlib.sha256()
    total = 0
    for data in iter(lambda: stream.read(CHUNK), b''):
        total += len(data)
        value.update(data)
    return value.hexdigest(), total


def _destination(parent: Path, name: str) -> Path:
    """Require trusted existing destination outside user data or a Git checkout."""
    if not STAGE_NAME.fullmatch(name) or name.endswith(('.', ' ')):
        raise PortableArchiveError('Specify an AthenZ- prefixed, Windows-safe stage name')
    parent = Path(parent).expanduser().absolute()
    if '..' in parent.parts:
        raise PortableArchiveError('Parent must not contain relative traversal')
    if not parent.is_dir():
        raise PortableArchiveError('Destination parent must already exist')
    for ancestor in (parent, *parent.parents):
        if ancestor.is_symlink():
            raise PortableArchiveError('Symlinked destination ancestors are not allowed')
        if (ancestor / '.git').exists() or (ancestor / '.git').is_symlink():
            raise PortableArchiveError('Do not stage a portable build inside a Git repository')
    if any(p.lower() == '.athenz' for p in parent.parts):
        raise PortableArchiveError('Do not stage a portable build inside a private AthenZ profile')
    # Case-insensitive collision rejection even on POSIX test runners.
    if any(x.name.casefold() == name.casefold() for x in parent.iterdir()):
        raise PortableArchiveError('A stage of this name already exists; never overwrite it')
    return parent / name


def _write_json_new(path: Path, obj: dict) -> None:
    payload = (json.dumps(obj, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    with path.open('xb') as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def stage_portable_zip(zip_path: Path, expected_sha256: str, parent: Path, *,
                       name: str, confirmed: bool = False) -> dict:
    """Snapshot, verify and unpack ZIP into a new named version folder only.

    A caller-owned destination parent is assumed: this is not a security boundary
    against another hostile process concurrently mutating that parent.
    """
    if not confirmed:
        raise PortableArchiveError('Explicit --confirm is required before writing a staging directory')
    destination = _destination(parent, name)
    source = Path(zip_path)
    if source.is_symlink() or not source.is_file():
        raise PortableArchiveError('Select a real non-symlink portable ZIP')
    if not 0 < source.stat().st_size <= MAX_ZIP:
        raise PortableArchiveError('Input portable ZIP size is outside supported limits')
    with tempfile.TemporaryDirectory(prefix='.athenz-staging-', dir=destination.parent) as workspace:
        tmp = Path(workspace)
        frozen = tmp / 'incoming.zip'
        # Verify the copied, private bytes, not a source path that might change
        # between checksum validation and extraction.
        with source.open('rb') as reader, frozen.open('xb') as writer:
            for part in iter(lambda: reader.read(CHUNK), b''):
                writer.write(part)
                if writer.tell() > MAX_ZIP:
                    raise PortableArchiveError('ZIP changed or exceeded the input size limit')
        verified = verify_portable_zip(frozen, expected_sha256)
        # ZIP names were fully checked above; never use ZipFile.extractall.
        extracted = tmp / 'AthenZ'
        extracted.mkdir(mode=0o700)
        records = []
        included_dirs = {'AthenZ'}
        with zipfile.ZipFile(frozen) as archive:
            for info in archive.infolist():
                _safe_name(info.filename)
                pieces = info.filename.rstrip('/').split('/')[1:]
                target = extracted.joinpath(*pieces) if pieces else extracted
                for i in range(1, len(pieces) + (1 if info.is_dir() else 0)):
                    if i <= len(pieces) - (0 if info.is_dir() else 1):
                        included_dirs.add('/'.join(('AthenZ', *pieces[:i])))
                if info.is_dir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                # Already validated size/ratio in frozen archive; stream bytes
                # with an additional per-file bound and reject duplicates.
                digest = hashlib.sha256()
                length = 0
                with archive.open(info, 'r') as reader, target.open('xb') as writer:
                    for part in iter(lambda: reader.read(CHUNK), b''):
                        length += len(part)
                        if length > info.file_size:
                            raise PortableArchiveError('ZIP member grew during extraction')
                        writer.write(part)
                        digest.update(part)
                if length != info.file_size:
                    raise PortableArchiveError('ZIP member size changed during extraction')
                records.append({'path': info.filename, 'bytes': length, 'sha256': digest.hexdigest()})
        frozen.unlink()
        manifest = {'schema': STAGE_SCHEMA, 'type': 'unsigned-portable-staging',
                    'zip_sha256': verified['sha256'], 'files': sorted(records, key=lambda r: r['path']),
                    'directories': sorted(included_dirs),
                    'automatically_activated': False, 'publisher_authenticated': False}
        _write_json_new(tmp / MARKER, manifest)
        # Atomic directory rename makes a fully assembled version visible at once;
        # existing-name checks refuse normal collisions. Trusted private parent
        # is required, as rename is NOT atomic no-replace on all POSIX systems.
        if destination.exists() or destination.is_symlink():
            raise PortableArchiveError('Stage destination appeared during preparation')
        os.rename(tmp, destination)
    return {'path': str(destination), 'zip_sha256': verified['sha256'],
            'files': len(records), 'staged': True, 'activated': False,
            'publisher_authenticated': False}


def verify_staged_portable(directory: Path) -> dict:
    """Fail closed on missing/extra/altered contents and executable symlinks."""
    base = Path(directory)
    if base.is_symlink() or not base.is_dir() or (base / MARKER).is_symlink():
        raise PortableArchiveError('Stage directory or integrity marker is unsafe')
    for ancestor in (base, *base.parents):
        if ancestor.is_symlink():
            raise PortableArchiveError('Stage path is symlinked')
    try:
        raw = (base / MARKER).read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            raise PortableArchiveError('Stage manifest is oversized')
        manifest = json.loads(raw)
    except (OSError, ValueError, TypeError) as exc:
        raise PortableArchiveError('Stage manifest is absent or invalid') from exc
    if not (isinstance(manifest, dict) and manifest.get('schema') == STAGE_SCHEMA
            and manifest.get('type') == 'unsigned-portable-staging'
            and manifest.get('publisher_authenticated') is False
            and manifest.get('automatically_activated') is False
            and isinstance(manifest.get('files'), list)
            and re.fullmatch(r'[a-f0-9]{64}', str(manifest.get('zip_sha256', '')))):
        raise PortableArchiveError('Unrecognized staged-portable manifest')
    expected = {}
    for row in manifest['files']:
        if not isinstance(row, dict) or not isinstance(row.get('path'), str):
            raise PortableArchiveError('Stage file metadata is invalid')
        path = row['path']
        if path.endswith('/') or not path.startswith('AthenZ/'):
            raise PortableArchiveError('Stage manifest has an unsafe file path')
        _safe_name(path)
        key = path.casefold()
        if key in expected or not isinstance(row.get('bytes'), int) or row['bytes'] < 0 or not re.fullmatch(r'[a-f0-9]{64}', str(row.get('sha256', ''))):
            raise PortableArchiveError('Duplicate or invalid stage manifest entry')
        expected[key] = row
    if len(expected) > 20000 or 'athenz/athenz.exe' not in expected:
        raise PortableArchiveError('Staged program files are incomplete')
    allowed_dirs = manifest.get('directories')
    if not isinstance(allowed_dirs, list) or len(allowed_dirs) > 20000:
        raise PortableArchiveError('Unrecognized staged directory inventory')
    directory_names = set()
    for folder, dirs, files in os.walk(base, followlinks=False):
        for part in dirs:
            rel = (Path(folder)/part).relative_to(base).as_posix()
            _safe_name(rel + '/')
            directory_names.add(rel)
    if len(directory_names) != len(allowed_dirs) or directory_names != set(allowed_dirs):
        raise PortableArchiveError('Staged directory inventory changed')
    actual = set()
    for folder, dirs, files in os.walk(base, followlinks=False):
        for part in dirs:
            target = Path(folder) / part
            if target.is_symlink():
                raise PortableArchiveError('Staged directory contains a symlink')
        for part in files:
            target = Path(folder) / part
            if target.is_symlink() or not target.is_file() or not stat.S_ISREG(target.stat().st_mode):
                raise PortableArchiveError('Stage contains a non-regular file')
            relative = target.relative_to(base).as_posix()
            if relative == MARKER:
                continue
            _safe_name(relative)
            key = relative.casefold()
            if key not in expected or key in actual:
                raise PortableArchiveError('Stage has unexpected or duplicate files')
            record = expected[key]
            if target.stat().st_size != record['bytes']:
                raise PortableArchiveError('Staged file size has changed')
            with target.open('rb') as handle:
                sha, count = _digest_stream(handle)
            if sha != record['sha256'] or count != record['bytes']:
                raise PortableArchiveError('Staged file fingerprint has changed')
            actual.add(key)
    if actual != set(expected):
        raise PortableArchiveError('Staged files are missing')
    return {'staged': True, 'valid': True, 'files': len(actual),
            'zip_sha256': manifest['zip_sha256'], 'activated': False,
            'publisher_authenticated': False}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description='Offline side-by-side staging for an unsigned AthenZ portable ZIP')
    sub = p.add_subparsers(dest='command', required=True)
    x = sub.add_parser('stage', help='Copy and verify a ZIP into a fresh version directory')
    x.add_argument('zip_file', type=Path)
    x.add_argument('destination_parent', type=Path)
    x.add_argument('--sha256', required=True, help='Expected full digest obtained via a trusted source')
    x.add_argument('--name', required=True, help='Unused directory name starting AthenZ-')
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('verify', help='Rehash a staged portable directory without running it')
    x.add_argument('directory', type=Path)
    args = p.parse_args(argv)
    if args.command == 'stage':
        result = stage_portable_zip(args.zip_file, args.sha256, args.destination_parent,
                                    name=args.name, confirmed=args.confirm)
    else:
        result = verify_staged_portable(args.directory)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
