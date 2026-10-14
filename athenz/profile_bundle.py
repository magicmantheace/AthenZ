"""Opt-in, local, plaintext archives of bounded private AthenZ profile assets.

This is a selective, consistent SQLite snapshot plus owner-file artifacts, NOT
cloud backup, end-to-end atomic multi-file snapshotting or an encrypted vault.
No shell tools, model calls, Git operations, or automatic restore are used.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import tempfile
import uuid
import zipfile

from .backup import (BackupError, _checksum, _write_new,
                     validated_new_destination, disarm_recovered_database)
from .experience import ExperienceStore
from .store import utc_now

# Explicit scope: never archive Git worktrees, Docker snapshots, old backups,
# imported source folders, Ollama daemon state, or arbitrary profile extras.
ROOTS = frozenset({'datasets', 'evaluations', 'reviews', 'runs', 'conversions', 'ollama-imports'})
MAX_FILES = 5000
MAX_SINGLE = 2 * 1024 ** 3
MAX_TOTAL = 16 * 1024 ** 3
ID = re.compile(r'[0-9a-f]{32}\Z')


def _secure_name(name: str) -> str:
    """Only portable relative paths in the six explicit artifact namespaces."""
    if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
        raise BackupError('Unsafe private archive path')
    posix = PurePosixPath(name)
    parts = name.split('/')
    if (posix.is_absolute() or '..' in parts or '' in parts or '.' in parts or
            any(p.endswith((' ', '.')) or ':' in p or any(ord(c) < 32 for c in p) for p in parts)):
        raise BackupError('Unsafe private archive path')
    if any((part.split('.')[0].casefold() in {'con', 'prn', 'aux', 'nul'} or
            re.fullmatch(r'(com|lpt)[1-9]', part.split('.')[0], re.I)) for part in parts):
        raise BackupError('Windows-reserved private archive path')
    if name != 'identity.sqlite3' and (not parts or parts[0] not in ROOTS or len(parts) < 2):
        raise BackupError('Archive file outside reviewed private asset scope')
    return name


def _directory(home: Path) -> Path:
    if any((p / '.git').exists() or (p / '.git').is_symlink() for p in (home, *home.parents)):
        raise BackupError('Private bundles cannot be saved under a Git checkout')
    root = home / 'bundles'
    if root.is_symlink():
        raise BackupError('Private bundle directory must not be a symlink')
    root.mkdir(mode=0o700, exist_ok=True)
    if root.resolve(strict=True) != root:
        raise BackupError('Unsafe private bundle directory')
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _locations(root: Path, identifier: str) -> tuple[Path, Path]:
    if not isinstance(identifier, str) or not ID.fullmatch(identifier):
        raise BackupError('Bundle identifier must be 32 lowercase hex characters')
    return root / f'bundle-{identifier}.zip', root / f'bundle-{identifier}.manifest.json'


def _collect(home: Path) -> list[tuple[str, Path, int]]:
    found = []
    seen = set()
    total = 0
    for folder_name in sorted(ROOTS):
        top = home / folder_name
        if top.is_symlink():
            raise BackupError('Symlinked private artifact root refused: ' + folder_name)
        if not top.exists():
            continue
        if not top.is_dir():
            raise BackupError('Private artifact root is not a directory: ' + folder_name)
        for parent, dirs, files in os.walk(top, followlinks=False):
            base = Path(parent)
            if base.is_symlink():
                raise BackupError('Symlinked private folder refused')
            for name in dirs:
                path = base / name
                if path.is_symlink():
                    raise BackupError('Symlinked private folder refused')
                _secure_name(path.relative_to(home).as_posix() + '/placeholder')
            for name in files:
                path = base / name
                if path.is_symlink():
                    raise BackupError('Symlinked private artifact refused')
                st = path.stat()
                if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                    raise BackupError('Only ordinary non-hard-linked private artifact files permitted')
                rel = _secure_name(path.relative_to(home).as_posix())
                key = rel.casefold()
                if key in seen:
                    raise BackupError('Case-colliding private filenames are not portable')
                seen.add(key)
                total += st.st_size
                if len(found) + 2 > MAX_FILES or st.st_size > MAX_SINGLE or total > MAX_TOTAL:
                    raise BackupError('Private profile exceeds bounded bundle limits')
                found.append((rel, path, st.st_size))
    return sorted(found)


def _add(zf: zipfile.ZipFile, name: str, source: Path, known_size: int) -> dict:
    sha = hashlib.sha256()
    length = 0
    if source.is_symlink() or not source.is_file():
        raise BackupError('Source file changed before bundle copy')
    with source.open('rb') as reader, zf.open(name, 'w', force_zip64=True) as writer:
        while True:
            data = reader.read(1024 * 1024)
            if not data:
                break
            length += len(data)
            if length > known_size or length > MAX_SINGLE:
                raise BackupError('Source file changed size during bundle copy')
            writer.write(data)
            sha.update(data)
    if length != known_size or _checksum(source) != (sha.hexdigest(), length):
        raise BackupError('Source file changed during bundle copy')
    return {'path': name, 'sha256': sha.hexdigest(), 'bytes': length}


def inspect_bundle_scope(home: Path | None = None) -> dict:
    """Read-only plaintext backup preflight; zero private bytes returned."""
    if home is None:
        home = Path(os.environ.get('ATHENZ_HOME', str(Path.home() / '.athenz')))
    candidate = Path(home).expanduser()
    if candidate.is_symlink():
        raise BackupError('Private profile root must not be a symlink')
    root = candidate.resolve()
    if any((parent / '.git').exists() or (parent / '.git').is_symlink()
           for parent in (root, *root.parents)):
        raise BackupError('Private bundles cannot be saved under a Git checkout')
    report = {'schema': 1, 'profile_found': False, 'selected_artifact_count': 0,
              'selected_artifact_bytes': 0, 'sqlite_present': False,
              'sqlite_bytes_observed': 0, 'estimated_plaintext_total_bytes': 0,
              'scope': 'sqlite-plus-selected-private-artifacts',
              'excludes': ['worktrees', 'snapshots', 'backups', 'bundles',
                           'ollama-installed-models', 'release-acceptance.sqlite3'],
              'encrypted': False, 'plaintext_warning': True,
              'reads_file_contents': False, 'creates_files': False}
    if not root.exists():
        return report
    if not root.is_dir():
        raise BackupError('Private profile root is not a directory')
    if os.name != 'nt' and root.stat().st_mode & 0o077:
        raise BackupError('Private profile must not be accessible to group or other users')
    chosen = _collect(root)
    db = root / 'identity.sqlite3'
    if db.is_symlink() or (db.exists() and not db.is_file()):
        raise BackupError('Unsafe private identity database')
    size = 0
    present = db.is_file()
    if present:
        st = db.stat()
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            raise BackupError('Unsafe private identity database')
        size = st.st_size
    artifacts = sum(row[2] for row in chosen)
    if size > MAX_SINGLE or size + artifacts > MAX_TOTAL:
        raise BackupError('Private profile exceeds bounded bundle limits')
    return {**report, 'profile_found': True,
            'selected_artifact_count': len(chosen),
            'selected_artifact_bytes': artifacts,
            'sqlite_present': present,
            'sqlite_bytes_observed': size,
            'estimated_plaintext_total_bytes': size + artifacts}


def create_bundle(home: Path | None = None, *, confirmed: bool = False) -> dict:
    """Snapshot SQLite and explicitly allowed artifacts to a private ZIP (plaintext)."""
    if not confirmed:
        raise BackupError('Explicit --confirm required: bundle contains UNENCRYPTED private information')
    try:
        store = ExperienceStore(home)
    except ValueError as exc:
        # Preserve the bundle API's BackupError contract when the shared
        # private-profile guard refuses a Git checkout.
        if 'Git checkout' in str(exc):
            raise BackupError('Private bundles cannot be saved under a Git checkout') from exc
        raise
    try:
        profile = store.home.expanduser().resolve(strict=True)
        root = _directory(profile)
        files = _collect(profile)
        identifier = uuid.uuid4().hex
        data, sidecar = _locations(root, identifier)
        with tempfile.TemporaryDirectory(dir=root, prefix='snapshot-') as scratch:
            sql = Path(scratch) / 'identity.sqlite3'
            with closing(sqlite3.connect(sql)) as db:
                store.db.backup(db, pages=256, sleep=0.1)
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise BackupError('Private SQLite snapshot failed integrity check')
            sqlite_size = sql.stat().st_size
            if sqlite_size > MAX_SINGLE or sqlite_size + sum(f[2] for f in files) > MAX_TOTAL:
                raise BackupError('SQLite snapshot exceeds bounded bundle limits')
            fd = os.open(data, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, 'O_NOFOLLOW', 0), 0o600)
            try:
                with os.fdopen(fd, 'wb') as target:
                    with zipfile.ZipFile(target, mode='w', compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
                        metadata = [_add(zf, 'identity.sqlite3', sql, sqlite_size)]
                        for rel, path, size in files:
                            metadata.append(_add(zf, rel, path, size))
                        manifest = {'schema': 1, 'type': 'private-profile-selected-files',
                                    'id': identifier, 'created_at': utc_now(), 'encrypted': False,
                                    'files': metadata, 'excludes': ['worktrees', 'snapshots',
                                                                     'backups', 'bundles', 'ollama-installed-models']}
                        zf.writestr('manifest.json', json.dumps(manifest, sort_keys=True, separators=(',', ':')))
                    target.flush()
                    os.fsync(target.fileno())
                sha, size = _checksum(data)
                _write_new(sidecar, (json.dumps({'schema': 1, 'id': identifier, 'sha256': sha,
                                                  'bytes': size, 'encrypted': False}, sort_keys=True) + '\n').encode('utf-8'))
            except BaseException:
                data.unlink(missing_ok=True)
                sidecar.unlink(missing_ok=True)
                raise
        return {'id': identifier, 'sha256': sha, 'bytes': size,
                'files': len(metadata), 'encrypted': False,
                'scope': 'sqlite-plus-selected-private-artifacts'}
    finally:
        store.close()


def verify_bundle(home: Path | None, identifier: str) -> dict:
    """Verify stored ZIP SHA, individual files, schema and SQLite integrity."""
    store = ExperienceStore(home)
    try:
        root = _directory(store.home.expanduser().resolve(strict=True))
        data, sidecar = _locations(root, identifier)
        if any(path.is_symlink() or not path.is_file() for path in (data, sidecar)):
            raise BackupError('Missing or symlinked profile bundle files')
        try:
            outer = json.loads(sidecar.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError) as exc:
            raise BackupError('Invalid private profile bundle manifest') from exc
        sha, size = _checksum(data)
        if (not isinstance(outer, dict) or
                type(outer.get('schema')) is not int or outer['schema'] != 1 or
                outer.get('id') != identifier or outer.get('encrypted') is not False or
                type(outer.get('bytes')) is not int or outer['bytes'] <= 0 or
                not isinstance(outer.get('sha256'), str) or
                not re.fullmatch(r'[a-f0-9]{64}', outer['sha256']) or
                outer['sha256'] != sha or outer['bytes'] != size):
            raise BackupError('Private profile bundle changed since it was created')
        try:
            with zipfile.ZipFile(data, mode='r') as zf:
                info = zf.infolist()
                if not info or len(info) > MAX_FILES + 1 or any(x.compress_type != zipfile.ZIP_STORED for x in info):
                    raise BackupError('Unsupported or oversized bundle archive')
                if [i.filename for i in info].count('manifest.json') != 1:
                    raise BackupError('Bundle manifest missing or duplicated')
                manifest_info = zf.getinfo('manifest.json')
                if manifest_info.file_size > 2 * 1024 * 1024:
                    raise BackupError('Bundle manifest too large')
                manifest = json.loads(zf.read('manifest.json'))
                if (not isinstance(manifest, dict) or
                        manifest.get('schema') != 1 or manifest.get('type') != 'private-profile-selected-files'
                        or manifest.get('id') != identifier or manifest.get('encrypted') is not False
                        or not isinstance(manifest.get('files'), list)):
                    raise BackupError('Malformed internal bundle manifest')
                rows = manifest['files']
                if any(not isinstance(row, dict) or
                       not isinstance(row.get('path'), str) or
                       not isinstance(row.get('sha256'), str) for row in rows):
                    raise BackupError('Malformed archive member metadata')
                paths = [row['path'] for row in rows]
                if (len(rows) != len(info) - 1 or
                        set(paths) != set(i.filename for i in info if i.filename != 'manifest.json') or
                        len(set(p.casefold() for p in paths)) != len(paths) or
                        'identity.sqlite3' not in paths):
                    raise BackupError('Bundle file list changed or collides')
                total = 0
                with tempfile.TemporaryDirectory(prefix='verify-', dir=root) as scratch:
                    db_path = Path(scratch) / 'identity.sqlite3'
                    for row in rows:
                        name = _secure_name(row['path'])
                        i = zf.getinfo(name)
                        size_expected = row.get('bytes')
                        if (type(size_expected) is not int or size_expected < 0 or size_expected > MAX_SINGLE
                                or i.file_size != size_expected or i.is_dir() or
                                ((i.external_attr >> 16) & 0o170000) == stat.S_IFLNK):
                            raise BackupError('Bundle entry is unsafe or oversized')
                        total += size_expected
                        if total > MAX_TOTAL:
                            raise BackupError('Bundle extraction budget exceeded')
                        h = hashlib.sha256()
                        with zf.open(i) as source:
                            sink = db_path.open('wb') if name == 'identity.sqlite3' else None
                            try:
                                for block in iter(lambda: source.read(1024 * 1024), b''):
                                    h.update(block)
                                    if sink is not None:
                                        sink.write(block)
                            finally:
                                if sink:
                                    sink.close()
                        if h.hexdigest() != row.get('sha256'):
                            raise BackupError('Private archive file differs from its fingerprint')
                    db_uri = db_path.resolve(strict=True).as_uri() + '?mode=ro&immutable=1'
                    with closing(sqlite3.connect(db_uri, uri=True)) as db:
                        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                            raise BackupError('Bundle SQLite failed integrity check')
                        version = db.execute('PRAGMA user_version').fetchone()[0]
                        if not 1 <= version <= 6:
                            raise BackupError('Bundle SQLite schema is unsupported')
        except (zipfile.BadZipFile, KeyError, TypeError, ValueError,
                AttributeError, UnicodeError, OverflowError, sqlite3.DatabaseError) as exc:
            raise BackupError('Invalid or unreadable private profile archive') from exc
        return {'id': identifier, 'valid': True, 'sha256': sha, 'bytes': size,
                'files': len(paths), 'encrypted': False}
    finally:
        store.close()



def list_bundles(home: Path | None = None) -> list[str]:
    """List bounded private manifests only; never read owner content or source data."""
    store = ExperienceStore(home)
    try:
        root = _directory(store.home.expanduser().resolve(strict=True))
        rows = []
        for path in root.iterdir():
            match = re.fullmatch(r'bundle-([a-f0-9]{32})\.manifest\.json', path.name)
            if match and path.is_file() and not path.is_symlink():
                rows.append((path.stat().st_mtime_ns, match[1]))
        return [id for _, id in sorted(rows, reverse=True)[:100]]
    finally:
        store.close()


def restore_bundle_new(home: Path | None, identifier: str, destination: Path, *,
                       confirmed: bool = False) -> dict:
    """Extract a VERIFIED, bounded bundle into a NEW offline profile only.

    Never replaces a live profile or resumes old authority. Even after
    verification, every extracted member is rehashed (archive may have moved).
    """
    if not confirmed:
        raise BackupError('Explicit --confirm required before restoring plaintext private files')
    reviewed = verify_bundle(home, identifier)
    store = ExperienceStore(home)
    try:
        source_home = store.home.expanduser().resolve(strict=True)
        archive, _ = _locations(_directory(source_home), identifier)
    finally:
        store.close()
    dest = validated_new_destination(source_home, destination)
    os.mkdir(dest, 0o700)
    made_files: list[Path] = []
    made_dirs: list[Path] = []
    try:
        with zipfile.ZipFile(archive, 'r') as zf:
            info = zf.getinfo('manifest.json')
            if info.file_size > 2 * 1024 * 1024:
                raise BackupError('Bundle manifest too large')
            manifest = json.loads(zf.read('manifest.json'))
            if manifest.get('id') != identifier or manifest.get('schema') != 1:
                raise BackupError('Bundle identity differs from verified manifest')
            for entry in manifest['files']:
                rel = _secure_name(entry['path'])
                zipinfo = zf.getinfo(rel)
                if (zipinfo.compress_type != zipfile.ZIP_STORED or
                        zipinfo.file_size != entry['bytes'] or zipinfo.file_size > MAX_SINGLE):
                    raise BackupError('Archive member changed during recovery')
                path = dest.joinpath(*rel.split('/'))
                missing = []
                folder = path.parent
                while folder != dest and not folder.exists():
                    missing.append(folder)
                    folder = folder.parent
                if folder.is_symlink() or not folder.is_dir():
                    raise BackupError('Recovery directory structure has changed')
                for new_dir in reversed(missing):
                    os.mkdir(new_dir, 0o700)
                    made_dirs.append(new_dir)
                sha, size = hashlib.sha256(), 0
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                             getattr(os, 'O_NOFOLLOW', 0), 0o600)
                made_files.append(path)
                with os.fdopen(fd, 'wb') as output, zf.open(zipinfo, 'r') as source:
                    while True:
                        block = source.read(1024 * 1024)
                        if not block:
                            break
                        size += len(block)
                        if size > entry['bytes']:
                            raise BackupError('Archive member is oversized')
                        sha.update(block)
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
                if sha.hexdigest() != entry['sha256'] or size != entry['bytes']:
                    raise BackupError('Archive member changed during recovery')
        # Protect against archive updates after the initial verified read.
        archive_sha, archive_size = _checksum(archive)
        if (archive_sha, archive_size) != (reviewed['sha256'], reviewed['bytes']):
            raise BackupError('Bundle archive changed during restore')
        disarm_recovered_database(dest / 'identity.sqlite3')
        recovered_sha, _ = _checksum(dest / 'identity.sqlite3')
        record = {'schema': 1, 'source_bundle_id': identifier,
                  'source_bundle_sha256': reviewed['sha256'],
                  'restored_db_sha256': recovered_sha,
                  'files_restored': len(made_files),
                  'worktrees_restored': False,
                  'scheduler_disarmed': True, 'model_routing_reset': True,
                  'automatic_activation': False}
        path = dest / 'recovery.json'
        _write_new(path, (json.dumps(record, sort_keys=True) + '\n').encode('utf-8'))
        made_files.append(path)
        return {'path': str(dest), **record}
    except BaseException:
        # Delete only files/dirs successfully created by this invocation;
        # never follow links or recursively purge a user's existing tree.
        for file in reversed(made_files):
            if file.exists() or file.is_symlink():
                file.unlink()
        for directory in reversed(made_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            dest.rmdir()
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> None:
    import argparse
    parser = argparse.ArgumentParser(description='Local plaintext AthenZ profile bundles; no cloud, no overwrite')
    parser.add_argument('--home', type=Path, default=None)
    subs = parser.add_subparsers(dest='command', required=True)
    x = subs.add_parser('create'); x.add_argument('--confirm', action='store_true')
    subs.add_parser('inspect')
    subs.add_parser('list')
    x = subs.add_parser('verify'); x.add_argument('id')
    x = subs.add_parser('restore-new'); x.add_argument('id')
    x.add_argument('--destination', type=Path, required=True)
    x.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'create':
        result = create_bundle(args.home, confirmed=args.confirm)
    elif args.command == 'inspect':
        result = inspect_bundle_scope(args.home)
    elif args.command == 'verify':
        result = verify_bundle(args.home, args.id)
    elif args.command == 'list':
        result = {'ids': list_bundles(args.home)}
    else:
        result = restore_bundle_new(args.home, args.id, args.destination, confirmed=args.confirm)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
