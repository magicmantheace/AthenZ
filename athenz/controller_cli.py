"""Operator-run v0.4 controller: no unattended execution, commit or push."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .chat import OllamaClient
from .controller import CodingController
from .experience import ExperienceStore
from .worker import Worker


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='athenz-controller')
    p.add_argument('--home', type=Path, default=None)
    sub = p.add_subparsers(dest='command', required=True)
    x = sub.add_parser('start')
    x.add_argument('key')
    x.add_argument('repository', type=Path)
    x.add_argument('task')
    x = sub.add_parser('plan')
    x.add_argument('key')
    x.add_argument('files', nargs='+')
    x.add_argument('--model', default=None)
    x.add_argument('--retries', type=int, default=2)
    x = sub.add_parser('prepare')
    x.add_argument('key')
    x.add_argument('--model', default=None)
    for name in ('show', 'review', 'syntax'):
        sub.add_parser(name).add_argument('key')
    x = sub.add_parser('apply')
    x.add_argument('key')
    x.add_argument('--sha256', required=True, help='Exact digest printed by review')
    x.add_argument('--confirm', action='store_true', required=True)
    x = sub.add_parser('export')
    x.add_argument('key')
    x.add_argument('--confirm', action='store_true', required=True)
    x = sub.add_parser('cancel')
    x.add_argument('key')
    x.add_argument('--discard-changes', action='store_true')
    return p


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    store = ExperienceStore(args.home)
    try:
        worker = Worker(store)
        ctl = CodingController(worker)
        if args.command == 'start':
            outcome = worker.begin(args.key, args.repository, args.task)
            print(outcome['state']['workspace'])
        elif args.command == 'plan':
            print(json.dumps(ctl.plan(args.key, args.files, OllamaClient(model=args.model),
                                      max_retries=args.retries), indent=2))
        elif args.command == 'prepare':
            print(json.dumps(ctl.prepare(args.key, OllamaClient(model=args.model)), indent=2))
        elif args.command == 'show':
            print(json.dumps(ctl.status(args.key), indent=2))
        elif args.command == 'review':
            print(json.dumps(ctl.review(args.key), indent=2))
        elif args.command == 'apply':
            if not args.confirm:
                raise ValueError('--confirm is required')
            print(f'Applied {ctl.apply(args.key, args.sha256)} reviewed file changes')
        elif args.command == 'syntax':
            print(json.dumps(ctl.syntax(args.key), indent=2))
        elif args.command == 'export':
            if not args.confirm:
                raise ValueError('--confirm is required')
            print(json.dumps(ctl.export(args.key), indent=2))
        elif args.command == 'cancel':
            worker.cleanup(args.key, discard_changes=args.discard_changes, disposition='cancelled')
            print('Cancelled; no Git commit or push performed')
    finally:
        store.close()


if __name__ == '__main__':
    main()
