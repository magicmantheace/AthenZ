"""Offline fail-closed guard for bounded GitHub Actions triggers.

Owner expressly authorized GitHub Actions during Twin-first development.
Permit ONLY push tests on the named Twin branch; all other workflows and
branches remain manual-only. No GitHub API or network access is required.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re


class CIBudgetError(ValueError):
    """The repository contains a potentially automatic Actions trigger."""


_TOP_LEVEL_ON = re.compile(r"^(?:on|['\"]on['\"]):(?:\s*#.*)?$")
_EVENT = re.compile(r"^  ([a-z][a-z_]*):(?:\s*#.*)?$")
WORKFLOWS = frozenset({'tests.yml', 'windows-portable.yml', 'docker-integration.yml'})
TWIN_TEST_BRANCH = 'feat/twin-first-evidence-boundaries-20261020'


def declared_events(content: str) -> tuple[str, ...]:
    """Extract event names ONLY from a safe block-style top-level `on:`.

    Inline lists, anchors, aliases, duplicate keys and unsupported shapes
    intentionally fail validation instead of being guessed safe.
    """
    lines = content.splitlines()
    on_positions = [idx for idx, line in enumerate(lines) if _TOP_LEVEL_ON.fullmatch(line)]
    if len(on_positions) != 1:
        raise CIBudgetError('Expected exactly one explicit, block-style top-level on:')
    on = on_positions[0]
    # Reject top-level ``on: push`` / ``on: [workflow_dispatch, push]``.
    if any(re.match(r"^(?:on|['\"]on['\"]):", line) and idx != on
           for idx, line in enumerate(lines)):
        raise CIBudgetError('Duplicate or unsupported on: declaration')
    events: list[str] = []
    for line in lines[on + 1:]:
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line.startswith((' ', '\t')):
            break
        if '\t' in line[:len(line) - len(line.lstrip())]:
            raise CIBudgetError('Tab indentation is not supported')
        if line.startswith('  ') and not line.startswith('    '):
            match = _EVENT.fullmatch(line)
            if not match:
                raise CIBudgetError('Unsupported event syntax in on: block')
            events.append(match.group(1))
    if not events or len(set(events)) != len(events):
        raise CIBudgetError('Missing or duplicated trigger names')
    return tuple(events)


def _scoped_twin_push(content: str) -> bool:
    """Reject wildcard/default push triggers and additional push branch names.

    This intentionally recognizes a single explicit YAML subset rather than
    accepting broad events under the user's permission for Actions.
    """
    lines = content.splitlines()
    try:
        start = lines.index('  push:')
    except ValueError:
        return False
    block = []
    for line in lines[start:]:
        if block and line and not line.startswith(' '):
            break
        if block and line.startswith('  ') and not line.startswith('    '):
            break
        if line.strip() and not line.lstrip().startswith('#'):
            block.append(line)
    return block == [
        '  push:', '    branches:', '      - ' + TWIN_TEST_BRANCH,
    ]


def audit_workflows(root: Path) -> dict[str, tuple[str, ...]]:
    directory = Path(root) / '.github' / 'workflows'
    paths = sorted((*directory.glob('*.yml'), *directory.glob('*.yaml')))
    if not WORKFLOWS.issubset({path.name for path in paths}):
        raise CIBudgetError('A required Actions workflow is missing')
    audited: dict[str, tuple[str, ...]] = {}
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise CIBudgetError(f'Unsafe workflow path: {path.name}')
        events = declared_events(path.read_text(encoding='utf-8'))
        if path.name == 'tests.yml' and events == ('push', 'workflow_dispatch'):
            if not _scoped_twin_push(path.read_text(encoding='utf-8')):
                raise CIBudgetError('Unapproved push branch scope in tests.yml')
        elif events != ('workflow_dispatch',):
            raise CIBudgetError(f'Automatic trigger detected in {path.name}: {events}')
        audited[path.name] = events
    return audited


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Check AthenZ Actions workflows locally, without running Actions')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    audited = audit_workflows(args.root)
    print(f'{len(audited)} workflows checked: manual or owner-approved scoped Twin push only')


if __name__ == '__main__':
    main()
