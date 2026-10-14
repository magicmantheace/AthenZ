"""Manual-review gate for model candidate evaluation; never trains or deploys.

Runs both models through the same held-out decision evaluator, revalidates the
owner-approved private training snapshot, and stores aggregate-only evidence.
Local observed scores are not independent/cryptographic attestations.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from math import comb, isfinite
from pathlib import Path

from .evaluation import (evaluate_decisions, _fingerprint, _heldout_rows,
                         _reference_fingerprint, _reject_overlapping_decision_splits,
                         _wilson_interval, _heldout_prompt_messages,
                         _reject_repeated_heldout_scenarios)
from .experience import ExperienceStore
from .training import DatasetError, _private_root, _write_new, verify_dataset


class BenchmarkError(ValueError):
    """Model comparison failed validation or lacked adequate held-out evidence."""


def _validated_case_outcomes(report: dict) -> list[dict]:
    """Check that observed aggregate scores match actual case-level results.

    Predictions stay private/in-memory. Only aggregates enter saved reports.
    This cannot authenticate model outputs; it prevents accidental arithmetic
    errors or mismatched evaluator metadata from being treated as improvements.
    """
    cases = report.get('cases')
    count, correct = report.get('total'), report.get('correct')
    accuracy = report.get('accuracy')
    if (not isinstance(cases, list) or type(count) is not int
            or type(correct) is not int or count != len(cases)
            or not 0 < count <= 1000 or not 0 <= correct <= count
            or type(accuracy) not in (int, float) or not isfinite(accuracy)
            or abs(accuracy - correct / count) > 1e-9):
        raise BenchmarkError('Evaluation aggregate accuracy disagrees with case evidence')
    chance = report.get('chance_expected')
    if (type(chance) not in (int, float) or not isfinite(chance)
            or not 0 < chance <= 0.5):
        raise BenchmarkError('Evaluation chance baseline is missing or invalid')
    invalid = 0
    true_correct = 0
    for case in cases:
        if not isinstance(case, dict):
            raise BenchmarkError('Invalid evaluation case evidence')
        gold, predicted, success = (case.get('expected'),
                                    case.get('predicted'), case.get('correct'))
        if (type(case.get('id')) is not int or not isinstance(gold, str)
                or len(gold) != 1 or gold not in 'ABCDEF'
                or (predicted is not None and
                    (not isinstance(predicted, str) or
                     len(predicted) != 1 or predicted not in 'ABCDEF'))
                or type(success) is not bool or success != (predicted == gold)):
            raise BenchmarkError('Invalid evaluation case evidence')
        invalid += int(predicted is None)
        true_correct += int(success)
    if true_correct != correct:
        raise BenchmarkError('Evaluation aggregate accuracy disagrees with case evidence')
    reported_invalid = report.get('invalid_predictions')
    if reported_invalid is not None and (type(reported_invalid) is not int
                                         or reported_invalid != invalid):
        raise BenchmarkError('Evaluation invalid prediction count disagrees with cases')
    return cases


def _case_outcome_fingerprint(cases: list[dict], key: bytes) -> str:
    """Keyed fingerprint of exact ordered per-case predictions, not just score.

    HMAC prevents cheap brute-forcing of short A-F prediction sequences from
    a saved digest. The 256-bit key remains in the private session checkpoint,
    never in the report or CLI response. This is local consistency evidence,
    not a cryptographically signed model attestation.
    """
    if type(key) is not bytes or len(key) != 32:
        raise BenchmarkError('Invalid private outcome fingerprint key')
    h = hmac.new(key, b'athenz-prediction-sequence-v1\n', hashlib.sha256)
    for row in cases:
        if (type(row) is not dict or type(row.get('id')) is not int
                or type(row.get('correct')) is not bool
                or type(row.get('expected')) is not str
                or row['expected'] not in 'ABCDEF'
                or (row.get('predicted') is not None and
                    (type(row['predicted']) is not str
                     or row['predicted'] not in 'ABCDEF'))):
            raise BenchmarkError('Invalid per-case outcome evidence')
        item = [row['id'], row['predicted'], row['expected'], row['correct']]
        body = json.dumps(item, separators=(',', ':')).encode('ascii')
        h.update(len(body).to_bytes(4, 'big'))
        h.update(body)
    return h.hexdigest()


def _paired_one_sided_probability(improvements: int, regressions: int) -> float:
    """Exact paired sign-test tail under equal odds of improving/regressing."""
    n = improvements + regressions
    if not n:
        return 1.0
    return sum(comb(n, k) for k in range(improvements, n + 1)) / (1 << n)


def _consistent_comparison_metadata(report: dict) -> bool:
    """Validate self-consistency of optional aggregate comparison evidence.

    Legacy metadata-only reports predate per-model counts and are not
    independently attested by this function. Newly produced comparisons
    include all aggregate fields and are checked before persistence/review.
    """
    if type(report.get('schema')) is not int or report['schema'] not in (1, 2):
        return False
    count = report.get('cases')
    if type(count) is not int or not 0 < count <= 1000:
        return False
    # Current reports retain the requested sampling limit AND the full
    # approved population. A new out-of-window case must invalidate a saved
    # comparison rather than silently preserving stale approval evidence.
    population_fields = ('requested_case_limit', 'approved_split_total',
                         'approved_split_sha256')
    present_population = [field in report for field in population_fields]
    if report['schema'] == 2 and not all(present_population):
        return False
    if any(present_population):
        if not all(present_population):
            return False
        requested, total = (report['requested_case_limit'],
                            report['approved_split_total'])
        population_sha = report.get('approved_split_sha256')
        if (type(requested) is not int or type(total) is not int
                or not 1 <= requested <= 1000 or total < 1
                or count != min(requested, total)):
            return False
        if (report['schema'] == 2 and
                (type(population_sha) is not str or len(population_sha) != 64
                 or any(c not in '0123456789abcdef' for c in population_sha))):
            return False
    outcome = report.get('baseline_outcome_sha256')
    if outcome is not None and (type(outcome) is not str or len(outcome) != 64
                                or any(c not in '0123456789abcdef' for c in outcome)):
        return False
    chance = report.get('chance_expected')
    if chance is not None and (type(chance) not in (int, float) or
                               not isfinite(chance) or not 0 < chance <= 0.5):
        return False
    names = ('baseline_correct', 'candidate_correct', 'baseline_accuracy',
             'candidate_accuracy')
    present = [key in report for key in names]
    digests = ('baseline_digest', 'candidate_digest')
    if any(key in report for key in digests):
        if not all(key in report for key in digests):
            return False
        values = [report[key] for key in digests]
        if (any(not isinstance(value, str) or len(value) != 64 or
                any(letter not in '0123456789abcdef' for letter in value)
                for value in values) or values[0] == values[1]):
            return False
    if report['schema'] == 2:
        if not all(present) or not all(key in report for key in digests):
            return False
        if not all(key in report for key in (
                'paired_improved', 'paired_regressed', 'paired_unchanged',
                'paired_one_sided_p_value')):
            return False
    if not any(present):
        # Historical schema 1 owner-reviewed reports omitted these statistics.
        return not any(key in report for key in (
            'paired_improved', 'paired_regressed', 'paired_unchanged',
            'paired_one_sided_p_value'))
    if not all(present):
        return False
    baseline, candidate = report['baseline_correct'], report['candidate_correct']
    base_rate, candidate_rate = report['baseline_accuracy'], report['candidate_accuracy']
    gain = report.get('accuracy_gain')
    if (type(baseline) is not int or type(candidate) is not int or
            not 0 <= baseline <= count or not 0 <= candidate <= count or
            type(base_rate) not in (int, float) or
            type(candidate_rate) not in (int, float) or
            not isfinite(base_rate) or not isfinite(candidate_rate) or
            abs(base_rate - baseline / count) > 1e-9 or
            abs(candidate_rate - candidate / count) > 1e-9 or
            type(gain) not in (int, float) or not isfinite(gain) or
            abs(gain - round((candidate - baseline) / count, 8)) > 1e-8 or
            report.get('eligible_for_review') is not (candidate > baseline)):
        return False
    for name, correct_count in (('baseline', baseline), ('candidate', candidate)):
        # These fields are descriptive only but must never misstate observed
        # failure counts or present a fabricated uncertainty interval.
        invalid = report.get(name + '_invalid_predictions')
        if invalid is not None and (type(invalid) is not int or
                                    not 0 <= invalid <= count - correct_count):
            return False
        interval = report.get(name + '_accuracy_interval_95')
        if interval is not None:
            expected = _wilson_interval(correct_count, count)
            if (not isinstance(interval, list) or len(interval) != 2 or
                    any(type(v) not in (int, float) or not isfinite(v)
                        for v in interval) or
                    any(abs(actual - bound) > 1e-8
                        for actual, bound in zip(interval, expected))):
                return False
    paired = ('paired_improved', 'paired_regressed',
              'paired_unchanged', 'paired_one_sided_p_value')
    if any(name in report for name in paired):
        if not all(name in report for name in paired):
            return False
        improved, regressed, unchanged = [report[k] for k in paired[:3]]
        p = report['paired_one_sided_p_value']
        if (any(type(x) is not int or x < 0 for x in
                (improved, regressed, unchanged)) or
                improved + regressed + unchanged != count or
                improved - regressed != candidate - baseline or
                type(p) not in (int, float) or not isfinite(p) or
                not 0 <= p <= 1 or
                abs(p - round(_paired_one_sided_probability(
                    improved, regressed), 10)) > 1e-9):
            return False
    return True


def _approved_heldout_population(store: ExperienceStore, split: str) -> tuple[int, str]:
    """Fingerprint ALL approved cases, streaming content privately through SHA-256.

    A count by itself cannot detect changed source/answer/provenance outside
    the scored window. The digest is never a disclosure of the examples or an
    independently signed attestation. Length-prefix each JSON row to remove
    concatenation ambiguity, with a domain-specific header.
    """
    h = hashlib.sha256(b'athenz-approved-heldout-population-v1\n')
    total = 0
    for row in store.db.execute(
            'SELECT id,scenario,choice,options_json,rationale,exception,'
            'source,source_ref,created_at FROM decisions '
            "WHERE status='approved' AND split=? ORDER BY id", (split,)):
        data = json.dumps(list(row), ensure_ascii=False,
                          separators=(',', ':')).encode('utf-8')
        h.update(len(data).to_bytes(8, 'big'))
        h.update(data)
        total += 1
    return total, h.hexdigest()


def _heldout_fingerprint(store: ExperienceStore, split: str, limit: int) -> str:
    """Bound held-out case content and provenance for approval-gate checks.

    Earlier pre-alpha reports that used choice-only fingerprints intentionally
    require fresh review after this format strengthens its evidence scope.
    """
    return _fingerprint(_heldout_rows(store, split, limit))


def inspect_heldout_readiness(store: ExperienceStore, *, split: str = 'calibration',
                             limit: int = 100, min_cases: int = 10,
                             seed: int = 42) -> dict:
    """Private-text-free, read-only benchmark planning; no Ollama or training.

    This is a bounded preflight for selecting reviewed held-out cases, NOT a
    model readiness, dataset-consent, or benchmark-accuracy certification.
    """
    if (split not in {'calibration', 'test'} or type(limit) is not int or
            type(min_cases) is not int or not 2 <= min_cases <= limit <= 1000
            or type(seed) is not int or not 0 <= seed < 2**32):
        raise BenchmarkError('Select a valid held-out split, limit and minimum sample count')
    rows = _heldout_rows(store, split, limit)
    initial_cases_sha = _fingerprint(rows)
    initial_reference_sha = _reference_fingerprint(store)
    total = store.db.execute(
        "SELECT COUNT(*) FROM decisions WHERE status='approved' AND split=?",
        (split,)).fetchone()[0]
    try:
        _reject_overlapping_decision_splits(store)
        clean = True
    except ValueError:
        clean = False
    # Count independence is not merely a cross-split property: duplicate
    # calibration/test questions can inflate success and Wilson precision.
    try:
        _reject_repeated_heldout_scenarios(store, split, limit)
        independent = True
    except ValueError:
        independent = False
    # This report never exposes the scenario/answer/rationale/options. It
    # deliberately leaves actual semantic leakage and full model verification
    # for the protected evaluator at inference time.
    sufficient = len(rows) >= min_cases
    options_valid = True
    reference_profile_clean = True
    for row in rows:
        try:
            choices = json.loads(row[3])
        except (ValueError, TypeError):
            options_valid = False
            break
        if (not isinstance(choices, list) or not 2 <= len(choices) <= 6
                or any(not isinstance(choice, str) for choice in choices)
                or row[2] not in choices or
                len({choice.strip().casefold() for choice in choices}) != len(choices)):
            options_valid = False
            break
        try:
            _heldout_prompt_messages(store, row, seed)
        except ValueError:
            # Covers reference-profile collisions or changed prompt structure.
            # Neither offending private text nor any prompt reaches the report.
            reference_profile_clean = False
            break
    snapshot_stable = (_fingerprint(_heldout_rows(store, split, limit))
                       == initial_cases_sha and
                       _reference_fingerprint(store) == initial_reference_sha)
    return {'schema': 1, 'split': split, 'limit': limit, 'seed': seed,
            'minimum_cases': min_cases, 'approved_cases': total,
            'selected_cases': len(rows),
            'split_independence_check': 'lexical-pass' if clean else 'lexical-overlap',
            'selected_cases_independent': independent,
            'minimum_cases_met': sufficient,
            'heldout_options_valid': options_valid,
            'reference_profile_clean': reference_profile_clean,
            'evidence_snapshot_stable': snapshot_stable,
            'ready_for_owner_review': (clean and independent and sufficient
                                       and options_valid and reference_profile_clean
                                       and snapshot_stable),
            'model_called': False, 'dataset_verified': False,
            'private_text_returned': False, 'promotion': 'not-authorized'}


def compare_models(store: ExperienceStore, baseline_model, candidate_model,
                   dataset_sha256: str, *, split: str = 'calibration', limit: int = 100,
                   seed: int = 42, min_cases: int = 10,
                   baseline_outcome_key: bytes | None = None) -> dict:
    """Evaluate only; optionally bind baseline predictions to a private session key."""
    if (split not in {'calibration', 'test'} or type(limit) is not int
            or type(min_cases) is not int or type(seed) is not int
            or not 1 <= limit <= 1000 or not 2 <= min_cases <= limit
            or not 0 <= seed < 2**32):
        raise BenchmarkError('Select a valid held-out split, limit and minimum sample count')
    if baseline_outcome_key is not None and (
            type(baseline_outcome_key) is not bytes or len(baseline_outcome_key) != 32):
        raise BenchmarkError('Invalid private outcome fingerprint key')
    baseline = getattr(baseline_model, 'model', None)
    candidate = getattr(candidate_model, 'model', None)
    if (not isinstance(baseline, str) or not isinstance(candidate, str)
            or not baseline.strip() or not candidate.strip() or baseline == candidate):
        raise BenchmarkError('Select two distinct, explicitly named local models')
    # Refuse biased held-out samples before contacting local model services.
    _reject_overlapping_decision_splits(store)
    _reject_repeated_heldout_scenarios(store, split, limit)
    approved_total, approved_population_sha = _approved_heldout_population(store, split)
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
    baseline_cases = _validated_case_outcomes(first)
    candidate_cases = _validated_case_outcomes(second)
    if abs(first['chance_expected'] - second['chance_expected']) > 1e-9:
        raise BenchmarkError('Evaluation chance baselines disagree on held-out cases')
    improved = sum(not a['correct'] and b['correct']
                   for a, b in zip(baseline_cases, candidate_cases))
    regressed = sum(a['correct'] and not b['correct']
                    for a, b in zip(baseline_cases, candidate_cases))
    # Exact paired evidence is descriptive and never authorizes promotion.
    # Opposing predictions on cases both got wrong do not count as wins.
    paired_p = _paired_one_sided_probability(improved, regressed)

    # Source approvals can be revoked while local inference is running.
    verify_dataset(store, dataset_sha256)
    current_ids = [r['id'] for r in store.db.execute(
        'SELECT id FROM decisions WHERE status=? AND split=? ORDER BY id LIMIT ?',
        ('approved', split, limit)).fetchall()]
    if ids_a != current_ids or _heldout_fingerprint(store, split, limit) != initial_cases_sha:
        raise BenchmarkError('Evaluation decisions changed while comparing models')
    if _approved_heldout_population(store, split) != (
            approved_total, approved_population_sha):
        raise BenchmarkError('Held-out population changed during model comparison')
    _reject_overlapping_decision_splits(store)
    _reject_repeated_heldout_scenarios(store, split, limit)
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
    result = {'schema': 2, 'dataset_sha256': dataset_sha256, 'split': split,
              'seed': seed, 'cases': len(ids_a),
              'requested_case_limit': limit, 'approved_split_total': approved_total,
              'approved_split_sha256': approved_population_sha,
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
              'paired_improved': improved, 'paired_regressed': regressed,
              'paired_unchanged': len(ids_a) - improved - regressed,
              'paired_one_sided_p_value': round(paired_p, 10),
              'chance_expected': first['chance_expected'],
              'eligible_for_review': second['correct'] > first['correct'],
              'attestation': 'local-model-observation-only',
              'promotion': 'not-authorized'}
    if baseline_outcome_key is not None:
        result['baseline_outcome_sha256'] = _case_outcome_fingerprint(
            baseline_cases, baseline_outcome_key)
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
    gain = comparison.get('accuracy_gain')
    if type(gain) not in (int, float) or not isfinite(gain) or not -1 <= gain <= 1:
        raise BenchmarkError('Invalid observed accuracy gain')
    if not _consistent_comparison_metadata(comparison):
        raise BenchmarkError('Evaluation comparison metadata is inconsistent')
    # The comparison is an earlier observation. Consent or model evidence may
    # change between evaluation and its owner-confirmed disk persistence.
    split, count = comparison.get('split'), comparison.get('cases')
    if (split not in {'calibration', 'test'} or type(count) is not int
            or not 2 <= count <= 1000):
        raise BenchmarkError('Invalid held-out comparison scope')
    try:
        _reject_overlapping_decision_splits(store)
    except ValueError as exc:
        raise BenchmarkError('Evaluation partitions overlap; re-evaluation required') from exc
    try:
        _reject_repeated_heldout_scenarios(store, split, count)
    except ValueError as exc:
        raise BenchmarkError('Evaluation sample independence failed; re-evaluation required') from exc
    current_ids = [row[0] for row in store.db.execute(
        "SELECT id FROM decisions WHERE status='approved' AND split=? "
        "ORDER BY id LIMIT ?", (split, count))]
    expected_ids_sha = hashlib.sha256(json.dumps(current_ids).encode()).hexdigest()
    if len(current_ids) != count or comparison.get('case_ids_sha256') != expected_ids_sha:
        raise BenchmarkError('Evaluation held-out case identities changed before saving')
    if (comparison.get('heldout_fingerprint') != _heldout_fingerprint(store, split, count)
            or comparison.get('reference_fingerprint') != _reference_fingerprint(store)):
        raise BenchmarkError('Evaluation evidence changed before saving; rerun comparison')
    # Preserve precise legacy diagnostics for scored-case edits/duplicates.
    # The full-population check then also detects changes beyond the
    # originally evaluated window that the selected-case hash cannot see.
    if ('requested_case_limit' in comparison and
            _approved_heldout_population(store, split) != (
                comparison['approved_split_total'],
                comparison.get('approved_split_sha256'))):
        raise BenchmarkError('Held-out population changed before saving; re-evaluation required')
    # The candidate can have been replaced in the Ollama daemon between
    # evaluation and this explicit owner-confirmed report save. An observed
    # score must never become review evidence for a different installed tag.
    if 'baseline_digest' in comparison and 'candidate_digest' in comparison:
        from .runtime import RoutingError, model_digest
        try:
            if (model_digest(comparison['baseline']) != comparison['baseline_digest']
                    or model_digest(comparison['candidate']) != comparison['candidate_digest']):
                raise BenchmarkError('Evaluated local model digest changed before saving')
        except (RoutingError, TypeError, KeyError) as exc:
            raise BenchmarkError('Evaluated local model inventory unavailable before saving') from exc
    root = _private_root(store) / 'evaluations'
    if root.is_symlink():
        raise DatasetError('Private evaluation directory may not be a symlink')
    root.mkdir(mode=0o700, exist_ok=True)
    if root.resolve() != root:
        raise DatasetError('Unsafe evaluation directory')
    try:
        payload = (json.dumps(comparison, sort_keys=True, allow_nan=False,
                              separators=(',', ':')) + '\n').encode('utf-8')
    except (ValueError, TypeError) as exc:
        raise BenchmarkError('Evaluation report must contain finite JSON data') from exc
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
