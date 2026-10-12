"""Explicit, local-only consistent SQLite snapshots of the private AthenZ profile.

Backups contain *plaintext private information*. This module never uploads,
archives unrelated directories, auto-restores, or executes commands. Model
adapters, datasets, reviews and other files are not part of SQLite snapshots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
            with sqlite3.connect(data) as destination:
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
        if (record.get('id') != identifier or record.get('schema') != 1 or
                record.get('type') != 'private-sqlite-only' or
                record.get('encrypted') is not False or
                record.get('restore_authorized') is not False):
            raise BackupError('Backup manifest is invalid')
        sha, size = _checksum(data)
        if sha != record.get('sha256') or size != record.get('size'):
            raise BackupError('Backup changed since its manifest was written')
        # Immutable URI avoids SQLite creating -wal/-shm sidecars in the backup
        # directory. No SQL from the database file is executed as code.
        db_uri = data.resolve(strict=True).as_uri() + '?mode=ro&immutable=1'
        try:
            with sqlite3.connect(db_uri, uri=True) as connection:
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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Owner-controlled local SQLite backup (no cloud/restore)')
    parser.add_argument('--home', type=Path, default=None)
    cmds = parser.add_subparsers(dest='command', required=True)
    x = cmds.add_parser('create'); x.add_argument('--confirm', action='store_true')
    cmds.add_parser('list')
    x = cmds.add_parser('verify'); x.add_argument('id')
    x = cmds.add_parser('delete'); x.add_argument('id'); x.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'create':
        report = create_backup(args.home, confirmed=args.confirm)
    elif args.command == 'list':
        report = {'ids': list_backups(args.home)}
    elif args.command == 'verify':
        report = verify_backup(args.home, args.id)
    else:
        report = {'deleted': delete_backup(args.home, args.id, confirmed=args.confirm)}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
