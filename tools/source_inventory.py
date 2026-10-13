"""Offline completeness preflight for the AthenZ source baseline.

This is an intentionally path-only inventory taken from the reviewed archival
source tree at 550eee10f3a0f9d530cb9424ba6b7ed18e5516c4. A complete path
set is needed before a local *full suite* or wheel can be called meaningful.
It does not verify file contents, trust, or freshness. New development files
are allowed; an edited tracked file is not incorrectly called a missing file.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

BASELINE = '550eee10f3a0f9d530cb9424ba6b7ed18e5516c4'
# Source/test inventory at the above non-triggering GitHub archive checkpoint.
# No private files, datasets, models, SQLite databases or external downloads.
REQUIRED = tuple('''
pyproject.toml
athenz/__init__.py athenz/__main__.py athenz/adapters.py athenz/backup.py
athenz/chat.py athenz/cli.py athenz/coding.py athenz/controller.py
athenz/controller_cli.py athenz/conversion.py athenz/desktop.py
athenz/desktop_shortcuts.py athenz/desktop_tasks.py athenz/desktop_zoom.py
athenz/evaluation.py athenz/experience.py athenz/finetune.py athenz/hardware.py
athenz/importers.py athenz/learning.py athenz/migrations.py
athenz/model_gate.py athenz/ollama_import.py athenz/onboarding.py
athenz/portable_integrity.py athenz/portable_stage.py athenz/preflight.py
athenz/profile_bundle.py athenz/prompting.py athenz/publishing.py
athenz/release_readiness.py athenz/runtime.py athenz/schedule_cli.py
athenz/scheduler.py athenz/sequence_cli.py athenz/sequencer.py
athenz/store.py athenz/task_panel.py athenz/train_cli.py athenz/training.py
athenz/verification.py athenz/work_cli.py athenz/worker.py
packaging/desktop_launcher.py
tests/test_adapters.py tests/test_backup.py tests/test_backup_restore.py
tests/test_chat.py tests/test_ci_budget.py tests/test_coding.py
tests/test_conflicts_artifacts.py tests/test_controller.py
tests/test_conversion.py tests/test_desktop.py tests/test_desktop_bootstrap.py
tests/test_desktop_readiness.py tests/test_desktop_shortcuts.py
tests/test_desktop_tasks.py tests/test_desktop_zoom.py
tests/test_docker_integration.py tests/test_evaluation.py
tests/test_experience.py tests/test_finetune.py tests/test_gui_smoke_cli.py
tests/test_hardware.py tests/test_identity.py tests/test_learning.py
tests/test_line_endings.py tests/test_local_validation.py
tests/test_model_gate.py tests/test_ollama_import.py tests/test_onboarding.py
tests/test_portable_integrity.py tests/test_portable_stage.py
tests/test_preflight.py tests/test_profile_bundle.py tests/test_prompting.py
tests/test_publishing.py tests/test_release_readiness.py tests/test_runtime.py
tests/test_sandbox_threats.py tests/test_scheduler.py
tests/test_sequencer.py tests/test_training.py tests/test_verification.py
tests/test_worker.py
tools/__init__.py tools/ci_budget.py tools/local_validation.py
athenz/chat_cancel.py
athenz/conflict_panel.py
athenz/conflict_review.py
athenz/inference_readiness.py
athenz/profile_health.py
athenz/profile_setup.py
athenz/recovery_drill.py
athenz/voice.py tests/test_voice.py
tests/test_chat_cancel.py
tests/test_chat_safety.py
tests/test_conflict_panel.py
tests/test_conflict_review.py
tests/test_desktop_shutdown.py
tests/test_inference_readiness.py
tests/test_private_home_guards.py
tests/test_profile_health.py
tests/test_profile_setup.py
tests/test_recovery_drill.py
tests/test_source_inventory.py
tools/source_inventory.py
'''.split())


class InventoryError(ValueError):
    """Local source is incomplete or uses untrusted file types."""


def inspect_sources(root: Path) -> dict:
    """Inspect only local known paths, without invoking Git, network or tests."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise InventoryError('Source root is not a real directory')
    missing: list[str] = []
    unsafe: list[str] = []
    for rel in REQUIRED:
        target = root / rel
        if not target.exists():
            missing.append(rel)
        elif not target.is_file() or any(p.is_symlink() for p in (target, *target.parents) if p != root):
            # Do not allow symlink paths even when resolved content is a regular file.
            unsafe.append(rel)
    return {'schema': 1, 'baseline_commit': BASELINE,
            'expected_files': len(REQUIRED), 'missing': sorted(missing),
            'unsafe': sorted(unsafe), 'complete': not missing and not unsafe,
            'content_verified': False, 'current_remote_verified': False,
            'network_accessed': False, 'github_actions_invoked': False}


def check_complete(root: Path) -> dict:
    """Fail before a misleading full-suite or wheel claim on partial sources."""
    report = inspect_sources(root)
    if not report['complete']:
        count = len(report['missing']) + len(report['unsafe'])
        examples = ', '.join((report['missing'] + report['unsafe'])[:5])
        raise InventoryError(f'Incomplete or unsafe AthenZ source checkout: {count} path(s); {examples}')
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Check local AthenZ source completeness (no network)')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    result = inspect_sources(args.root)
    print(json.dumps(result, indent=2))
    if not result['complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
