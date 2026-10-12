"""Explicit, read-only local SQLite health observation before recovery/update.

This does not initialize/migrate the profile, read user records, run a model,
contact a service, start a scheduler or approve any action. Reports sanitized
metadata only. This is not an attestation or a guarantee of recoverability.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import time


class ProfileHealthError(ValueError):
    """Unsafe location or missing explicit local inspection consent."""


def _home_location(home: Path | None) -> Path:
    if home is None:
        home = Path(os.environ.get('ATHENZ_HOME', str(Path.home() / '.athenz')))
    raw = Path(home).expanduser().absolute()
    if any(path.is_symlink() for path in (raw, *raw.parents)):
        raise ProfileHealthError('Refusing a symlinked private profile path')
    home = raw.resolve(strict=False)
    if any((path / '.git').exists() for path in (home, *home.parents)):
        raise ProfileHealthError('Private profile must be outside any Git checkout')
    return home


def inspect_profile(home: Path | None = None, *, confirmed: bool = False,
                    timeout_seconds: int = 5) -> dict:
    """Read a private SQLite quick-check after explicit approval, with no data output.

    The health probe is a local observation, not a snapshot or recovery test.
    Python SQLite mode=ro may need existing WAL shared-memory state; inability
    to read it is reported as unavailable, not permission to modify the DB.
    """
    if not confirmed:
        raise ProfileHealthError('Explicit --confirm required for a private profile inspection')
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 15:
        raise ProfileHealthError('Inspection timeout must be 1..15 seconds')
    private = _home_location(home)
    base = {'schema': 1, 'status': 'not-initialized', 'database_present': False,
            'sqlite_integrity_ok': False, 'schema_version': None,
            'database_owner_only': None, 'read_only_requested': True,
            'private_data_collected': False, 'records_exposed': False,
            'network_accessed': False, 'hardware_validated': False,
            'recovery_validated': False, 'deploy_authorized': False}
    if not private.exists():
        return base
    if not private.is_dir():
        raise ProfileHealthError('Private profile is not a directory')
    if os.name != 'nt' and (private.stat().st_mode & 0o077):
        raise ProfileHealthError('Private profile directory is accessible to others')
    db = private / 'identity.sqlite3'
    # SQLite may inspect adjacent WAL and SHM files; disallow pointer aliases.
    for sidecar in (db, private / 'identity.sqlite3-wal', private / 'identity.sqlite3-shm'):
        if sidecar.is_symlink():
            raise ProfileHealthError('Refusing a symlinked SQLite database or sidecar')
    if not db.exists():
        return base
    if not db.is_file():
        raise ProfileHealthError('Invalid SQLite database file')
    owner_only = None if os.name == 'nt' else not bool(db.stat().st_mode & 0o077)
    report = {**base, 'database_present': True, 'database_owner_only': owner_only,
              'status': 'unavailable'}
    try:
        # No SQLite schema creation or AthenZ migrations, and no private rows.
        con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True,
                              timeout=min(timeout_seconds, 5))
        try:
            started = time.monotonic()
            con.set_progress_handler(
                lambda: int(time.monotonic() - started >= timeout_seconds), 1000)
            con.execute('PRAGMA query_only=ON')
            version = con.execute('PRAGMA user_version').fetchone()[0]
            ok = con.execute('PRAGMA quick_check(1)').fetchone()[0] == 'ok'
        finally:
            con.close()
    except (sqlite3.Error, OSError, ValueError):
        # Never expose database contents, SQLite messages, local paths or SQL.
        return report
    return {**report, 'status': 'ok' if ok else 'integrity-failed',
            'sqlite_integrity_ok': bool(ok), 'schema_version': int(version)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Read-only local AthenZ SQLite health check')
    parser.add_argument('--home', type=Path, default=None, help='Private profile outside Git')
    parser.add_argument('--confirm', action='store_true', help='Authorize local private SQLite inspection')
    parser.add_argument('--timeout', type=int, default=5, help='Bound SQLite quick-check to 1..15 seconds')
    args = parser.parse_args(argv)
    report = inspect_profile(args.home, confirmed=args.confirm, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2))
    if report['status'] not in ('ok', 'not-initialized'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
