"""Opt-in, local training data preparation CLI; no weight update operations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .experience import ExperienceStore
from .training import build_dataset, delete_dataset, inspect_dataset, verify_dataset
from .model_gate import compare_models, save_report
from .chat import OllamaClient
from .finetune import create_run, describe_run, execute_run
from .adapters import register_adapter, selection, select_for_review, rollback_selection


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
    x = sub.add_parser('prepare-qlora', help='Create private, immutable QLoRA recipe; NO training')
    x.add_argument('sha256', help='Approved training dataset SHA-256')
    x.add_argument('--base-model', type=Path, required=True, help='Existing offline Qwen2.5 HF safetensors directory')
    x.add_argument('--max-steps', type=int, default=80)
    x.add_argument('--seq-length', type=int, default=512)
    x.add_argument('--seed', type=int, default=42)
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('verify-qlora', help='Verify private recipe, source consent and local base weights')
    x.add_argument('run_id')
    x = sub.add_parser('run-qlora', help='Opt-in experimental CUDA QLoRA trainer; never deploys')
    x.add_argument('run_id')
    x.add_argument('--resume', action='store_true', help='Explicitly resume an interrupted/failed run')
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('register-adapter', help='Register completed private adapter (no Ollama load)')
    x.add_argument('run_id')
    x.add_argument('--candidate', required=True, help='Explicit LOCAL candidate label; lineage unverified')
    x.add_argument('--confirm', action='store_true')
    sub.add_parser('selection', help='Show private adapter-review pointer; NOT deployed')
    x = sub.add_parser('select-adapter', help='Save owner-approved review pointer; no inference change')
    x.add_argument('run_id')
    x.add_argument('--report-sha256', required=True)
    x.add_argument('--revision', type=int, required=True)
    x.add_argument('--ack-lineage', action='store_true', help='I manually verified candidate uses this adapter')
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('rollback-adapter', help='Revert private review pointer, not Ollama')
    x.add_argument('--revision', type=int, required=True)
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
        elif args.command == 'prepare-qlora':
            result = create_run(store, args.sha256, args.base_model,
                                max_steps=args.max_steps, seq_length=args.seq_length,
                                seed=args.seed, confirmed=args.confirm)
        elif args.command == 'verify-qlora':
            result = describe_run(store, args.run_id)
        elif args.command == 'run-qlora':
            result = execute_run(store, args.run_id, confirmed=args.confirm, resume=args.resume)
        elif args.command == 'register-adapter':
            result = register_adapter(store, args.run_id, args.candidate, confirmed=args.confirm)
        elif args.command == 'selection':
            result = selection(store)
        elif args.command == 'select-adapter':
            result = select_for_review(store, args.run_id, args.report_sha256,
                                       expected_revision=args.revision,
                                       confirmed=args.confirm,
                                       lineage_acknowledged=args.ack_lineage)
        elif args.command == 'rollback-adapter':
            result = rollback_selection(store, expected_revision=args.revision,
                                        confirmed=args.confirm)
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
