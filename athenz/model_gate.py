"""Manual-review gate for model candidate evaluation; never trains or deploys.

Runs both models through the same held-out decision evaluator, revalidates the
owner-approved private training snapshot, and stores aggregate-only evidence.
Local observed scores are not independent/cryptographic attestations.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .evaluation import evaluate_decisions
from .experience import ExperienceStore
from .training import DatasetError, _private_root, _write_new, verify_dataset


class BenchmarkError(ValueError):
    """Model comparison failed validation or lacked adequate held-out evidence."""


def _heldout_fingerprint(store: ExperienceStore, split: str, limit: int) -> str:
    """Capture question, choices, rationale-free gold and options before inference."""
    rows = [list(r) for r in store.db.execute(
        "SELECT id,scenario,choice,options_json FROM decisions "
        "WHERE status='approved' AND split=? ORDER BY id LIMIT ?", (split, limit))]
    payload = json.dumps(rows, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


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
    first = evaluate_decisions(store, baseline_model, split=split, limit=limit, seed=seed)
    if model_digest(baseline) != initial_baseline_digest:
        raise BenchmarkError('Baseline model digest changed during evaluation')
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
    # Do not embed scenarios, gold answers or model predictions in the report.
    result = {'schema': 1, 'dataset_sha256': dataset_sha256, 'split': split,
              'seed': seed, 'cases': len(ids_a),
              'case_ids_sha256': hashlib.sha256(json.dumps(ids_a).encode()).hexdigest(),
              'heldout_fingerprint': initial_cases_sha,
              'baseline': baseline, 'candidate': candidate,
              'baseline_digest': initial_baseline_digest,
              'candidate_digest': initial_candidate_digest,
              'baseline_correct': first['correct'], 'candidate_correct': second['correct'],
              'baseline_accuracy': first['accuracy'], 'candidate_accuracy': second['accuracy'],
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
