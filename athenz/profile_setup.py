"""Opt-in private profile status for the AthenZ Setup screen.

The GUI never requests this inspection automatically. The adapter only passes
owner-confirmed intent to the read-only backend and formats a fixed allowlist
of metadata; no paths, SQLite rows or backend exception messages are shown.
"""
from __future__ import annotations

from pathlib import Path


class ProfileSetupError(ValueError):
    """A profile inspection or report was not safely authorized."""


def inspect_for_setup(home: Path | None = None, *, confirmed: bool = False) -> dict:
    """Get sanitized SQLite metadata strictly after a separate owner decision."""
    if confirmed is not True:
        raise ProfileSetupError('Profile inspection needs a separate explicit confirmation')
    from .profile_health import inspect_profile
    return inspect_profile(home, confirmed=True)


def format_for_setup(report: dict) -> str:
    """Render exclusively known status codes and bounded integers, never raw data."""
    if not isinstance(report, dict):
        raise ProfileSetupError('Invalid profile health report')
    status = report.get('status')
    labels = {
        'not-initialized': 'Not initialized: no existing private SQLite profile was found.',
        'ok': 'SQLite quick-check completed successfully.',
        'unavailable': 'SQLite health could not be checked safely.',
        'integrity-failed': 'SQLite quick-check detected an integrity problem.',
    }
    if type(status) is not str or status not in labels:
        raise ProfileSetupError('Unrecognized private profile health status')
    schema = report.get('schema_version')
    if schema is not None and (type(schema) is not int or schema < 0 or schema > 1_000_000):
        raise ProfileSetupError('Invalid private profile schema value')
    permission = report.get('database_owner_only')
    if permission is not None and type(permission) is not bool:
        raise ProfileSetupError('Invalid private profile access report')
    lines = ['PRIVATE PROFILE HEALTH (owner-requested only)', '', labels[status]]
    if schema is not None:
        lines.append(f'SQLite schema version: {schema}')
    if permission is True:
        lines.append('POSIX file permissions: owner-only observed')
    elif permission is False:
        lines.append('POSIX file permissions: review file access restrictions')
    else:
        lines.append('File permission check: not available')
    lines.extend(['', 'No personal rows, file paths or device identifiers displayed.',
                  'This is a limited read-only SQLite observation, NOT a restore test,',
                  'migration, model test, hardware validation or permission grant.',
                  'Use separate, owner-confirmed backup verification before updating.'])
    return '\n'.join(lines)
