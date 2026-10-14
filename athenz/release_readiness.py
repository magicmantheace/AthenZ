"""Private, manually recorded release-acceptance observations.

Records owner-reported outcomes; NEVER claims automated proof, certification,
training success, signing, installed models, or authorization to deploy.
No system probes, subprocesses, model calls or network access occur here.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import stat


CHECKS = (
    ('windows-gui-hidpi', 'Human inspection of desktop layout and high-DPI scaling on target Windows 11'),
    ('keyboard-accessibility', 'Keyboard-only and assistive-technology usability on target Windows'),
    ('ollama-inference', 'Owner-approved local Ollama Agent/Twin inference and routing on target PC'),
    ('rtx3060-cuda-qlora', 'Actual RTX 3060 CUDA / WSL2 QLoRA training, memory budget and adapter validation'),
    ('wsl2-docker', 'Trust-pinned Docker code-test isolation on target Windows/WSL2'),
    ('profile-recovery', 'Owner-performed offline backup and new-profile recovery drill'),
    ('portable-update-rollback', 'Verified side-by-side unsigned portable update and manual rollback'),
    ('privacy-consent', 'Private storage, permissions and approval-gate acceptance review'),
    ('signed-release', 'Authentic publisher signing, installer and release-update validation'),
)
VALID = frozenset(('passed', 'failed', 'blocked'))


class ReadinessError(ValueError):
    """Invalid local acceptance record or unsafe private storage."""


def _private_home(home: Path | None) -> Path:
    if home is None:
        home = Path(os.environ.get('ATHENZ_HOME', str(Path.home() / '.athenz')))
    home = Path(home).expanduser()
    if home.is_symlink():
        raise ReadinessError('Private home must not be a symlink')
    resolved = home.resolve()
    if any((folder / '.git').exists() for folder in (resolved, *resolved.parents)):
        raise ReadinessError('Never store acceptance state inside a Git checkout')
    # A database created within a shared POSIX directory can be read before
    # its file-mode hardening completes. Refuse unsafe pre-existing homes.
    if os.name != 'nt' and resolved.is_dir() and (resolved.stat().st_mode & 0o077):
        raise ReadinessError('Private home must not be accessible to group or other users')
    db = resolved / 'release-acceptance.sqlite3'
    if db.is_symlink():
        raise ReadinessError('Unsafe private acceptance database')
    if db.exists():
        metadata = db.lstat()
        # A hardlink could point at a database owned by another workflow. An
        # overly permissive existing file might disclose acceptance history.
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1
                or (os.name != 'nt' and metadata.st_mode & 0o077)):
            raise ReadinessError('Unsafe private acceptance database')
    return resolved


def acceptance_plan() -> dict:
    """Return public static requirements without touching disk or hardware."""
    return {'schema': 1, 'title': 'AthenZ release acceptance (owner observations)',
            'requirements': [{'id': key, 'check': description, 'type': 'owner-observed'}
                             for key, description in CHECKS],
            'grants_permissions': False, 'starts_work': False, 'runs_hardware_tests': False,
            'launches_models': False, 'automated_attestation': False}


def record(home: Path | None, check_id: str, status: str, *, confirmed: bool = False) -> dict:
    """Persist only owner-reported status in a separate private SQLite file."""
    if not confirmed:
        raise ReadinessError('Recording requires explicit --confirm')
    if check_id not in dict(CHECKS) or status not in VALID:
        raise ReadinessError('Choose a known acceptance case and status')
    private = _private_home(home)
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    db_path = private / 'release-acceptance.sqlite3'
    if db_path.is_symlink():
        raise ReadinessError('Unsafe acceptance database')
    # Exclusive BEGIN IMMEDIATE prevents lost updates with simultaneous CLI users.
    con = sqlite3.connect(db_path, timeout=10)
    try:
        con.execute('CREATE TABLE IF NOT EXISTS observations '
                    '(check_id TEXT PRIMARY KEY, status TEXT NOT NULL, '
                    'source TEXT NOT NULL, recorded_at TEXT NOT NULL)')
        con.execute('CREATE TABLE IF NOT EXISTS observation_history '
                    '(id INTEGER PRIMARY KEY AUTOINCREMENT, '
                    'check_id TEXT NOT NULL, status TEXT NOT NULL, '
                    'source TEXT NOT NULL, recorded_at TEXT NOT NULL)')
        with con:
            con.execute('BEGIN IMMEDIATE')
            con.execute("INSERT INTO observations (check_id,status,source,recorded_at) "
                        "VALUES (?,?,'owner-reported',strftime('%Y-%m-%dT%H:%M:%fZ','now')) "
                        "ON CONFLICT(check_id) DO UPDATE SET status=excluded.status, "
                        "source=excluded.source, recorded_at=excluded.recorded_at",
                        (check_id, status))
            con.execute(
                "INSERT INTO observation_history (check_id,status,source,recorded_at) "
                "VALUES (?,?,'owner-reported',strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (check_id, status))
    finally:
        con.close()
    if os.name != 'nt':
        db_path.chmod(0o600)
    return {'id': check_id, 'status': status, 'source': 'owner-reported',
            'independently_attested': False, 'deploy_authorized': False}


def status_report(home: Path | None) -> dict:
    """Read-only status; no database created when no observations exist."""
    private = _private_home(home)
    db = private / 'release-acceptance.sqlite3'
    observed: dict[str, str] = {}
    history_count = 0
    if db.is_file():
        # SQLite mode=ro prevents creation of a new database on a status query.
        con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            rows = list(con.execute('SELECT check_id,status,source FROM observations'))
            if any(key not in dict(CHECKS) or status not in VALID
                   or source != 'owner-reported' for key, status, source in rows):
                raise ReadinessError('Private acceptance observations are invalid')
            observed = {str(key): str(value) for key, value, _ in rows}
            history_exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND "
                "name='observation_history'").fetchone()
            if history_exists:
                history_count = int(con.execute(
                    'SELECT COUNT(*) FROM observation_history').fetchone()[0])
                # Legacy unanchored current rows are supported. But once a
                # check has an owner-history event, its current row MUST exist
                # and agree with the latest event. Inspect every event, not
                # only the most recent event for each surviving current row:
                # otherwise deleting a failed current row or corrupting an
                # older event could silently hide acceptance evidence.
                latest: dict[str, str] = {}
                for check_id, state, source, timestamp in con.execute(
                        'SELECT check_id,status,source,recorded_at '
                        'FROM observation_history ORDER BY id'):
                    if (check_id not in dict(CHECKS) or state not in VALID
                            or source != 'owner-reported'
                            or not isinstance(timestamp, str)
                            or len(timestamp) > 40 or not timestamp.endswith('Z')):
                        raise ReadinessError('Private acceptance history is invalid')
                    latest[check_id] = state
                if any(observed.get(check_id) != state
                       for check_id, state in latest.items()):
                    raise ReadinessError('Private acceptance observation history disagrees with current status')
        except sqlite3.DatabaseError as exc:
            raise ReadinessError('Private acceptance database is invalid') from exc
        finally:
            con.close()
    items = [{'id': key, 'check': description, 'status': observed.get(key, 'not-recorded'),
              'source': 'owner-reported' if key in observed else 'none',
              'independently_attested': False} for key, description in CHECKS]
    return {'schema': 1, 'requirements': items,
            'owner_observation_history_events': history_count,
            'recorded': sum(x['status'] != 'not-recorded' for x in items),
            'all_owner_reported_passed': all(x['status'] == 'passed' for x in items),
            'release_certified': False, 'model_deployment_authorized': False,
            'hardware_independently_validated': False}


def history_report(home: Path | None, *, limit: int = 25) -> dict:
    """Return a bounded read-only view of owner-only acceptance history."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ReadinessError('History limit must be an integer from 1 to 100')
    private = _private_home(home)
    db = private / 'release-acceptance.sqlite3'
    records: list[dict] = []
    if db.is_file():
        con = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            present = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='observation_history'").fetchone()
            if present:
                rows = con.execute(
                    "SELECT check_id,status,source,recorded_at FROM observation_history "
                    "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
                for check_id, status, source, timestamp in rows:
                    if (check_id not in dict(CHECKS) or status not in VALID
                            or source != 'owner-reported' or
                            not isinstance(timestamp, str) or len(timestamp) > 40 or
                            not timestamp.endswith('Z')):
                        raise ReadinessError('Private acceptance history is invalid')
                    records.append({'id': check_id, 'status': status,
                                    'source': source, 'recorded_at': timestamp})
        except sqlite3.DatabaseError as exc:
            raise ReadinessError('Private acceptance history is invalid') from exc
        finally:
            con.close()
    return {'schema': 1, 'events': records, 'count': len(records),
            'independently_attested': False, 'release_certified': False}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='AthenZ manual release-acceptance evidence, local only')
    parser.add_argument('--home', type=Path, default=None, help='Private AthenZ profile outside Git')
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('plan', help='Public release checks, no filesystem writes')
    actions.add_parser('status', help='Read owner reports without changing data')
    history = actions.add_parser('history', help='Read latest owner observation events only')
    history.add_argument('--limit', type=int, default=25,
                         help='Maximum events to return (1..100)')
    mark = actions.add_parser('record', help='Record an owner observation; never certifies release')
    mark.add_argument('check_id', choices=[name for name, _ in CHECKS])
    mark.add_argument('result', choices=sorted(VALID))
    mark.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    if args.action == 'plan':
        output = acceptance_plan()
    elif args.action == 'status':
        output = status_report(args.home)
    elif args.action == 'history':
        output = history_report(args.home, limit=args.limit)
    else:
        output = record(args.home, args.check_id, args.result, confirmed=args.confirm)
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
