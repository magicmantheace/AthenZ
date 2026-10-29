"""Explicitly started supervised local proposal scheduler; off by default."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .scheduler import ProposalScheduler


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='athenz-scheduler', description='Owner-controlled proposal queue; no automatic patch application')
    p.add_argument('--home', type=Path, default=None)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    x = sub.add_parser('show'); x.add_argument('key')
    x = sub.add_parser('add'); x.add_argument('key'); x.add_argument('--model', required=True); x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('arm'); x.add_argument('key'); x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('pause'); x.add_argument('key')
    x = sub.add_parser('cancel'); x.add_argument('key'); x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('remove'); x.add_argument('key'); x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('recover'); x.add_argument('key'); x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('tick'); x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('serve'); x.add_argument('--confirm', action='store_true')
    x.add_argument('--ticks', type=int, default=10); x.add_argument('--interval', type=int, default=30)
    return p


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    queue = ProposalScheduler(args.home)
    if args.command == 'list': result = queue.list()
    elif args.command == 'show': result = queue.get(args.key)
    elif args.command == 'add': result = queue.register(args.key, model=args.model, confirmed=args.confirm)
    elif args.command == 'arm': result = queue.arm(args.key, confirmed=args.confirm)
    elif args.command == 'pause': result = queue.pause(args.key)
    elif args.command == 'cancel': result = queue.cancel(args.key, confirmed=args.confirm)
    elif args.command == 'remove': result = {'removed': queue.remove(args.key, confirmed=args.confirm)}
    elif args.command == 'recover': result = queue.recover(args.key, confirmed=args.confirm)
    elif args.command == 'tick': result = queue.run_once(confirmed=args.confirm)
    else:
        if not args.confirm:
            raise ValueError('The foreground scheduler is off by default: add --confirm')
        result = queue.serve(confirmed=True, ticks=args.ticks, interval=args.interval,
                             on_tick=lambda event: print(json.dumps(event, ensure_ascii=False, default=str), flush=True))
        result = {'ticks': len(result), 'status': 'foreground stopped'}
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
