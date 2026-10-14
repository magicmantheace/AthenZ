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
import zipfile

from .backup import ID, _checksum, verify_backup, restore_to_new_profile
from .profile_bundle import (MAX_TOTAL, _secure_name, verify_bundle,
                             restore_bundle_new)


# A failed disk-space check is safer than filling an owner's device. 2 GiB is
# a generous upper bound for a SQLite-only rehearsal, not a product quota.
MAX_SNAPSHOT = 2 * 1024 ** 3
MIN_FREE_MARGIN = 32 * 1024 ** 2


class RecoveryDrillError(ValueError):
    """Consent, capacity or isolated recovery checks failed."""


def _safe_scratch_parent(source_home: Path, scratch_root: Path | None,
                         required_bytes: int) -> Path:
    """Validate an existing non-Git scratch parent and conservative disk budget."""
    if scratch_root is not None:
        supplied = Path(scratch_root).expanduser().absolute()
        if not supplied.is_dir() or any(
                p.is_symlink() or getattr(p, 'is_junction', lambda: False)()
                for p in (supplied, *supplied.parents)):
            raise RecoveryDrillError('Scratch parent must be a real existing directory')
        parent = supplied.resolve(strict=True)
    else:
        parent = Path(tempfile.gettempdir()).resolve()
    for part in (parent, *parent.parents):
        if (part.is_symlink() or (part / '.git').exists() or
                (part / '.git').is_symlink()):
            raise RecoveryDrillError('Scratch directory cannot be within a Git checkout')
    if parent == source_home or source_home in parent.parents:
        raise RecoveryDrillError('Scratch directory must be separate from the live private profile')
    try:
        free = shutil.disk_usage(parent).free
    except OSError as exc:
        raise RecoveryDrillError('Cannot verify temporary free disk space') from exc
    if free < required_bytes + MIN_FREE_MARGIN:
        raise RecoveryDrillError('Insufficient scratch space for a safe recovery rehearsal')
    return parent


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

    parent = _safe_scratch_parent(source_home, scratch_root, expected_size * 2)

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
        if (not integrity or not 1 <= version <= 6 or pending_scheduler or active_route or active_checkpoints
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


def rehearse_profile_bundle(home: Path | None, identifier: str, *,
                           confirmed: bool = False,
                           scratch_root: Path | None = None) -> dict:
    """Rehearse full selected-asset recovery in a disposable offline profile.

    Plaintext may temporarily exist under owner-selected local scratch.
    Neither the source profile nor external model/adapter runtime is activated.
    Reports contain only fixed technical booleans and artifact counts.
    """
    if confirmed is not True:
        raise RecoveryDrillError('Explicit --confirm required for plaintext bundle rehearsal')
    if not isinstance(identifier, str) or not ID.fullmatch(identifier):
        raise RecoveryDrillError('Choose a valid private profile bundle identifier')
    from .profile_health import _home_location
    source_home = _home_location(home)
    archive = source_home / 'bundles' / ('bundle-' + identifier + '.zip')
    sidecar = source_home / 'bundles' / ('bundle-' + identifier + '.manifest.json')
    if (not source_home.is_dir() or
            not (source_home / 'identity.sqlite3').is_file() or
            (source_home / 'identity.sqlite3').is_symlink() or
            any(p.is_symlink() or not p.is_file() for p in (archive, sidecar))):
        raise RecoveryDrillError('Existing private profile and verified bundle required')
    verified = verify_bundle(source_home, identifier)
    bytes_needed = verified.get('bytes')
    if type(bytes_needed) is not int or not 0 < bytes_needed <= MAX_TOTAL + 2 * 1024**2:
        raise RecoveryDrillError('Private bundle exceeds the rehearsal size bound')
    # Archive is stored, not compressed, and the restore destination plus
    # original verifier scratch may need ~2x its size. Reserve a 3x margin.
    parent = _safe_scratch_parent(source_home, scratch_root, bytes_needed * 3)
    with tempfile.TemporaryDirectory(prefix='athenz-bundle-drill-', dir=parent) as scratch:
        sandbox = Path(scratch)
        if os.name != 'nt':
            sandbox.chmod(0o700)
        dest = sandbox / 'recovered'
        try:
            restored = restore_bundle_new(source_home, identifier, dest, confirmed=True)
        except (OSError, ValueError, sqlite3.DatabaseError, zipfile.BadZipFile):
            # OS errors and lower-level recovery diagnostics may contain
            # private filenames, paths or owner content. Never print them
            # through this explicitly sanitized rehearsal interface.
            raise RecoveryDrillError('Temporary private bundle recovery failed') from None
        db_path = dest / 'identity.sqlite3'
        if db_path.is_symlink() or not db_path.is_file():
            raise RecoveryDrillError('Recovered bundle database is unsafe')
        with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            version = db.execute('PRAGMA user_version').fetchone()[0]
            scheduling = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='proposal_schedule'"
            ).fetchone()
            active_jobs = (db.execute(
                "SELECT count(*) FROM proposal_schedule WHERE state!='paused' OR lease IS NOT NULL"
            ).fetchone()[0] if scheduling else 0)
            runtime_routes = db.execute(
                "SELECT count(*) FROM checkpoints WHERE task_key='ollama_runtime'"
            ).fetchone()[0]
            running = db.execute(
                "SELECT count(*) FROM checkpoints WHERE status='running'"
            ).fetchone()[0]
        if (not integrity or not 1 <= version <= 6 or active_jobs or
                runtime_routes or running or
                restored.get('scheduler_disarmed') is not True or
                restored.get('model_routing_reset') is not True):
            raise RecoveryDrillError('Recovered bundle retained execution authority')
        # The restore path rechecked the source ZIP checksum. Independently
        # hash every restored member against the included per-file manifest.
        try:
            with zipfile.ZipFile(archive, mode='r') as zf:
                info = zf.getinfo('manifest.json')
                if info.file_size > 2 * 1024 * 1024:
                    raise RecoveryDrillError('Private bundle manifest changed during rehearsal')
                manifest = json.loads(zf.read(info))
            if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), list):
                raise RecoveryDrillError('Private bundle manifest changed during rehearsal')
            rows = manifest['files']
        except (OSError, KeyError, TypeError, ValueError, zipfile.BadZipFile):
            raise RecoveryDrillError('Private bundle manifest changed during rehearsal') from None
        for entry in rows:
            rel = _secure_name(entry['path'])
            copied = dest.joinpath(*rel.split('/'))
            if copied.is_symlink() or not copied.is_file():
                raise RecoveryDrillError('Recovered bundle member is missing or unsafe')
            checksum, length = _checksum(copied)
            if rel == 'identity.sqlite3':
                # Restoration MUST change SQLite: stale scheduler authority
                # is removed and old running checkpoints are paused. Compare
                # against the recovery provenance's POST-disarm digest, not
                # the pre-disarm archive hash.
                if (checksum != restored.get('restored_db_sha256') or
                        length <= 0):
                    raise RecoveryDrillError('Recovered database provenance is inconsistent')
            elif (checksum, length) != (entry['sha256'], entry['bytes']):
                raise RecoveryDrillError('Recovered bundle member hash changed')
        if (restored.get('files_restored') != len(rows) or
                any((dest / folder).exists()
                    for folder in ('worktrees', 'snapshots', 'backups', 'bundles'))):
            raise RecoveryDrillError('Recovered profile contains out-of-scope files')
        if _checksum(archive)[0] != verified['sha256']:
            raise RecoveryDrillError('Private bundle changed during rehearsal')
    return {'schema': 1, 'backup_type': 'selected-profile-bundle',
            'rehearsal_passed': True, 'database_integrity_ok': True,
            'selected_files_verified': len(rows),
            'scheduler_disarmed': True, 'running_checkpoints_paused': True,
            'model_routing_reset': True, 'temp_profile_deleted': True,
            'live_profile_replaced': False, 'source_profile_may_be_touched': True,
            'private_records_exposed': False, 'independent_hardware_validation': False,
            'externally_installed_models_restored': False}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description='Explicit offline SQLite restore rehearsal; never activates a profile')
    p.add_argument('backup_id', help='Existing 32-character SQLite or profile-bundle identifier')
    p.add_argument('--bundle', action='store_true',
                   help='Rehearse selected private profile bundle instead of SQLite-only backup')
    p.add_argument('--home', type=Path, default=None, help='Existing private AthenZ home outside Git')
    p.add_argument('--scratch', type=Path, default=None, help='Optional existing trusted scratch parent')
    p.add_argument('--confirm', action='store_true', help='Required to read private backup and run a rehearsal')
    a = p.parse_args(argv)
    result = (rehearse_profile_bundle(a.home, a.backup_id, confirmed=a.confirm,
                                      scratch_root=a.scratch)
              if a.bundle else
              rehearse_sqlite_backup(a.home, a.backup_id, confirmed=a.confirm,
                                     scratch_root=a.scratch))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
