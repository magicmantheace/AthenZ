"""Bounded local AthenZ validation without invoking GitHub Actions.

Runs fixed repository tests and optionally builds a wheel without package-index
access. This is NOT a sandbox for untrusted source or a guarantee that project
unit tests cannot perform network I/O. Execute only reviewed local source.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


MODES = ('policy', 'full', 'wheel', 'all')
MAX_TIMEOUT = 900


class LocalValidationError(ValueError):
    """Invalid local validation request."""


def _valid_root(root: Path) -> Path:
    root = Path(root)
    if root.is_symlink():
        raise LocalValidationError('Validation root must not be a symlink')
    root = root.resolve(strict=True)
    for name in ('pyproject.toml', 'athenz/__init__.py', 'tools/ci_budget.py'):
        candidate = root / name
        if candidate.is_symlink() or not candidate.is_file():
            raise LocalValidationError('Repository source and CI policy files are required')
    return root


def _wheel_snapshot(root: Path, destination: Path) -> None:
    """Stage package sources so building never writes artifacts into checkout."""
    source = root / 'athenz'
    if source.is_symlink():
        raise LocalValidationError('Refusing a symlinked package directory')
    for path in source.rglob('*'):
        if path.is_symlink():
            raise LocalValidationError('Refusing a symlink inside package sources')
    shutil.copytree(source, destination / 'athenz', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copy2(root / 'pyproject.toml', destination / 'pyproject.toml')
    if (root / 'README.md').is_file() and not (root / 'README.md').is_symlink():
        shutil.copy2(root / 'README.md', destination / 'README.md')


def validate(root: Path, *, mode: str = 'policy', timeout: int = 180) -> dict:
    """Run explicitly selected local checks; return statuses, not source output."""
    if mode not in MODES:
        raise LocalValidationError('Choose policy, full, wheel or all')
    if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT:
        raise LocalValidationError('Timeout must be 1–900 seconds')
    root = _valid_root(root)
    from tools.ci_budget import audit_workflows
    from tools.source_inventory import check_complete
    # A run never proceeds if CI may automatically trigger in the checkout.
    audited = audit_workflows(root)
    # The archival checkout must be complete before declaring its wheel or
    # entire test suite good. Ordinary edited development files are allowed.
    # Policy-only checks remain usable while reconstructing a checkout.
    inventory = check_complete(root) if mode in ('full', 'wheel', 'all') else None
    steps = []
    if mode in ('policy', 'all'):
        steps.append(('policy-unit-tests', [sys.executable, '-m', 'unittest', 'tests.test_ci_budget', '-q']))
    if mode in ('full', 'all'):
        steps.append(('full-unit-suite', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-q']))
    if mode in ('wheel', 'all'):
        steps.append(('wheel-no-index', None))
    results = []
    with TemporaryDirectory(prefix='athenz-local-validate-') as tmp:
        private = Path(tmp) / 'private'
        private.mkdir()
        env = os.environ.copy()
        env.update({'ATHENZ_HOME': str(private), 'PIP_NO_INDEX': '1',
                    'PIP_DISABLE_PIP_VERSION_CHECK': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                    'PYTHONPATH': str(root)})
        for name, command in steps:
            cwd = root
            if command is None:
                staged = Path(tmp) / 'build-source'
                staged.mkdir()
                _wheel_snapshot(root, staged)
                cwd = staged
                command = [sys.executable, '-m', 'pip', 'wheel', '--no-index',
                           '--no-deps', '--no-build-isolation', '--wheel-dir', str(Path(tmp) / 'wheels'), '.']
            try:
                finished = subprocess.run(command, cwd=cwd, env=env, shell=False,
                                          capture_output=True, text=True, timeout=timeout,
                                          errors='replace')
                ok = finished.returncode == 0
                note = 'passed' if ok else 'failed-local-process'
            except (OSError, subprocess.TimeoutExpired):
                ok = False
                note = 'unavailable-or-timeout'
            results.append({'check': name, 'passed': ok, 'status': note})
            if not ok:
                break  # fail closed; do not build a wheel after failing tests
    return {'schema': 1, 'mode': mode, 'checks': results,
            'passed': bool(results) and all(c['passed'] for c in results),
            'workflows_audited': len(audited), 'github_actions_invoked': False,
            'hardware_validated': False, 'network_sandboxed': False,
            'source_inventory_complete': inventory is not None,
            'source_content_verified': False}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description='Run fixed AthenZ local checks (no GitHub Actions)')
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument('--mode', choices=MODES, default='policy')
    p.add_argument('--timeout', type=int, default=180)
    args = p.parse_args(argv)
    result = validate(args.root, mode=args.mode, timeout=args.timeout)
    print(json.dumps(result, indent=2))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
