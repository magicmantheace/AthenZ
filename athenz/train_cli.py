"""Opt-in, local training data preparation CLI; no weight update operations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .experience import ExperienceStore
from .training import build_dataset, delete_dataset, inspect_dataset, verify_dataset
from .model_gate import compare_models, save_report, inspect_heldout_readiness
from .learning_cycle import inspect_learning_cycle
from .learning_session import (start_session, session_status, record_baseline,
                               link_completed_run, link_comparison, close_session,
                               cancel_session, session_comparison_context,
                               LearningSessionError)
from .chat import OllamaClient
from .finetune import create_run, describe_run, execute_run
from .adapters import register_adapter, selection, select_for_review, rollback_selection
from .runtime import (status as runtime_status, activate as activate_runtime,
                      rollback as rollback_runtime, checked_active_tag,
                      inspect_rollback_readiness, rehearse_rollback)
from .ollama_import import prepare_import, verify_import, import_local
from .model_lineage import inspect_model_lineage
from .conversion import (prepare_conversion, execute_conversion,
                         pause_conversion, conversion_status)


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
    x = sub.add_parser('inspect-heldout', help='Check aggregate held-out case counts and split overlap without inference')
    x.add_argument('--split', choices=['calibration', 'test'], default='calibration')
    x.add_argument('--limit', type=int, default=100)
    x.add_argument('--min-cases', type=int, default=10)
    x.add_argument('--seed', type=int, default=42)
    x = sub.add_parser('learning-plan', help='Inspect a complete reviewed learning cycle offline, without inference or training')
    x.add_argument('--split', choices=['calibration', 'test'], default='calibration')
    x.add_argument('--limit', type=int, default=100)
    x.add_argument('--min-cases', type=int, default=10)
    x.add_argument('--seed', type=int, default=42)
    x.add_argument('--dataset-sha256', default=None, help='Optional previously exported local reviewed dataset fingerprint')
    x = sub.add_parser('session-start', help='Record an owner-confirmed offline learning experiment (no training)')
    x.add_argument('dataset_sha256')
    x.add_argument('--split', choices=['calibration', 'test'], default='calibration')
    x.add_argument('--limit', type=int, default=100)
    x.add_argument('--min-cases', type=int, default=10)
    x.add_argument('--seed', type=int, default=42)
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('session-baseline', help='Explicitly measure and pin pretraining held-out baseline (local inference)')
    x.add_argument('session_id')
    x.add_argument('--model', required=True, help='Existing installed baseline Ollama tag')
    x.add_argument('--revision', type=int, required=True)
    x.add_argument('--confirm', action='store_true', help='Explicit permission to send held-out prompts to local Ollama')
    x = sub.add_parser('session-status', help='Revalidate private experiment evidence without model calls')
    x.add_argument('session_id')
    x = sub.add_parser('session-link-run', help='Record a separately completed and registered QLoRA adapter')
    x.add_argument('session_id')
    x.add_argument('run_id')
    x.add_argument('--revision', type=int, required=True)
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('session-link-report', help='Record an already saved local comparison (even if worse)')
    x.add_argument('session_id')
    x.add_argument('report_sha256')
    x.add_argument('--revision', type=int, required=True)
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('session-close', help='Seal an evaluated session as an observation; does NOT deploy')
    x.add_argument('session_id')
    x.add_argument('--revision', type=int, required=True)
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('session-cancel', help='Cancel a pending session without touching model routing')
    x.add_argument('session_id')
    x.add_argument('--revision', type=int, required=True)
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('compare', help='Compare two local models on the SAME held-out decision cases')
    x.add_argument('sha256', help='Previously approved private dataset hash')
    x.add_argument('--baseline', required=True)
    x.add_argument('--candidate', required=True)
    x.add_argument('--split', choices=['calibration', 'test'], default='calibration')
    x.add_argument('--limit', type=int, default=100)
    x.add_argument('--min-cases', type=int, default=10)
    x.add_argument('--seed', type=int, default=42)
    x.add_argument('--session', help='Optional schema-three session ID; binds exact per-case baseline outcomes')
    x.add_argument('--revision', type=int, help='Required current revision with --session')
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
    sub.add_parser('runtime-status', help='Show current AthenZ Ollama tag routing (no Ollama mutation)')
    x = sub.add_parser('runtime-rollback-readiness', help='Read-only rollback status; optional loopback inventory check')
    x.add_argument('--check-ollama', action='store_true',
                   help='Read existing pinned baseline digest from local Ollama; no inference or routing change')
    x = sub.add_parser('runtime-activate', help='Route to a reviewed locally imported model, or explicitly acknowledge legacy lineage')
    x.add_argument('--baseline', required=True, help='Evaluated, locally installed baseline tag')
    x.add_argument('--revision', type=int, required=True)
    x.add_argument('--ack-legacy-lineage', action='store_true',
                   help='Explicit owner acknowledgment ONLY when no AthenZ GGUF import record exists')
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('runtime-rehearse-rollback',
                       help='Consent-gated local baseline smoke and temporary SQLite rollback, never persists routing change')
    x.add_argument('--revision', type=int, required=True)
    x.add_argument('--confirm', action='store_true',
                   help='Explicitly authorize one synthetic prompt to the installed baseline via loopback Ollama')
    x = sub.add_parser('runtime-rollback', help='Restore the pinned baseline as AthenZ chat default')
    x.add_argument('--revision', type=int, required=True)
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('prepare-conversion', help='Freeze adapter merge and trusted local llama.cpp converter fingerprint')
    x.add_argument('run_id')
    x.add_argument('--converter', type=Path, required=True, help='Trusted local convert_hf_to_gguf.py path')
    x.add_argument('--sha256', required=True, help='SHA-256 of the exact trusted converter script')
    x.add_argument('--trust-converter', action='store_true', help='I reviewed/trust this local Python script and packages')
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('run-conversion', help='Merge LoRA into HF and convert to GGUF on this PC; no Ollama mutation')
    x.add_argument('run_id')
    x.add_argument('--resume', action='store_true', help='Start a new private attempt after interrupted/failed run')
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('pause-conversion', help='Revoke an in-flight or queued conversion checkpoint; CPU process may still run')
    x.add_argument('run_id')
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('verify-conversion', help='Revalidate approved inputs, converter and complete GGUF artifact')
    x.add_argument('run_id')
    x = sub.add_parser('prepare-import', help='Prepare a full merged GGUF model import; NO Ollama change')
    x.add_argument('run_id')
    x.add_argument('gguf', type=Path)
    x.add_argument('--candidate', required=True, help='Registered candidate tag: athenz/name:tag')
    x.add_argument('--ack-merge', action='store_true', help='I independently merged the exact approved adapter and base')
    x.add_argument('--confirm', action='store_true')
    x = sub.add_parser('lineage-audit',
                       help='Read-only private evidence chain; optional Ollama inventory, never inference')
    x.add_argument('run_id')
    x.add_argument('--check-ollama', action='store_true',
                   help='Verify candidate tag digest using fixed local loopback inventory')
    x = sub.add_parser('verify-import', help='Verify private GGUF/adapter lineage and optional Ollama tag')
    x.add_argument('run_id')
    x.add_argument('--check-ollama', action='store_true')
    x = sub.add_parser('import-local', help='Explicitly create a fresh LOCAL Ollama tag from complete GGUF')
    x.add_argument('run_id')
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
        elif args.command == 'inspect-heldout':
            result = inspect_heldout_readiness(
                store, split=args.split, limit=args.limit,
                min_cases=args.min_cases, seed=args.seed)
        elif args.command == 'learning-plan':
            result = inspect_learning_cycle(
                store, split=args.split, limit=args.limit,
                min_cases=args.min_cases, seed=args.seed,
                dataset_sha256=args.dataset_sha256)
        elif args.command == 'session-start':
            result = start_session(
                store, args.dataset_sha256, split=args.split, limit=args.limit,
                min_cases=args.min_cases, seed=args.seed, confirmed=args.confirm)
        elif args.command == 'session-baseline':
            if not args.confirm:
                raise ValueError('--confirm required before local baseline inference')
            result = record_baseline(
                store, args.session_id, OllamaClient(model=args.model),
                expected_revision=args.revision, confirmed=True)
        elif args.command == 'session-status':
            result = session_status(store, args.session_id)
        elif args.command == 'session-link-run':
            result = link_completed_run(
                store, args.session_id, args.run_id,
                expected_revision=args.revision, confirmed=args.confirm)
        elif args.command == 'session-link-report':
            result = link_comparison(
                store, args.session_id, args.report_sha256,
                expected_revision=args.revision, confirmed=args.confirm)
        elif args.command == 'session-close':
            result = close_session(
                store, args.session_id, expected_revision=args.revision,
                confirmed=args.confirm)
        elif args.command == 'session-cancel':
            result = cancel_session(
                store, args.session_id, expected_revision=args.revision,
                confirmed=args.confirm)
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
        elif args.command == 'runtime-status':
            result = runtime_status(store)
        elif args.command == 'runtime-rollback-readiness':
            result = inspect_rollback_readiness(store, check_ollama=args.check_ollama)
        elif args.command == 'runtime-activate':
            result = activate_runtime(
                store, expected_revision=args.revision,
                baseline_tag=args.baseline, confirmed=args.confirm,
                ack_legacy_lineage=args.ack_legacy_lineage)
        elif args.command == 'runtime-rehearse-rollback':
            result = rehearse_rollback(
                store, expected_revision=args.revision, confirmed=args.confirm)
        elif args.command == 'runtime-rollback':
            result = rollback_runtime(store, expected_revision=args.revision,
                                      confirmed=args.confirm)
        elif args.command == 'prepare-conversion':
            result = prepare_conversion(store, args.run_id, args.converter,
                                        converter_sha256=args.sha256, confirmed=args.confirm,
                                        trust_converter=args.trust_converter)
        elif args.command == 'run-conversion':
            result = execute_conversion(store, args.run_id, confirmed=args.confirm,
                                        resume=args.resume)
        elif args.command == 'verify-conversion':
            result = conversion_status(store, args.run_id)
        elif args.command == 'pause-conversion':
            result = pause_conversion(store, args.run_id, confirmed=args.confirm)
        elif args.command == 'prepare-import':
            result = prepare_import(store, args.run_id, args.gguf, candidate_tag=args.candidate,
                                    confirmed=args.confirm, acknowledge_merge=args.ack_merge)
        elif args.command == 'lineage-audit':
            result = inspect_model_lineage(
                store, args.run_id, check_ollama=args.check_ollama)
        elif args.command == 'verify-import':
            result = verify_import(store, args.run_id, verify_ollama=args.check_ollama)
        elif args.command == 'import-local':
            result = import_local(store, args.run_id, confirmed=args.confirm)
        elif args.command == 'rollback-adapter':
            result = rollback_selection(store, expected_revision=args.revision,
                                        confirmed=args.confirm)
        elif args.command == 'compare':
            if not args.confirm:
                raise ValueError('--confirm required before running local model benchmarks')
            if args.session is None and args.revision is not None:
                raise ValueError('--revision may only be used with --session')
            key, expected = (None, None)
            if args.session is not None:
                key, expected = session_comparison_context(
                    store, args.session, expected_revision=args.revision,
                    baseline=args.baseline, candidate=args.candidate,
                    dataset_sha256=args.sha256, split=args.split,
                    limit=args.limit, seed=args.seed)
            try:
                report = compare_models(
                    store, OllamaClient(model=args.baseline),
                    OllamaClient(model=args.candidate), args.sha256,
                    split=args.split, limit=args.limit, seed=args.seed,
                    min_cases=args.min_cases, baseline_outcome_key=key)
            except Exception:
                if args.session is not None:
                    # Private local backend errors may contain held-out text.
                    raise LearningSessionError(
                        'Session comparison inference failed; check local evidence') from None
                raise
            if args.session is not None:
                # Recheck revisions and consent after potentially long inference
                # and before writing any report to the private filesystem.
                new_key, latest = session_comparison_context(
                    store, args.session, expected_revision=args.revision,
                    baseline=args.baseline, candidate=args.candidate,
                    dataset_sha256=args.sha256, split=args.split,
                    limit=args.limit, seed=args.seed)
                if (new_key != key or latest != expected
                        or report.get('baseline_outcome_sha256') != expected):
                    raise LearningSessionError(
                        'Baseline predictions changed; comparison not saved')
            result = {**report, 'report': save_report(store, report, confirmed=True)}
        else:
            result = {'deleted': delete_dataset(store, args.sha256, confirmed=args.confirm)}
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        store.close()


if __name__ == '__main__':
    main()
