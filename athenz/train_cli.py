"""Opt-in, local training data preparation CLI; no weight update operations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .experience import ExperienceStore
from .training import build_dataset, delete_dataset, inspect_dataset, verify_dataset


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='athenz-training', description='Private, reviewed SFT dataset preparation')
    p.add_argument('--home', type=Path, default=None)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('inspect', help='Report counts and leakage/conflict gates without exposing text')
    x = sub.add_parser('build', help='Export approved SFT samples into private local storage')
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('verify', help='Revalidate a snapshot against current approval and bytes')
    x.add_argument('sha256')
    x = sub.add_parser('delete', help='Delete only a named AthenZ dataset and manifest')
    x.add_argument('sha256')
    x.add_argument('--confirm', action='store_true')
    return p


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    store = ExperienceStore(args.home)
    try:
        if args.command == 'inspect':
            result = inspect_dataset(store)
        elif args.command == 'build':
            result = build_dataset(store, confirmed=args.confirm)
        elif args.command == 'verify':
            result = verify_dataset(store, args.sha256)
        else:
            result = {'deleted': delete_dataset(store, args.sha256, confirmed=args.confirm)}
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        store.close()


if __name__ == '__main__':
    main()
