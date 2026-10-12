"""Offline fail-closed guard against accidental automatic GitHub Actions triggers.

No GitHub API or network access; safe to run when Actions quota is exhausted.
Only recognizes the restricted manual-only YAML event layout we maintain.
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
        if events != ('workflow_dispatch',):
            raise CIBudgetError(f'Automatic trigger detected in {path.name}: {events}')
        audited[path.name] = events
    return audited


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Check AthenZ Actions workflows locally, without running Actions')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    audited = audit_workflows(args.root)
    print(f'{len(audited)} workflows checked: manual workflow_dispatch only; no GitHub requests')


if __name__ == '__main__':
    main()
