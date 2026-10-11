"""Operator-controlled multi-stage AthenZ coding workflow (no automatic execution)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .chat import OllamaClient
from .experience import ExperienceStore
from .sequencer import SequenceController
from .worker import Worker


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='athenz-sequence')
    p.add_argument('--home', type=Path)
    sub = p.add_subparsers(dest='command', required=True)
    x = sub.add_parser('start')
    x.add_argument('key')
    x.add_argument('repo', type=Path)
    x.add_argument('task')
    x.add_argument('--stage', required=True, action='append',
                   help='Comma-separated list of existing Python files; repeat per stage')
    x.add_argument('--max-failures', type=int, default=2)
    for name in ('show', 'review', 'syntax', 'advance', 'recover'):
        sub.add_parser(name).add_argument('key')
    x = sub.add_parser('prepare')
    x.add_argument('key')
    x.add_argument('--model')
    x = sub.add_parser('apply')
    x.add_argument('key')
    x.add_argument('--sha256', required=True)
    x.add_argument('--confirm', required=True, action='store_true')
    x = sub.add_parser('test', help='Owner-approved full-sequence unittest in pinned Docker')
    x.add_argument('key')
    x.add_argument('--image', required=True)
    x.add_argument('--timeout', type=int, default=120)
    x.add_argument('--confirm', action='store_true', required=True)
    x = sub.add_parser('export')
    x.add_argument('key')
    x.add_argument('--confirm', required=True, action='store_true')
    x = sub.add_parser('publish-local', help='Create local branch after passing container tests; never push')
    x.add_argument('key')
    x.add_argument('--sha256', required=True, help='Exact exported patch SHA-256')
    x.add_argument('--confirm', required=True, action='store_true')
    x = sub.add_parser('cancel')
    x.add_argument('key')
    x.add_argument('--discard-changes', action='store_true')
    return p


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    store = ExperienceStore(args.home)
    try:
        ctl = SequenceController(Worker(store))
        if args.command == 'start':
            result = ctl.start(args.key, args.repo, args.task,
                               [s.split(',') for s in args.stage], max_failures=args.max_failures)
        elif args.command == 'prepare':
            result = ctl.prepare(args.key, OllamaClient(model=args.model))
        elif args.command == 'apply':
            if not args.confirm:
                raise ValueError('Explicit --confirm required')
            result = {'changed_files': ctl.apply(args.key, args.sha256)}
        elif args.command == 'test':
            if not args.confirm:
                raise ValueError('Explicit --confirm required for container execution')
            result = ctl.verify_container(args.key, image=args.image, timeout=args.timeout)
        elif args.command == 'export':
            if not args.confirm:
                raise ValueError('Explicit --confirm required')
            result = ctl.export(args.key)
        elif args.command == 'publish-local':
            if not args.confirm:
                raise ValueError('Explicit --confirm required for local Git ref creation')
            from .publishing import publish_local_branch
            result = publish_local_branch(ctl, args.key, args.sha256)
        elif args.command == 'cancel':
            ctl.cancel(args.key, discard_changes=args.discard_changes)
            result = {'status': 'cancelled'}
        elif args.command == 'show':
            result = ctl.status(args.key)
        else:
            result = getattr(ctl, args.command)(args.key)
        print(json.dumps(result, indent=2))
    finally:
        store.close()


if __name__ == '__main__':
    main()
