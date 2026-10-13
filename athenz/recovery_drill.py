"""Owner-confirmed offline SQLite backup recovery rehearsal.

A rehearsal reads a selected private snapshot, restores it only into a fresh
throwaway directory, tests recovery integrity and permission disarming, and
removes the temporary copy. No live-profile overwrite, model calls, telemetry,
automatic scheduler restart, or Git operations. Reports omit paths and data.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .backup import ID, verify_backup, restore_to_new_profile


# A failed disk-space check is safer than filling an owner's device. 2 GiB is
# a generous upper bound for a SQLite-only rehearsal, not a product quota.
MAX_SNAPSHOT = 2 * 1024 ** 3
MIN_FREE_MARGIN = 32 * 1024 ** 2


class RecoveryDrillError(ValueError):
    """Consent, capacity or isolated recovery checks failed."""


def rehearse_sqlite_backup(home: Path | None, identifier: str, *,
                            confirmed: bool = False, scratch_root: Path | None = None) -> dict:
    """Restore once to a newly created throwaway profile; never retain its data.

    Scratch location may be user-selected, but must already be a non-symlink
    directory outside a Git checkout and the live AthenZ profile. The backed-up
    data is never copied into the project's source repository.
    """
    if confirmed is not True:
        raise RecoveryDrillError('Explicit --confirm is required for a recovery rehearsal')
    if not isinstance(identifier, str) or not ID.fullmatch(identifier):
        raise RecoveryDrillError('Choose a valid 32-character private SQLite backup identifier')
    # The backup verifier uses ExperienceStore, which creates/migrates a
    # profile on open. Refuse absent/unsafe sources before calling it so an
    # accidental rehearsal cannot bootstrap a new private identity database.
    from .profile_health import _home_location
    source_home = _home_location(home)
    database = source_home / 'identity.sqlite3'
    backup_root = source_home / 'backups'
    snapshot = backup_root / ('profile-' + identifier + '.sqlite3')
    manifest = backup_root / ('profile-' + identifier + '.manifest.json')
    if (not source_home.is_dir() or database.is_symlink() or not database.is_file()
            or backup_root.is_symlink() or not backup_root.is_dir()
            or any(p.is_symlink() or not p.is_file() for p in (snapshot, manifest))):
        raise RecoveryDrillError('Existing private profile and SQLite snapshot required')
    # Deliberately do not print arbitrary paths, backup content or raw errors.
    checked = verify_backup(home, identifier)
    if checked.get('valid') is not True or checked.get('scope') != 'sqlite-only':
        raise RecoveryDrillError('Source backup could not be authenticated locally')
    expected_size = checked.get('size')
    if type(expected_size) is not int or not 0 < expected_size <= MAX_SNAPSHOT:
        raise RecoveryDrillError('Backup exceeds the bounded rehearsal size')

    if scratch_root is not None:
        supplied = Path(scratch_root).expanduser().absolute()
        if not supplied.is_dir() or any(
                p.is_symlink() or getattr(p, 'is_junction', lambda: False)()
                for p in (supplied, *supplied.parents)):
            raise RecoveryDrillError('Scratch parent must be a real existing directory')
        # Windows short and long path spellings may reference the same
        # directory; canonicalize before inspecting Git and profile ancestry.
        parent = supplied.resolve(strict=True)
    else:
        parent = Path(tempfile.gettempdir()).resolve()
    # Avoid leaking snapshot contents into Git. Refuse the scratch ancestor if
    # a repository marker or symlink appears in any traversed parent.
    for part in (parent, *parent.parents):
        if part.is_symlink() or (part / '.git').exists() or (part / '.git').is_symlink():
            raise RecoveryDrillError('Scratch directory cannot be within a Git checkout')
    if parent == source_home or source_home in parent.parents:
        raise RecoveryDrillError('Scratch directory must be separate from the live private profile')
    try:
        free = shutil.disk_usage(parent).free
    except OSError as exc:
        raise RecoveryDrillError('Cannot verify temporary free disk space') from exc
    if free < expected_size * 2 + MIN_FREE_MARGIN:
        raise RecoveryDrillError('Insufficient scratch space for a safe recovery rehearsal')

    with tempfile.TemporaryDirectory(prefix='athenz-recovery-drill-', dir=parent) as scratch:
        sandbox = Path(scratch)
        if os.name != 'nt':
            sandbox.chmod(0o700)
        destination = sandbox / 'restored'
        restored = restore_to_new_profile(home, identifier, destination, confirmed=True)
        if destination.is_symlink() or not destination.is_dir():
            raise RecoveryDrillError('Recovered profile directory is unsafe')
        db_path = destination / 'identity.sqlite3'
        if not db_path.is_file() or db_path.is_symlink():
            raise RecoveryDrillError('Recovered SQLite file is unsafe')
        # The recovery function has already checked the full SQLite integrity
        # and disarmed scheduler/model routing. Re-open independently to check.
        with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            version = int(db.execute('PRAGMA user_version').fetchone()[0])
            pending_scheduler = 0
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='proposal_schedule'").fetchone():
                pending_scheduler = db.execute(
                    "SELECT count(*) FROM proposal_schedule WHERE state!='paused' OR lease IS NOT NULL"
                ).fetchone()[0]
            active_route = db.execute("SELECT count(*) FROM checkpoints WHERE task_key='ollama_runtime'").fetchone()[0]
            active_checkpoints = db.execute("SELECT count(*) FROM checkpoints WHERE status='running'").fetchone()[0]
        if (not integrity or not 1 <= version <= 5 or pending_scheduler or active_route or active_checkpoints
                or restored.get('scheduler_disarmed') is not True
                or restored.get('model_routing_reset') is not True):
            raise RecoveryDrillError('Temporary recovery failed integrity or permission checks')
    return {'schema': 1, 'backup_type': 'sqlite-only', 'rehearsal_passed': True,
            'database_integrity_ok': True, 'scheduler_disarmed': True, 'running_checkpoints_paused': True,
            'model_routing_reset': True, 'temp_profile_deleted': True,
            'live_profile_replaced': False, 'source_sqlite_may_be_touched': True,
            'private_records_exposed': False,
            'independent_hardware_validation': False,
            'full_profile_recovery_validated': False}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description='Explicit offline SQLite restore rehearsal; never activates a profile')
    p.add_argument('backup_id', help='Existing SHA-verified private SQLite backup identifier')
    p.add_argument('--home', type=Path, default=None, help='Existing private AthenZ home outside Git')
    p.add_argument('--scratch', type=Path, default=None, help='Optional existing trusted scratch parent')
    p.add_argument('--confirm', action='store_true', help='Required to read private backup and run a rehearsal')
    a = p.parse_args(argv)
    print(json.dumps(rehearse_sqlite_backup(a.home, a.backup_id, confirmed=a.confirm,
                                            scratch_root=a.scratch), indent=2))


if __name__ == '__main__':
    main()
