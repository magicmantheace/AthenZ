"""Explicit, local-only consistent SQLite snapshots of the private AthenZ profile.

Backups contain *plaintext private information*. This module never uploads,
archives unrelated directories, auto-restores, or executes commands. Model
adapters, datasets, reviews and other files are not part of SQLite snapshots.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import shutil
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import uuid

from .experience import ExperienceStore
from .store import utc_now

ID = re.compile(r'[a-f0-9]{32}\Z')


class BackupError(ValueError):
    pass


def _private_backup_root(store: ExperienceStore) -> Path:
    home = store.home.expanduser().resolve(strict=True)
    if any((p / '.git').exists() or (p / '.git').is_symlink()
           for p in (home, *home.parents)):
        raise BackupError('Private backups cannot be saved under a Git checkout')
    folder = home / 'backups'
    if folder.is_symlink():
        raise BackupError('Backup destination must not be a symlink')
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.resolve(strict=True) != folder:
        raise BackupError('Unsafe backup folder')
    try:
        folder.chmod(0o700)
    except OSError:
        pass
    return folder


def _paths(root: Path, identifier: str) -> tuple[Path, Path]:
    if not isinstance(identifier, str) or not ID.fullmatch(identifier):
        raise BackupError('Backup ID must be 32 lowercase hex characters')
    name = 'profile-' + identifier
    return root / (name + '.sqlite3'), root / (name + '.manifest.json')


def _write_new(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, 'wb') as writer:
            writer.write(payload)
            writer.flush()
            os.fsync(writer.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _checksum(path: Path) -> tuple[str, int]:
    h, size = hashlib.sha256(), 0
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            size += len(block)
            h.update(block)
    return h.hexdigest(), size


def create_backup(home: Path | None = None, *, confirmed: bool = False) -> dict:
    """Owner-confirmed consistent SQLite backup; never moves/edits live DB."""
    if not confirmed:
        raise BackupError('Explicit --confirm required; backup contains plaintext private information')
    store = ExperienceStore(home)
    try:
        root = _private_backup_root(store)
        uid = uuid.uuid4().hex
        data, meta = _paths(root, uid)
        # Fail if either destination is already occupied; names are random.
        if any(p.exists() or p.is_symlink() for p in (data, meta)):
            raise BackupError('Backup identifier unexpectedly already exists')
        # O_EXCL forbids overwrite; use the source connection's consistent
        # SQLite backup API (a file copy would miss active WAL transactions).
        fd = os.open(data, os.O_RDWR | os.O_CREAT | os.O_EXCL |
                     getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        try:
            with closing(sqlite3.connect(data)) as destination:
                store.db.backup(destination, pages=256, sleep=0.1)
                if destination.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise BackupError('New SQLite snapshot failed integrity check')
                schema = int(destination.execute('PRAGMA user_version').fetchone()[0])
            digest, size = _checksum(data)
            manifest = {'schema': 1, 'type': 'private-sqlite-only',
                        'id': uid, 'created_at': utc_now(), 'sha256': digest,
                        'size': size, 'sqlite_schema': schema,
                        'encrypted': False, 'restore_authorized': False}
            _write_new(meta, (json.dumps(manifest, sort_keys=True) + '\n').encode('utf-8'))
        except BaseException:
            data.unlink(missing_ok=True)
            meta.unlink(missing_ok=True)
            raise
        return {'id': uid, 'sha256': digest, 'size': size,
                'scope': 'sqlite-only', 'encrypted': False}
    finally:
        store.close()


def verify_backup(home: Path | None, identifier: str) -> dict:
    """Verify snapshot bytes and SQLite consistency. Does not restore it."""
    store = ExperienceStore(home)
    try:
        data, meta = _paths(_private_backup_root(store), identifier)
        if any(p.is_symlink() or not p.is_file() for p in (data, meta)):
            raise BackupError('Backup data or manifest missing or symlinked')
        try:
            record = json.loads(meta.read_text('utf-8'))
        except (OSError, UnicodeError, ValueError) as exc:
            raise BackupError('Invalid private backup manifest') from exc
        if (not isinstance(record, dict) or
                record.get('id') != identifier or
                type(record.get('schema')) is not int or record['schema'] != 1 or
                record.get('type') != 'private-sqlite-only' or
                record.get('encrypted') is not False or
                record.get('restore_authorized') is not False or
                type(record.get('size')) is not int or record['size'] <= 0 or
                type(record.get('sqlite_schema')) is not int or
                not 1 <= record['sqlite_schema'] <= 6 or
                not isinstance(record.get('sha256'), str) or
                not re.fullmatch(r'[a-f0-9]{64}', record['sha256'])):
            raise BackupError('Backup manifest is invalid')
        sha, size = _checksum(data)
        if sha != record.get('sha256') or size != record.get('size'):
            raise BackupError('Backup changed since its manifest was written')
        # Immutable URI avoids SQLite creating -wal/-shm sidecars in the backup
        # directory. No SQL from the database file is executed as code.
        db_uri = data.resolve(strict=True).as_uri() + '?mode=ro&immutable=1'
        try:
            with closing(sqlite3.connect(db_uri, uri=True)) as connection:
                valid = connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                schema = connection.execute('PRAGMA user_version').fetchone()[0]
        except sqlite3.DatabaseError as exc:
            raise BackupError('Backup is not a valid SQLite snapshot') from exc
        if not valid or schema != record.get('sqlite_schema'):
            raise BackupError('SQLite backup integrity or schema mismatch')
        return {'id': identifier, 'valid': True, 'sha256': sha, 'size': size,
                'scope': 'sqlite-only', 'encrypted': False}
    finally:
        store.close()


def list_backups(home: Path | None = None) -> list[str]:
    store = ExperienceStore(home)
    try:
        root = _private_backup_root(store)
        result = []
        for item in root.iterdir():
            found = re.fullmatch(r'profile-([0-9a-f]{32})\.manifest\.json', item.name)
            if found and item.is_file() and not item.is_symlink():
                result.append((item.stat().st_mtime_ns, found[1]))
        return [uid for _, uid in sorted(result, reverse=True)[:100]]
    finally:
        store.close()


def delete_backup(home: Path | None, identifier: str, *, confirmed: bool = False) -> bool:
    if not confirmed:
        raise BackupError('Deleting a private backup requires explicit --confirm')
    store = ExperienceStore(home)
    try:
        data, meta = _paths(_private_backup_root(store), identifier)
        found = False
        for item in (meta, data):
            if item.exists() or item.is_symlink():
                item.unlink()  # only controlled basename inside private backup folder
                found = True
        return found
    finally:
        store.close()



def disarm_recovered_database(db_path: Path) -> None:
    """Require valid schema and drop stale execution authority in recovered DB."""
    with closing(sqlite3.connect(db_path, timeout=5)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise BackupError('Recovered SQLite database failed integrity check')
        schema = int(db.execute('PRAGMA user_version').fetchone()[0])
        if not 1 <= schema <= 6:
            raise BackupError('Recovery database schema is unsupported')
        with db:
            # Checkpoint metadata is evidence, NOT permission to execute.
            # Remove stale runtime preference and disarm all proposal jobs;
            # their external Git worktrees are deliberately not copied.
            db.execute("DELETE FROM checkpoints WHERE task_key='ollama_runtime'")
            db.execute("UPDATE checkpoints SET status='paused' WHERE status='running'")
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='proposal_schedule'").fetchone():
                db.execute("""UPDATE proposal_schedule SET state='paused', lease=NULL,
                    last_result='Recovered offline: owner reauthorization required'
                    WHERE state!='cancelled'""")
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise BackupError('Recovered SQLite changes failed integrity check')


def validated_new_destination(source_home: Path, destination: Path) -> Path:
    """Require an absent, standalone profile root; never overwrite any checkout."""
    dest = Path(destination).expanduser().absolute()
    if dest.exists() or dest.is_symlink():
        raise BackupError('Recovery destination must not exist; never overwrite a profile')
    if not dest.parent.is_dir() or dest.parent.is_symlink():
        raise BackupError('Destination parent must be an existing, non-symlink directory')
    parent = dest.parent.resolve(strict=True)
    if dest.parent != parent:
        raise BackupError('Recovery destination has a symlinked path component')
    if dest == source_home or source_home in dest.parents or dest in source_home.parents:
        raise BackupError('Recover outside the existing AthenZ private profile')
    if any((path / '.git').exists() or (path / '.git').is_symlink()
           for path in (parent, *parent.parents)):
        raise BackupError('Private recovery cannot be placed in a Git checkout')
    if not dest.name or dest.name in {'.', '..'}:
        raise BackupError('Choose a new recovery folder name')
    return dest


def restore_to_new_profile(home: Path | None, identifier: str, destination: Path, *,
                           confirmed: bool = False) -> dict:
    """Recover a verified SQLite snapshot into a NEW offline profile, never over live data.

    Recovered executable authorities (scheduler leases and an active model
    preference) are disarmed. External adapter/model files, worktrees, and
    tool permissions must be revalidated separately. There is no overwrite.
    """
    if not confirmed:
        raise BackupError('Explicit --confirm required for offline profile recovery')
    # Verify complete bytes and schema *before* touching the target.
    verified = verify_backup(home, identifier)
    store = ExperienceStore(home)
    try:
        source_home = store.home.expanduser().resolve(strict=True)
        snapshot, _ = _paths(_private_backup_root(store), identifier)
    finally:
        store.close()
    dest = validated_new_destination(source_home, destination)
    os.mkdir(dest, mode=0o700)  # atomic: existing destination causes failure
    db_path = dest / 'identity.sqlite3'
    provenance = dest / 'recovery.json'
    try:
        # No source-side modification. O_EXCL prevents colliding with an
        # unexpected file; read-only source and bounded copying.
        with snapshot.open('rb') as source:
            fd = os.open(db_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, 'O_NOFOLLOW', 0), 0o600)
            with os.fdopen(fd, 'wb') as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
                target.flush()
                os.fsync(target.fileno())
        # Ensure no one edited the source since verify_backup returned.
        copied_sha, copied_size = _checksum(db_path)
        if copied_sha != verified['sha256'] or copied_size != verified['size']:
            raise BackupError('Recovery source changed during copy')
        disarm_recovered_database(db_path)
        restored_sha, _ = _checksum(db_path)
        record = {'schema': 1, 'source_backup_id': identifier,
                  'source_sha256': verified['sha256'],
                  'restored_db_sha256': restored_sha,
                  'scope': 'sqlite-only', 'external_files_restored': False,
                  'scheduler_disarmed': True, 'model_routing_reset': True}
        _write_new(provenance, (json.dumps(record, sort_keys=True) + '\n').encode('utf-8'))
        return {'path': str(dest), **record}
    except BaseException:
        # Remove ONLY our known files; never chase symlinks or delete an
        # existing profile. If another actor created extras, keep the folder.
        for item in (provenance, db_path):
            if item.exists() or item.is_symlink():
                item.unlink()
        try:
            dest.rmdir()
        except OSError:
            pass
        raise


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Owner-controlled local SQLite backup (no cloud/restore)')
    parser.add_argument('--home', type=Path, default=None)
    cmds = parser.add_subparsers(dest='command', required=True)
    x = cmds.add_parser('create'); x.add_argument('--confirm', action='store_true')
    cmds.add_parser('list')
    x = cmds.add_parser('verify'); x.add_argument('id')
    x = cmds.add_parser('delete'); x.add_argument('id'); x.add_argument('--confirm', action='store_true')
    x = cmds.add_parser('restore-new'); x.add_argument('id'); x.add_argument('--destination', type=Path, required=True); x.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'create':
        report = create_backup(args.home, confirmed=args.confirm)
    elif args.command == 'list':
        report = {'ids': list_backups(args.home)}
    elif args.command == 'verify':
        report = verify_backup(args.home, args.id)
    elif args.command == 'restore-new':
        report = restore_to_new_profile(args.home, args.id, args.destination, confirmed=args.confirm)
    else:
        report = {'deleted': delete_backup(args.home, args.id, confirmed=args.confirm)}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
