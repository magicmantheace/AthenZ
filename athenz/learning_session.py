"""Private, revision-fenced ledger for explicit local learning experiments.

A session is an evidence journal, not an orchestrator: it cannot start
training, run inference, install weights, route models, or grant permissions.
Only aggregate status and opaque local identifiers are displayed.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets

from .adapters import ALIAS, verified_registry_entry
from .evaluation import (evaluate_decisions, _heldout_rows,
                         _reference_fingerprint)
from .experience import ExperienceStore
from .learning_cycle import inspect_learning_cycle
from .model_gate import (_approved_heldout_population, _consistent_comparison_metadata,
                         _heldout_fingerprint, _validated_case_outcomes,
                         _case_outcome_fingerprint)
from .training import _private_root, verify_dataset


_ID = re.compile(r'[0-9a-f]{16}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_STAGES = frozenset({'prepared', 'baselined', 'trained', 'evaluated', 'closed', 'cancelled'})


class LearningSessionError(ValueError):
    """A session transition or its owner-reviewed evidence was not valid."""


def _key(session_id: str) -> str:
    if type(session_id) is not str or not _ID.fullmatch(session_id):
        raise LearningSessionError('Invalid opaque learning session ID')
    return 'learning_session_' + session_id


def _checkpoint(store: ExperienceStore, session_id: str) -> dict:
    item = store.get_checkpoint(_key(session_id))
    if item is None or not isinstance(item.get('state'), dict):
        raise LearningSessionError('Learning session not found')
    s = item['state']
    if (type(s.get('schema')) is not int or s['schema'] not in (1, 2, 3)
            or s.get('stage') not in _STAGES
            or (s['schema'] == 1 and s['stage'] == 'baselined')
            or s.get('session_id') != session_id
            or not isinstance(s.get('dataset_sha256'), str)
            or not _SHA.fullmatch(s['dataset_sha256'])
            or s.get('split') not in {'calibration', 'test'}
            or type(s.get('limit')) is not int or not 2 <= s['limit'] <= 1000
            or type(s.get('min_cases')) is not int
            or not 2 <= s['min_cases'] <= s['limit']
            or type(s.get('seed')) is not int or not 0 <= s['seed'] < 2**32
            or type(s.get('approved_total')) is not int or s['approved_total'] < 1
            or not isinstance(s.get('population_sha256'), str)
            or not _SHA.fullmatch(s['population_sha256'])
            or not isinstance(s.get('reference_sha256'), str)
            or not _SHA.fullmatch(s['reference_sha256'])):
        raise LearningSessionError('Stored session metadata is invalid')
    if s['schema'] in (2, 3) and s['stage'] in {'baselined', 'trained', 'evaluated', 'closed'}:
        observed_cases = s.get('baseline_cases')
        observed_correct = s.get('baseline_correct')
        if (type(observed_cases) is not int or not s['min_cases'] <= observed_cases <= s['limit']
                or type(observed_correct) is not int
                or not 0 <= observed_correct <= observed_cases
                or type(s.get('baseline_tag')) is not str
                or not ALIAS.fullmatch(s['baseline_tag'])
                or any(type(s.get(field)) is not str or not _SHA.fullmatch(s[field])
                       for field in ('baseline_digest', 'baseline_case_ids_sha256',
                                     'baseline_heldout_sha256', 'baseline_reference_sha256'))):
            raise LearningSessionError('Stored baseline evidence is invalid')
    if s['schema'] == 3 and s['stage'] in {'baselined', 'trained', 'evaluated', 'closed'}:
        if any(type(s.get(field)) is not str or not _SHA.fullmatch(s[field])
               for field in ('baseline_outcome_key', 'baseline_outcome_sha256')):
            raise LearningSessionError('Stored per-case baseline fingerprint is invalid')
    if s['stage'] in {'trained', 'evaluated', 'closed'} and not isinstance(s.get('run_id'), str):
        raise LearningSessionError('Stored session is missing training evidence')
    if s['stage'] in {'evaluated', 'closed'} and not isinstance(s.get('report_sha256'), str):
        raise LearningSessionError('Stored session is missing evaluation evidence')
    return item


def _saved_report(store: ExperienceStore, digest: str) -> dict:
    """Validate private schema-two report including negative comparisons.

    Adapter review refuses unimproved candidates by design. A learning
    journal MUST still record negative observed results, not hide failures.
    It never turns a report into activation authority.
    """
    if type(digest) is not str or not _SHA.fullmatch(digest):
        raise LearningSessionError('Invalid comparison report fingerprint')
    root = store.home / 'datasets' / 'evaluations'
    path = root / ('eval-' + digest + '.json')
    if (root.is_symlink() or not root.is_dir() or path.is_symlink()
            or not path.is_file() or path.stat().st_size > 128_000):
        raise LearningSessionError('Private comparison report is unavailable')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise LearningSessionError('Comparison report integrity has changed')
    try:
        report = json.loads(raw)
    except (ValueError, UnicodeError, TypeError) as exc:
        raise LearningSessionError('Invalid private comparison report') from exc
    if (not isinstance(report, dict) or type(report.get('schema')) is not int
            or report['schema'] != 2 or not _consistent_comparison_metadata(report)
            or report.get('attestation') != 'local-model-observation-only'
            or report.get('promotion') != 'not-authorized'):
        raise LearningSessionError('Comparison lacks version-two non-deploying evidence')
    return report


def _evidence_is_current(store: ExperienceStore, state: dict) -> bool:
    try:
        verified = verify_dataset(store, state['dataset_sha256'])
        if verified['valid'] is not True:
            return False
        if _approved_heldout_population(store, state['split']) != (
                state['approved_total'], state['population_sha256']):
            return False
        if _reference_fingerprint(store) != state['reference_sha256']:
            return False
        # Recheck current consent, cross-split overlap, selected-case quality,
        # and the exact case bounds without model or GPU access.
        ready = inspect_learning_cycle(
            store, split=state['split'], limit=state['limit'],
            min_cases=state['min_cases'], seed=state['seed'],
            dataset_sha256=state['dataset_sha256'])
        if not ready['ready_for_manual_model_comparison']:
            return False
        if state['schema'] in (2, 3) and state.get('baseline_digest'):
            if (state['baseline_reference_sha256'] != state['reference_sha256']
                    or state['baseline_heldout_sha256'] !=
                    _heldout_fingerprint(store, state['split'], state['baseline_cases'])):
                return False
            ids = [row[0] for row in store.db.execute(
                "SELECT id FROM decisions WHERE status='approved' AND split=? "
                "ORDER BY id LIMIT ?", (state['split'], state['baseline_cases']))]
            if hashlib.sha256(json.dumps(ids).encode()).hexdigest() != state['baseline_case_ids_sha256']:
                return False
        if state.get('run_id'):
            registered = verified_registry_entry(store, state['run_id'])
            if (registered['dataset_sha256'] != state['dataset_sha256']
                    or registered['candidate_model'] != state['candidate_tag']):
                return False
        if state.get('report_sha256'):
            report = _saved_report(store, state['report_sha256'])
            if (report['candidate'] != state['candidate_tag']
                    or report['dataset_sha256'] != state['dataset_sha256']
                    or report['split'] != state['split']
                    or report['requested_case_limit'] != state['limit']
                    or report['seed'] != state['seed']
                    or report['approved_split_total'] != state['approved_total']
                    or report['approved_split_sha256'] != state['population_sha256']
                    or report['reference_fingerprint'] != state['reference_sha256']
                    or report['heldout_fingerprint'] !=
                    _heldout_fingerprint(store, state['split'], report['cases'])
                    or report['baseline_digest'] != state['baseline_digest']
                    or report['candidate_digest'] != state['candidate_digest']):
                return False
            if state['schema'] in (2, 3) and (
                    report['baseline'] != state['baseline_tag']
                    or report['baseline_correct'] != state['baseline_correct']
                    or report['cases'] != state['baseline_cases']
                    or report['case_ids_sha256'] != state['baseline_case_ids_sha256']
                    or report['baseline_digest'] != state['baseline_digest']):
                return False
            if state['schema'] == 3 and (
                    report.get('baseline_outcome_sha256') != state['baseline_outcome_sha256']):
                return False
        return True
    except (ValueError, OSError, UnicodeError, TypeError, KeyError, IndexError):
        return False


def _summary(item: dict, *, current: bool) -> dict:
    state = item['state']
    return {
        'session_id': state['session_id'], 'revision': item['revision'],
        'stage': state['stage'], 'evidence_current': current,
        'baseline_observed': bool(state.get('baseline_digest')),
        'baseline_outcomes_pinned': bool(state.get('baseline_outcome_sha256')),
        'baseline_model_installed_verified': False,
        'training_run_linked': bool(state.get('run_id')),
        'comparison_linked': bool(state.get('report_sha256')),
        'observed_outcome': state.get('observed_outcome', 'not-measured'),
        'owner_action_required': True, 'model_called': False,
        'training_started': False, 'model_selected': False,
        'promotion_authorized': False, 'private_text_returned': False,
        'rollback': 'separate-explicit-owner-action',
    }


def start_session(store: ExperienceStore, dataset_sha256: str, *,
                  split: str = 'calibration', limit: int = 100,
                  min_cases: int = 10, seed: int = 42,
                  confirmed: bool = False) -> dict:
    if not confirmed:
        raise LearningSessionError('Explicit --confirm required to record a learning session')
    if type(dataset_sha256) is not str or not _SHA.fullmatch(dataset_sha256):
        raise LearningSessionError('Invalid dataset fingerprint')
    try:
        planning = inspect_learning_cycle(
            store, split=split, limit=limit, min_cases=min_cases,
            seed=seed, dataset_sha256=dataset_sha256)
        if not planning['ready_for_manual_model_comparison']:
            raise LearningSessionError('Approved learning sources are not ready')
        total, population = _approved_heldout_population(store, split)
        reference = _reference_fingerprint(store)
        # Fail closed on a source change between planning and persistence.
        verify_dataset(store, dataset_sha256)
        rerun = inspect_learning_cycle(
            store, split=split, limit=limit, min_cases=min_cases,
            seed=seed, dataset_sha256=dataset_sha256)
        if not rerun['ready_for_manual_model_comparison'] or (
                _approved_heldout_population(store, split) != (total, population)
                or _reference_fingerprint(store) != reference):
            raise LearningSessionError('Learning evidence changed during setup')
    except (ValueError, OSError, UnicodeError) as exc:
        raise LearningSessionError('Learning preflight failed; review local evidence') from exc
    for _ in range(4):
        session_id = secrets.token_hex(8)
        if store.get_checkpoint(_key(session_id)) is None:
            break
    else:
        raise LearningSessionError('Could not reserve a unique session ID')
    state = {'schema': 3, 'session_id': session_id, 'stage': 'prepared',
             'dataset_sha256': dataset_sha256, 'split': split, 'limit': limit,
             'min_cases': min_cases, 'seed': seed, 'approved_total': total,
             'population_sha256': population, 'reference_sha256': reference}
    store.checkpoint(_key(session_id), 'Private learning experiment evidence (no automation)',
                     state, status='paused', expected_revision=0)
    return _summary(_checkpoint(store, session_id), current=True)


def session_status(store: ExperienceStore, session_id: str) -> dict:
    item = _checkpoint(store, session_id)
    # Never claim cancelled records are ready, even with unchanged evidence.
    current = (item['state']['stage'] != 'cancelled'
               and _evidence_is_current(store, item['state']))
    return _summary(item, current=current)


def _transition(store: ExperienceStore, session_id: str, expected_revision: int,
                stage: str, changes: dict) -> dict:
    if type(expected_revision) is not int or expected_revision < 1:
        raise LearningSessionError('Provide the current session revision')
    key = _key(session_id)
    item = _checkpoint(store, session_id)
    if item['revision'] != expected_revision:
        raise LearningSessionError('Session revision changed; reload before updating')
    state = {**item['state'], **changes, 'stage': stage}
    try:
        store.checkpoint(key, item['task'], state,
                         status='complete' if stage == 'closed' else 'paused',
                         expected_revision=expected_revision)
    except ValueError as exc:
        raise LearningSessionError('Session changed during update; reload') from exc
    return session_status(store, session_id)


def record_baseline(store: ExperienceStore, session_id: str, model, *,
                    expected_revision: int, confirmed: bool = False) -> dict:
    """Record a deterministic protected baseline BEFORE linking training.

    Explicit local inference only; no training, adapter creation, import or
    deployment. Model digest is observed before/after. The experiment journal
    stores aggregate counts and private evidence digests, never predictions,
    prompts, gold answers or their rationales.
    """
    if not confirmed:
        raise LearningSessionError('Explicit --confirm required before baseline inference')
    item = _checkpoint(store, session_id)
    state = item['state']
    if type(expected_revision) is not int or expected_revision != item['revision']:
        raise LearningSessionError('Session revision changed; reload before inference')
    if state['schema'] not in (2, 3) or state['stage'] != 'prepared':
        raise LearningSessionError('Only a new prepared session can record its baseline')
    tag = getattr(model, 'model', None)
    if type(tag) is not str or not ALIAS.fullmatch(tag):
        raise LearningSessionError('Select one explicitly named local baseline model')
    if not _evidence_is_current(store, state):
        raise LearningSessionError('Source evidence changed; start a new session')
    from .runtime import model_digest
    try:
        pinned_digest = model_digest(tag)
        observations = evaluate_decisions(
            store, model, split=state['split'], limit=state['limit'],
            seed=state['seed'])
        if model_digest(tag) != pinned_digest:
            raise LearningSessionError('Baseline model digest changed during inference')
        cases = _validated_case_outcomes(observations)
        selected_ids = [row[0] for row in _heldout_rows(store, state['split'], state['limit'])]
        scored_ids = [case['id'] for case in cases]
        if (len(cases) < state['min_cases']
                or len(set(scored_ids)) != len(scored_ids)
                or selected_ids != scored_ids
                or observations['heldout_sha256'] !=
                    _heldout_fingerprint(store, state['split'], state['limit'])
                or observations['reference_sha256'] != state['reference_sha256']
                or _approved_heldout_population(store, state['split']) != (
                    state['approved_total'], state['population_sha256'])
                or not _evidence_is_current(store, state)):
            raise LearningSessionError('Baseline evaluation evidence changed or is incomplete')
    except LearningSessionError:
        raise
    except Exception:
        # Local model backends can include private prompts in exceptions.
        # Suppress chained tracebacks: CLI exceptions must never print that
        # backend message or echo the held-out content it may contain.
        raise LearningSessionError('Baseline evaluation failed; review local evidence') from None
    # Private per-session key makes per-case outcome hashes resistant to
    # exhaustive guessing when the held-out set is small. Only this checkpoint
    # stores the key. No per-case prediction text is persisted.
    outcome_fields = {}
    if state['schema'] == 3:
        outcome_key = secrets.token_bytes(32)
        outcome_fields = {
            'baseline_outcome_key': outcome_key.hex(),
            'baseline_outcome_sha256': _case_outcome_fingerprint(
                cases, outcome_key)}
    return _transition(store, session_id, expected_revision, 'baselined', {
        **outcome_fields,
        'baseline_tag': tag, 'baseline_digest': pinned_digest,
        'baseline_cases': len(cases), 'baseline_correct': observations['correct'],
        'baseline_case_ids_sha256': hashlib.sha256(
            json.dumps(scored_ids).encode()).hexdigest(),
        'baseline_heldout_sha256': observations['heldout_sha256'],
        'baseline_reference_sha256': observations['reference_sha256']})


def link_completed_run(store: ExperienceStore, session_id: str, run_id: str, *,
                       expected_revision: int, confirmed: bool = False) -> dict:
    if not confirmed:
        raise LearningSessionError('Explicit --confirm required to link a trained adapter')
    item = _checkpoint(store, session_id)
    if item['state']['stage'] != ('baselined' if item['state']['schema'] in (2, 3) else 'prepared'):
        raise LearningSessionError('Session is not awaiting a completed training run')
    if not _evidence_is_current(store, item['state']):
        raise LearningSessionError('Source evidence changed; start a new session')
    try:
        registered = verified_registry_entry(store, run_id)
    except (ValueError, OSError, TypeError) as exc:
        raise LearningSessionError('Completed training registration is not verifiable') from exc
    if registered['dataset_sha256'] != item['state']['dataset_sha256']:
        raise LearningSessionError('Training run uses a different approved dataset')
    return _transition(store, session_id, expected_revision, 'trained', {
        'run_id': run_id, 'candidate_tag': registered['candidate_model'],
        'adapter_sha256': registered['adapter_sha256']})


def link_comparison(store: ExperienceStore, session_id: str, report_sha256: str, *,
                    expected_revision: int, confirmed: bool = False) -> dict:
    if not confirmed:
        raise LearningSessionError('Explicit --confirm required to link evaluation evidence')
    item = _checkpoint(store, session_id)
    state = item['state']
    if state['stage'] != 'trained':
        raise LearningSessionError('Session is not awaiting model comparison')
    if not _evidence_is_current(store, state):
        raise LearningSessionError('Source or training evidence changed')
    report = _saved_report(store, report_sha256)
    if (report['dataset_sha256'] != state['dataset_sha256']
            or report['split'] != state['split'] or report['seed'] != state['seed']
            or report['requested_case_limit'] != state['limit']
            or report['approved_split_total'] != state['approved_total']
            or report['approved_split_sha256'] != state['population_sha256']
            or report['reference_fingerprint'] != state['reference_sha256']
            or report['candidate'] != state['candidate_tag']
            or report['cases'] < state['min_cases']
            or (state['schema'] in (2, 3) and (
                report['baseline'] != state['baseline_tag']
                or report['baseline_digest'] != state['baseline_digest']
                or report['baseline_correct'] != state['baseline_correct']
                or report['cases'] != state['baseline_cases']
                or report['case_ids_sha256'] != state['baseline_case_ids_sha256']))
            or (state['schema'] == 3 and report.get('baseline_outcome_sha256') !=
                state['baseline_outcome_sha256'])
            or report['heldout_fingerprint'] !=
                _heldout_fingerprint(store, state['split'], report['cases'])):
        raise LearningSessionError('Report is for different or outdated model evidence')
    gain = report['candidate_correct'] - report['baseline_correct']
    result = ('candidate-improved-observed' if gain > 0
              else 'candidate-regressed-observed' if gain < 0
              else 'no-observed-gain')
    return _transition(store, session_id, expected_revision, 'evaluated', {
        'report_sha256': report_sha256, 'observed_outcome': result,
        'baseline_digest': report['baseline_digest'],
        'candidate_digest': report['candidate_digest']})


def session_comparison_context(store: ExperienceStore, session_id: str, *,
                               expected_revision: int, baseline: str,
                               candidate: str, dataset_sha256: str, split: str,
                               limit: int, seed: int) -> tuple[bytes, str]:
    """Validate same-session comparison and supply private keyed digest salt.

    Call before and after inferencing. This function never makes network
    requests; the caller must separately require explicit inference consent.
    """
    item = _checkpoint(store, session_id)
    state = item['state']
    if type(expected_revision) is not int or item['revision'] != expected_revision:
        raise LearningSessionError('Session revision changed; reload before inference')
    if state['schema'] != 3 or state['stage'] != 'trained':
        raise LearningSessionError('Session must have a registered run and keyed baseline')
    if (baseline != state['baseline_tag'] or candidate != state['candidate_tag']
            or dataset_sha256 != state['dataset_sha256'] or split != state['split']
            or type(limit) is not int or limit != state['limit']
            or type(seed) is not int or seed != state['seed']):
        raise LearningSessionError('Requested comparison differs from session baseline')
    if not _evidence_is_current(store, state):
        raise LearningSessionError('Session evidence changed before comparison')
    return bytes.fromhex(state['baseline_outcome_key']), state['baseline_outcome_sha256']


def close_session(store: ExperienceStore, session_id: str, *,
                  expected_revision: int, confirmed: bool = False) -> dict:
    if not confirmed:
        raise LearningSessionError('Explicit --confirm required to close a learning session')
    item = _checkpoint(store, session_id)
    if item['state']['stage'] != 'evaluated':
        raise LearningSessionError('Only evaluated sessions may be closed')
    if not _evidence_is_current(store, item['state']):
        raise LearningSessionError('Evidence changed; session cannot be finalized')
    return _transition(store, session_id, expected_revision, 'closed', {})


def cancel_session(store: ExperienceStore, session_id: str, *,
                   expected_revision: int, confirmed: bool = False) -> dict:
    if not confirmed:
        raise LearningSessionError('Explicit --confirm required to cancel a learning session')
    item = _checkpoint(store, session_id)
    if item['state']['stage'] in {'closed', 'cancelled'}:
        raise LearningSessionError('Session already finalized or cancelled')
    return _transition(store, session_id, expected_revision, 'cancelled', {})
