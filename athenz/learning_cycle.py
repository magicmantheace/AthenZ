"""Offline, privacy-preserving readiness for an owner-approved learning cycle.

No model, GPU, subprocess, training, network, or deployment action is started.
This inspects existing approved local sources and optionally validates an
already exported private SFT snapshot. It never returns training/held-out text,
source IDs, prompts, model labels, paths, or case-level predictions.
"""
from __future__ import annotations

import hashlib
import re

from .evaluation import _fingerprint, _heldout_rows, _reference_fingerprint
from .experience import ExperienceStore
from .model_gate import inspect_heldout_readiness
from .training import (DatasetError, _read_approved, _render, verify_dataset)


class LearningCycleError(ValueError):
    """Invalid, non-authorizing local learning-cycle inspection."""


def _review_snapshot(store: ExperienceStore, split: str, limit: int) -> tuple:
    """Fingerprint private selected records in memory; return only digests."""
    pairs, stats = _read_approved(store)
    # Don't materialize one giant JSONL blob merely to inspect a large
    # approved dataset. Hash one bounded source row at a time instead.
    digest = hashlib.sha256()
    for row in pairs:
        digest.update(_render([row]))
    return (digest.hexdigest(),
            tuple(row[0] for row in pairs),
            stats,
            _fingerprint(_heldout_rows(store, split, limit)),
            _reference_fingerprint(store))


def inspect_learning_cycle(store: ExperienceStore, *,
                           split: str = 'calibration', limit: int = 100,
                           min_cases: int = 10, seed: int = 42,
                           dataset_sha256: str | None = None) -> dict:
    """Inspect the next manual learning experiment without changing any model.

    The dataset is never exported here. When an existing SHA is supplied,
    an absent/malformed/stale snapshot is reported as an aggregate blocker,
    rather than creating one or disclosing an owner-specific error.
    """
    if (split not in {'calibration', 'test'} or type(limit) is not int
            or type(min_cases) is not int or not 2 <= min_cases <= limit <= 1000
            or type(seed) is not int or not 0 <= seed < 2**32):
        raise LearningCycleError('Invalid bounded held-out learning-cycle settings')
    if dataset_sha256 is not None and (
            type(dataset_sha256) is not str or
            re.fullmatch(r'[a-f0-9]{64}', dataset_sha256) is None):
        raise LearningCycleError('Dataset SHA must be 64 lowercase hex characters')

    # The held-out preflight validates bounded split/seed/case settings. No
    # private data or model request is returned from that existing gate.
    before = _review_snapshot(store, split, limit)
    heldout = inspect_heldout_readiness(
        store, split=split, limit=limit, min_cases=min_cases, seed=seed)
    snapshot_state = 'not-selected'
    snapshot_verified = False
    if dataset_sha256 is not None:
        # verify_dataset uses its private datasets-directory helper; don't
        # allow this read-only inspection to create a missing directory.
        dataset_dir = store.home / 'datasets'
        if not dataset_dir.is_dir() or dataset_dir.is_symlink():
            snapshot_state = 'missing-or-stale'
        else:
            try:
                evidence = verify_dataset(store, dataset_sha256)
                snapshot_verified = (evidence['valid'] is True and
                                     evidence['sha256'] == dataset_sha256)
                snapshot_state = 'verified' if snapshot_verified else 'missing-or-stale'
            except (DatasetError, ValueError, OSError, UnicodeError, TypeError, KeyError):
                snapshot_state = 'missing-or-stale'
    after = _review_snapshot(store, split, limit)
    stable = before == after and heldout['evidence_snapshot_stable']
    stats = after[2]
    training_eligible = stats['included'] > 0 and stats['conflicts'] == 0
    heldout_eligible = heldout['ready_for_owner_review']
    can_compare = training_eligible and heldout_eligible and snapshot_verified and stable

    if not stable:
        next_step = 'repeat-preflight-after-source-changes'
    elif stats['conflicts']:
        next_step = 'resolve-reviewed-training-conflicts'
    elif not stats['included']:
        next_step = 'approve-distinct-training-examples'
    elif not heldout_eligible:
        next_step = 'review-heldout-evaluation-cases'
    elif dataset_sha256 is None:
        next_step = 'export-reviewed-dataset-with-explicit-confirmation'
    elif not snapshot_verified:
        next_step = 'repair-or-rebuild-reviewed-dataset'
    else:
        next_step = 'owner-may-compare-installed-local-models'

    return {
        'schema': 1, 'type': 'offline-learning-cycle-preflight',
        'split': split, 'limit': limit, 'seed': seed,
        'training': {key: stats[key] for key in (
            'approved', 'included', 'duplicates', 'heldout_excluded', 'conflicts')},
        'heldout': {
            'approved_cases': heldout['approved_cases'],
            'selected_cases': heldout['selected_cases'],
            'minimum_cases': min_cases,
            'minimum_cases_met': heldout['minimum_cases_met'],
            'split_independence_check': heldout['split_independence_check'],
            'selected_cases_independent': heldout['selected_cases_independent'],
            'heldout_options_valid': heldout['heldout_options_valid'],
            'reference_profile_clean': heldout['reference_profile_clean'],
            'ready_for_owner_review': heldout_eligible,
        },
        'dataset_snapshot': snapshot_state,
        'dataset_verified': snapshot_verified,
        'source_snapshot_stable': stable,
        'training_sources_eligible': training_eligible,
        'ready_for_manual_model_comparison': can_compare,
        'next_step': next_step,
        'model_called': False, 'training_started': False,
        'model_selected': False, 'promotion_authorized': False,
        'private_text_returned': False,
        'independent_model_quality_attested': False,
    }
