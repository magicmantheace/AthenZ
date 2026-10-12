"""Manual-review gate for model candidate evaluation; never trains or deploys.

Runs both models through the same held-out decision evaluator, revalidates the
owner-approved private training snapshot, and stores aggregate-only evidence.
Local observed scores are not independent/cryptographic attestations.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .evaluation import evaluate_decisions, _fingerprint, _heldout_rows, _reference_fingerprint
from .experience import ExperienceStore
from .training import DatasetError, _private_root, _write_new, verify_dataset


class BenchmarkError(ValueError):
    """Model comparison failed validation or lacked adequate held-out evidence."""


def _heldout_fingerprint(store: ExperienceStore, split: str, limit: int) -> str:
    """Bound held-out case content and provenance for approval-gate checks.

    Earlier pre-alpha reports that used choice-only fingerprints intentionally
    require fresh review after this format strengthens its evidence scope.
    """
    return _fingerprint(_heldout_rows(store, split, limit))


def compare_models(store: ExperienceStore, baseline_model, candidate_model,
                   dataset_sha256: str, *, split: str = 'calibration', limit: int = 100,
                   seed: int = 42, min_cases: int = 10) -> dict:
    """Evaluate only, without updating models or selection; return aggregate scores."""
    if split not in {'calibration', 'test'} or not 1 <= limit <= 1000 or not 2 <= min_cases <= limit:
        raise BenchmarkError('Select a valid held-out split, limit and minimum sample count')
    baseline = getattr(baseline_model, 'model', None)
    candidate = getattr(candidate_model, 'model', None)
    if (not isinstance(baseline, str) or not isinstance(candidate, str)
            or not baseline.strip() or not candidate.strip() or baseline == candidate):
        raise BenchmarkError('Select two distinct, explicitly named local models')
    from .runtime import model_digest
    initial_baseline_digest = model_digest(baseline)
    initial_candidate_digest = model_digest(candidate)
    if initial_baseline_digest == initial_candidate_digest:
        raise BenchmarkError('Baseline and candidate have identical installed model digests')
    verify_dataset(store, dataset_sha256)
    initial_cases_sha = _heldout_fingerprint(store, split, limit)
    initial_reference_sha = _reference_fingerprint(store)
    first = evaluate_decisions(store, baseline_model, split=split, limit=limit, seed=seed)
    if model_digest(baseline) != initial_baseline_digest:
        raise BenchmarkError('Baseline model digest changed during evaluation')
    if _reference_fingerprint(store) != initial_reference_sha:
        raise BenchmarkError('Approved reference evidence changed while comparing models')
    second = evaluate_decisions(store, candidate_model, split=split, limit=limit, seed=seed)
    if (model_digest(baseline) != initial_baseline_digest or
            model_digest(candidate) != initial_candidate_digest):
        raise BenchmarkError('Installed model digest changed during evaluation')
    ids_a = [c['id'] for c in first['cases']]
    ids_b = [c['id'] for c in second['cases']]
    if (ids_a != ids_b or len(ids_a) < min_cases or len(set(ids_a)) != len(ids_a)
            or any(a['expected'] != b['expected'] for a, b in zip(first['cases'], second['cases']))):
        raise BenchmarkError('Insufficient, unequal or changed held-out evaluation cases')
    # Source approvals can be revoked while local inference is running.
    verify_dataset(store, dataset_sha256)
    current_ids = [r['id'] for r in store.db.execute(
        'SELECT id FROM decisions WHERE status=? AND split=? ORDER BY id LIMIT ?',
        ('approved', split, limit)).fetchall()]
    if ids_a != current_ids or _heldout_fingerprint(store, split, limit) != initial_cases_sha:
        raise BenchmarkError('Evaluation decisions changed while comparing models')
    if _reference_fingerprint(store) != initial_reference_sha:
        raise BenchmarkError('Approved reference evidence changed while comparing models')
    # Reject mismatched evidence snapshots even when model scores look plausible.
    # Both evaluation reports must be tied to this same private reference set.
    if (first.get('heldout_sha256') != initial_cases_sha or
            second.get('heldout_sha256') != initial_cases_sha or
            first.get('reference_sha256') != initial_reference_sha or
            second.get('reference_sha256') != initial_reference_sha):
        raise BenchmarkError('Evaluations used unequal or stale evidence snapshots')
    # Do not embed scenarios, gold answers or model predictions in the report.
    result = {'schema': 1, 'dataset_sha256': dataset_sha256, 'split': split,
              'seed': seed, 'cases': len(ids_a),
              'case_ids_sha256': hashlib.sha256(json.dumps(ids_a).encode()).hexdigest(),
              'heldout_fingerprint': initial_cases_sha,
              'reference_fingerprint': initial_reference_sha,
              'baseline': baseline, 'candidate': candidate,
              'baseline_digest': initial_baseline_digest,
              'candidate_digest': initial_candidate_digest,
              'baseline_correct': first['correct'], 'candidate_correct': second['correct'],
              'baseline_accuracy': first['accuracy'], 'candidate_accuracy': second['accuracy'],
              'baseline_accuracy_interval_95': first.get('accuracy_interval_95'),
              'candidate_accuracy_interval_95': second.get('accuracy_interval_95'),
              'baseline_invalid_predictions': first.get('invalid_predictions'),
              'candidate_invalid_predictions': second.get('invalid_predictions'),
              'accuracy_gain': round(second['accuracy'] - first['accuracy'], 8),
              'chance_expected': first['chance_expected'],
              'eligible_for_review': second['correct'] > first['correct'],
              'attestation': 'local-model-observation-only',
              'promotion': 'not-authorized'}
    return result


def save_report(store: ExperienceStore, comparison: dict, *, confirmed: bool = False) -> dict:
    """Save aggregate scores into a private, immutable report for human review."""
    if not confirmed:
        raise BenchmarkError('Explicit --confirm required for local evaluation record')
    sha = comparison.get('dataset_sha256')
    if not isinstance(sha, str):
        raise BenchmarkError('Missing dataset SHA')
    verify_dataset(store, sha)
    if comparison.get('promotion') != 'not-authorized' or comparison.get('attestation') != 'local-model-observation-only':
        raise BenchmarkError('Only non-deploying observed benchmarks can be stored')
    # The comparison is an earlier observation. Consent or model evidence may
    # change between evaluation and its owner-confirmed disk persistence.
    split, count = comparison.get('split'), comparison.get('cases')
    if (split not in {'calibration', 'test'} or type(count) is not int
            or not 2 <= count <= 1000):
        raise BenchmarkError('Invalid held-out comparison scope')
    if (comparison.get('heldout_fingerprint') != _heldout_fingerprint(store, split, count)
            or comparison.get('reference_fingerprint') != _reference_fingerprint(store)):
        raise BenchmarkError('Evaluation evidence changed before saving; rerun comparison')
    root = _private_root(store) / 'evaluations'
    if root.is_symlink():
        raise DatasetError('Private evaluation directory may not be a symlink')
    root.mkdir(mode=0o700, exist_ok=True)
    if root.resolve() != root:
        raise DatasetError('Unsafe evaluation directory')
    payload = (json.dumps(comparison, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    fingerprint = hashlib.sha256(payload).hexdigest()
    target = root / f'eval-{fingerprint}.json'
    if target.is_symlink():
        raise BenchmarkError('Refusing symlinked evaluation artifact')
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != fingerprint:
            raise BenchmarkError('Existing immutable report has changed')
    else:
        _write_new(target, payload)
    return {'path': str(target), 'sha256': fingerprint, 'eligible_for_review': comparison['eligible_for_review']}
