"""Opt-in, local training data preparation CLI; no weight update operations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .experience import ExperienceStore
from .training import build_dataset, delete_dataset, inspect_dataset, verify_dataset
from .model_gate import compare_models, save_report
from .chat import OllamaClient


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
    x = sub.add_parser('compare', help='Compare two local models on the SAME held-out decision cases')
    x.add_argument('sha256', help='Previously approved private dataset hash')
    x.add_argument('--baseline', required=True)
    x.add_argument('--candidate', required=True)
    x.add_argument('--split', choices=['calibration', 'test'], default='calibration')
    x.add_argument('--limit', type=int, default=100)
    x.add_argument('--min-cases', type=int, default=10)
    x.add_argument('--seed', type=int, default=42)
    x.add_argument('--confirm', action='store_true', help='Explicit permission for local Ollama inference and report')
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
        elif args.command == 'compare':
            if not args.confirm:
                raise ValueError('--confirm required before running local model benchmarks')
            report = compare_models(store, OllamaClient(model=args.baseline),
                                    OllamaClient(model=args.candidate), args.sha256,
                                    split=args.split, limit=args.limit, seed=args.seed,
                                    min_cases=args.min_cases)
            result = {**report, 'report': save_report(store, report, confirmed=True)}
        else:
            result = {'deleted': delete_dataset(store, args.sha256, confirmed=args.confirm)}
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        store.close()


if __name__ == '__main__':
    main()
