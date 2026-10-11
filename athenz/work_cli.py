"""Explicit supervised worktree operations. No unattended loop or Git publishing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .chat import OllamaClient
from .coding import diff_for
from .experience import ExperienceStore
from .worker import Worker


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='athenz-worker', description='Review-first isolated checkout coding assistant')
    p.add_argument('--home', type=Path, default=None)
    sub = p.add_subparsers(dest='command', required=True)
    x = sub.add_parser('start', help='Begin isolated checkout of clean Git repository')
    x.add_argument('key')
    x.add_argument('repo', type=Path)
    x.add_argument('task')
    x = sub.add_parser('show')
    x.add_argument('key')
    x = sub.add_parser('propose')
    x.add_argument('key')
    x.add_argument('files', nargs='+')
    x.add_argument('--model', default=None)
    x = sub.add_parser('diff')
    x.add_argument('key')
    x = sub.add_parser('apply', help='Apply previously proposed replacement after review')
    x.add_argument('key')
    x.add_argument('--confirm', action='store_true', required=True,
                   help='Explicit permission to modify disposable checkout')
    x = sub.add_parser('retry', help='Explicitly undo or dismiss proposal within 3-retry limit')
    x.add_argument('key')
    x.add_argument('--confirm', action='store_true', required=True)
    x = sub.add_parser('syntax', help='AST parse only; no untrusted Python execution')
    x.add_argument('key')
    x = sub.add_parser('test', help='Run unit tests only within digest-pinned container')
    x.add_argument('key')
    x.add_argument('--image', required=True, help='e.g. python@sha256:<64 lowercase hex>')
    x.add_argument('--confirm', action='store_true', required=True)
    x = sub.add_parser('export-review', help='Write an immutable patch into private AthenZ storage')
    x.add_argument('key')
    x.add_argument('--confirm', action='store_true', required=True)
    x = sub.add_parser('cancel', help='Explicitly cancel a session and clean up worktree')
    x.add_argument('key')
    x.add_argument('--discard-changes', action='store_true')
    x = sub.add_parser('cleanup', help='Explicitly discard or remove worktree')
    x.add_argument('key')
    x.add_argument('--discard-changes', action='store_true')
    return p


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    store = ExperienceStore(args.home)
    try:
        worker = Worker(store)
        if args.command == 'start':
            item = worker.begin(args.key, args.repo, args.task)
            print(f"Worktree created: {item['state']['workspace']}")
        elif args.command == 'show':
            item = worker.resume(args.key)
            print(json.dumps({'key': args.key, 'task': item['task'],
                              'status': item['status'], 'revision': item['revision'],
                              **item['state']}, indent=2))
        elif args.command == 'propose':
            pid = worker.propose(args.key, OllamaClient(model=args.model), args.files)
            print(f'Proposal #{pid}; run `athenz-worker diff {args.key}` before applying')
        elif args.command == 'diff':
            item = worker.resume(args.key)
            if item['state']['proposal_id'] is not None:
                print(diff_for(store, item['state']['proposal_id']))
            else:
                print(worker.diff(args.key))
        elif args.command == 'apply':
            if not args.confirm:
                raise ValueError('Explicit --confirm is required to apply edits')
            print(f"Files changed: {worker.apply(args.key)}")
        elif args.command == 'retry':
            if not args.confirm:
                raise ValueError('Explicit --confirm required to reset proposed changes')
            print(f'Retry #{worker.retry(args.key)} ready for a revised proposal')
        elif args.command == 'syntax':
            print(json.dumps(worker.syntax_check(args.key), indent=2))
        elif args.command == 'test':
            if not args.confirm:
                raise ValueError('Explicit --confirm required for container execution')
            print(json.dumps(worker.container_tests(args.key, image=args.image), indent=2))
        elif args.command == 'export-review':
            if not args.confirm:
                raise ValueError('Explicit --confirm required to export a private review bundle')
            print(json.dumps(worker.export_review(args.key), indent=2))
        elif args.command == 'cancel':
            worker.cleanup(args.key, discard_changes=args.discard_changes, disposition='cancelled')
            print('Cancelled; private metadata retained, edits removed if explicitly discarded')
        elif args.command == 'cleanup':
            worker.cleanup(args.key, discard_changes=args.discard_changes)
            print('Worktree removed; private task record retained')
    finally:
        store.close()


if __name__ == '__main__':
    main()
