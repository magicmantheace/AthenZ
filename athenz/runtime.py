"""Owner-controlled AthenZ Ollama *tag routing*, not weight installation.

No Ollama create/pull/push/delete operations exist here. A selected adapter is
an owner-declared lineage, not independent proof of an Ollama weight import.
Every routed inference rechecks the exact Ollama tag digest and private consent.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .adapters import ALIAS, _read_review, selection, verified_registry_entry
from .chat import LocalModelError, OllamaClient
from .experience import ExperienceStore

SHA = re.compile(r'[0-9a-f]{64}\Z')
CHECKPOINT = 'ollama_runtime'


class RoutingError(ValueError):
    """Runtime selection was rejected or is no longer verifiable."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RoutingError('Local Ollama endpoint redirected; refusing remote requests')


def model_digest(tag: str, *, endpoint: str | None = None) -> str:
    """Observe a locally installed Ollama model's manifest digest.

    The only HTTP request is to the validated loopback API. The response is
    bounded, redirects are rejected, and no private owner text is sent.
    """
    if not isinstance(tag, str) or not ALIAS.fullmatch(tag):
        raise RoutingError('Select one explicit, local Ollama model tag')
    client = OllamaClient(endpoint=endpoint, model=tag)
    request = Request(client.endpoint + '/api/tags', method='GET')
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=8) as response:
            raw = response.read(1024 * 1024 + 1)
    except RoutingError:
        raise
    except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
        raise RoutingError('Local Ollama tag inventory is unavailable') from exc
    if len(raw) > 1024 * 1024:
        raise RoutingError('Ollama inventory exceeds the safe response limit')
    try:
        obj = json.loads(raw)
        rows = obj['models']
    except (ValueError, TypeError, KeyError) as exc:
        raise RoutingError('Malformed Ollama tag inventory') from exc
    if not isinstance(rows, list):
        raise RoutingError('Malformed Ollama tag inventory')
    canonical = tag if ':' in tag else tag + ':latest'
    matching = [r for r in rows if isinstance(r, dict)
                and (r.get('name') == canonical or r.get('model') == canonical)]
    if len(matching) != 1 or not isinstance(matching[0].get('digest'), str) \
            or not SHA.fullmatch(matching[0]['digest']):
        raise RoutingError('Ollama tag is missing, ambiguous or lacks a verifiable SHA-256 digest')
    return matching[0]['digest']


def _checkpoint(store: ExperienceStore) -> dict | None:
    return store.get_checkpoint(CHECKPOINT)


def _import_lineage(store: ExperienceStore, run_id: str,
                    candidate_tag: str, candidate_digest: str) -> dict:
    """Verify the actual owner-reviewed GGUF import without contacting Ollama.

    Import evidence is itself owner-acknowledged, not an independent proof of
    model-weight derivation. A prepared, failed or tampered import is never
    equivalent to a successfully created local candidate tag.
    """
    from .ollama_import import verify_import
    try:
        imported = verify_import(store, run_id)
    except (ValueError, OSError, TypeError, KeyError, UnicodeError):
        # Private paths may be present in lower-level filesystem exceptions.
        raise RoutingError('Recorded local model import is missing or stale') from None
    if (imported.get('status') != 'complete'
            or imported.get('deployment') != 'created-local-not-selected'
            or imported.get('candidate_tag') != candidate_tag
            or imported.get('candidate_digest') != candidate_digest):
        raise RoutingError('Recorded local model import does not match reviewed candidate')
    return imported


def _check_lineage(store: ExperienceStore, state: dict) -> None:
    run_id = state.get('active_run_id')
    if run_id is None:
        return  # Manually restored baseline; only its tag digest must match.
    selected = selection(store)
    if selected.get('active_run_id') != run_id or not selected.get('owner_lineage_acknowledged'):
        raise RoutingError('Adapter review selection changed; use explicit rollback')
    report_sha = state.get('evaluation_sha256')
    if report_sha != selected.get('evaluation_sha256'):
        raise RoutingError('Adapter evaluation selection changed')
    entry = verified_registry_entry(store, run_id)  # consent, adapter bytes, base fingerprint
    report = _read_review(store, report_sha)  # approval and held-out decision fingerprint
    if (report.get('dataset_sha256') != entry['dataset_sha256'] or
            report.get('candidate') != entry['candidate_model'] or
            report.get('baseline') != state.get('baseline_tag') or
            report.get('baseline_digest') != state.get('baseline_digest') or
            report.get('candidate_digest') != state.get('active_digest') or
            state.get('active_tag') != entry['candidate_model']):
        raise RoutingError('Candidate/evaluation/adapter lineage no longer agrees')
    policy = state.get('lineage_policy')
    routing_schema = state.get('routing_schema')
    if (routing_schema not in (None, 2) or
            (routing_schema == 2 and policy is None)):
        raise RoutingError('Runtime provenance marker missing or invalid')
    if policy in (None, 'legacy-owner-attested'):
        # A missing policy denotes a historical checkpoint created before
        # this gate, which remains readable and rollback-capable. New legacy
        # activations require the owner's explicit --ack-legacy-lineage.
        return
    if policy != 'recorded-local-import':
        raise RoutingError('Unknown runtime lineage policy; explicit rollback required')
    imported = _import_lineage(
        store, run_id, entry['candidate_model'], state['active_digest'])
    if (type(state.get('import_revision')) is not int
            or imported['revision'] != state['import_revision']
            or state.get('gguf_sha256') != imported['gguf_sha256']):
        raise RoutingError('Pinned import evidence changed; runtime routing paused')


def status(store: ExperienceStore) -> dict:
    cp = _checkpoint(store)
    if cp is None:
        return {'revision': 0, 'active_tag': None, 'baseline_tag': None,
                'active_run_id': None, 'routing': 'default-configuration'}
    state = cp['state']
    return {k: state.get(k) for k in ('active_tag', 'active_digest', 'baseline_tag',
                                      'baseline_digest', 'active_run_id', 'evaluation_sha256',
                                      'routing_schema', 'lineage_policy',
                                      'import_revision', 'gguf_sha256')} | {
        'revision': cp['revision'], 'routing': 'explicit-local-tag-selection'}


def checked_active_tag(store: ExperienceStore, *, endpoint: str | None = None) -> str | None:
    """Fail CLOSED if tag, private approval or review evidence drifts."""
    cp = _checkpoint(store)
    if cp is None:
        return None
    state = cp['state']
    _check_lineage(store, state)
    tag, expected = state.get('active_tag'), state.get('active_digest')
    if not isinstance(tag, str) or not isinstance(expected, str) or not SHA.fullmatch(expected):
        raise RoutingError('Stored runtime model selection is malformed')
    if model_digest(tag, endpoint=endpoint) != expected:
        raise RoutingError('Ollama tag digest changed: routing paused until owner review')
    return tag


def activate(store: ExperienceStore, *, expected_revision: int, baseline_tag: str,
             confirmed: bool = False, endpoint: str | None = None,
             smoke_model_factory=None,
             ack_legacy_lineage: bool = False) -> dict:
    """Probe already-installed candidate, then atomically route AthenZ to its tag.

    Nothing is added to or changed in the Ollama server. Candidate lineage is
    acknowledged by the owner in the existing adapter review flow.
    """
    if not confirmed:
        raise RoutingError('Explicit --confirm required to activate a local tag')
    if type(ack_legacy_lineage) is not bool:
        raise RoutingError('Invalid legacy-lineage acknowledgment')
    if not isinstance(baseline_tag, str) or not ALIAS.fullmatch(baseline_tag):
        raise RoutingError('Baseline must be an explicit local tag')
    cp = _checkpoint(store)
    revision = cp['revision'] if cp else 0
    if revision != expected_revision:
        raise RoutingError('Runtime revision changed; recheck status')
    previous = cp['state'] if cp else None
    if previous and previous.get('active_run_id') is not None:
        raise RoutingError('Roll back the existing candidate before activating another')
    selected = selection(store)
    run_id = selected.get('active_run_id')
    if run_id is None or not selected.get('owner_lineage_acknowledged'):
        raise RoutingError('Select a reviewed, lineage-acknowledged adapter first')
    entry = verified_registry_entry(store, run_id)
    report_sha = selected.get('evaluation_sha256')
    report = _read_review(store, report_sha)
    candidate = entry['candidate_model']
    if (report.get('candidate') != candidate or report.get('baseline') != baseline_tag
            or report.get('dataset_sha256') != entry['dataset_sha256']
            or candidate == baseline_tag):
        raise RoutingError('Baseline/candidate/evaluation identities do not match')
    baseline_sha = model_digest(baseline_tag, endpoint=endpoint)
    candidate_sha = model_digest(candidate, endpoint=endpoint)
    if baseline_sha == candidate_sha:
        raise RoutingError('Baseline and candidate have identical Ollama digests')
    if (report.get('baseline_digest') != baseline_sha or
            report.get('candidate_digest') != candidate_sha):
        raise RoutingError('Installed model digests differ from evaluated model digests')
    if previous and (previous.get('baseline_tag') != baseline_tag
                     or previous.get('baseline_digest') != baseline_sha):
        raise RoutingError('Baseline drifted since previous runtime selection')
    import_checkpoint = store.get_checkpoint('ollama_import_' + run_id)
    if import_checkpoint is None:
        if not ack_legacy_lineage:
            raise RoutingError(
                'No recorded local model import; explicit --ack-legacy-lineage required')
        lineage = {'lineage_policy': 'legacy-owner-attested'}
    else:
        # An invalid or interrupted import cannot be bypassed by requesting
        # the legacy path: a recorded import must validate before activation.
        imported = _import_lineage(store, run_id, candidate, candidate_sha)
        lineage = {'lineage_policy': 'recorded-local-import',
                   'import_revision': imported['revision'],
                   'gguf_sha256': imported['gguf_sha256']}
    # No private examples, chat logs, or identity context are used for smoke inference.
    model = (smoke_model_factory(candidate) if smoke_model_factory is not None
             else OllamaClient(endpoint=endpoint, model=candidate))
    try:
        reply = model.generate([{'role': 'user', 'content': 'Reply with a short greeting.'}],
                               timeout=30, temperature=0)
    except Exception:
        # Backend exceptions may include prompts or sensitive local paths.
        raise RoutingError('Candidate local inference failed; runtime unchanged') from None
    if not isinstance(reply, str) or not reply.strip():
        raise RoutingError('Candidate returned no text; runtime unchanged')
    if model_digest(candidate, endpoint=endpoint) != candidate_sha:
        raise RoutingError('Candidate tag changed during smoke test')
    if model_digest(baseline_tag, endpoint=endpoint) != baseline_sha:
        raise RoutingError('Baseline tag changed during candidate smoke test')
    # Source approval may be revoked during the smoke inference.
    checked_state = {'active_run_id': run_id, 'evaluation_sha256': report_sha,
                     'baseline_tag': baseline_tag, 'active_tag': candidate,
                     'baseline_digest': baseline_sha, 'active_digest': candidate_sha,
                     'routing_schema': 2, **lineage}
    _check_lineage(store, checked_state)
    state = checked_state
    store.checkpoint(CHECKPOINT, 'Owner-approved local Ollama tag routing', state,
                     status='paused', expected_revision=revision)
    return status(store)


def inspect_rollback_readiness(store: ExperienceStore, *,
                               check_ollama: bool = False,
                               endpoint: str | None = None) -> dict:
    """Read-only feasibility check for explicit local baseline restoration.

    A revoked/deleted candidate MUST NOT block rollback. Do not query its
    adapter, evaluation report or installed tag. By default this is an
    offline structural assessment only; --check-ollama performs one read-only
    loopback tag inventory request to verify the pinned baseline digest.
    This does not actually restore routing or prove live inference works.
    """
    if type(check_ollama) is not bool:
        raise RoutingError('Invalid rollback readiness check mode')
    cp = _checkpoint(store)
    revision = cp['revision'] if cp is not None else 0
    state = cp['state'] if cp is not None else {}
    candidate_active = state.get('active_run_id') is not None
    baseline = state.get('baseline_tag')
    digest = state.get('baseline_digest')
    structurally_valid = (candidate_active and type(baseline) is str
                          and ALIAS.fullmatch(baseline) is not None
                          and type(digest) is str and SHA.fullmatch(digest) is not None
                          and type(state.get('active_tag')) is str
                          and type(state.get('active_digest')) is str
                          and SHA.fullmatch(state['active_digest']) is not None)
    matching = False
    if structurally_valid and check_ollama:
        try:
            matching = model_digest(baseline, endpoint=endpoint) == digest
        except (RoutingError, TypeError, OSError, ValueError):
            matching = False
    if not candidate_active:
        next_step = 'no-active-candidate'
    elif not structurally_valid:
        next_step = 'review-invalid-baseline-record'
    elif not check_ollama:
        next_step = 'check-local-baseline-digest'
    elif not matching:
        next_step = 'restore-or-review-pinned-baseline'
    else:
        next_step = 'owner-may-confirm-runtime-rollback'
    return {'revision': revision, 'candidate_active': candidate_active,
            'baseline_record_valid': bool(structurally_valid),
            'local_inventory_checked': bool(structurally_valid and check_ollama),
            'baseline_digest_matches': bool(matching),
            'ready_for_manual_rollback': bool(structurally_valid and check_ollama and matching),
            'next_step': next_step, 'model_called': False,
            'routing_changed': False, 'training_started': False,
            'promotion_authorized': False, 'private_text_returned': False}


def _restore_state(old: dict) -> dict:
    """Shared projected baseline pointer for real and rehearsed rollback."""
    baseline, digest = old.get('baseline_tag'), old.get('baseline_digest')
    if (type(baseline) is not str or ALIAS.fullmatch(baseline) is None
            or type(digest) is not str or SHA.fullmatch(digest) is None):
        raise RoutingError('Pinned baseline routing record is malformed')
    return {'active_tag': baseline, 'active_digest': digest,
            'baseline_tag': baseline, 'baseline_digest': digest,
            'active_run_id': None, 'evaluation_sha256': None}


def rehearse_rollback(store: ExperienceStore, *, expected_revision: int,
                      confirmed: bool = False, endpoint: str | None = None,
                      smoke_model_factory=None) -> dict:
    """Exercise baseline inference and SQLite rollback CAS without keeping a write.

    This deliberately does NOT depend on candidate/model adapter lineage:
    stale or revoked candidates must not prevent restoring the pinned baseline.
    A SAVEPOINT exercises the actual checkpoint update and checked routing,
    then ALWAYS reverses the projected state and its event-log write.
    """
    if not confirmed:
        raise RoutingError('Explicit --confirm required for local rollback rehearsal')
    if type(expected_revision) is not int or expected_revision < 1:
        raise RoutingError('Provide the current runtime revision')
    cp = _checkpoint(store)
    if (cp is None or cp['revision'] != expected_revision
            or cp['state'].get('active_run_id') is None):
        raise RoutingError('No current candidate or runtime revision conflict')
    projected = _restore_state(cp['state'])
    baseline, expected_digest = projected['baseline_tag'], projected['baseline_digest']
    if model_digest(baseline, endpoint=endpoint) != expected_digest:
        raise RoutingError('Pinned baseline digest changed; rehearsal refused')
    model = (smoke_model_factory(baseline) if smoke_model_factory is not None
             else OllamaClient(endpoint=endpoint, model=baseline))
    try:
        reply = model.generate(
            [{'role': 'user', 'content': 'Reply with a short greeting.'}],
            timeout=30, temperature=0)
    except Exception:
        # Local-model exception messages can contain private operational data.
        raise RoutingError('Baseline smoke inference failed; routing unchanged') from None
    if not isinstance(reply, str) or not reply.strip():
        raise RoutingError('Baseline smoke inference returned no text; routing unchanged')
    if model_digest(baseline, endpoint=endpoint) != expected_digest:
        raise RoutingError('Pinned baseline changed during rehearsal; routing unchanged')
    observed = _checkpoint(store)
    if (observed is None or observed['revision'] != expected_revision
            or observed['state'] != cp['state']):
        raise RoutingError('Runtime revision changed during rehearsal; routing unchanged')

    # The current repository checkpoint API joins an existing transaction
    # rather than committing inside it. SAVEPOINT therefore exercises its
    # real compare-and-swap and event path without ever persisting the change.
    # Verify the simulated restored tag, then roll back even on failure.
    try:
        store.db.execute('SAVEPOINT athenz_rollback_rehearsal')
        try:
            store.checkpoint(
                CHECKPOINT, cp['task'], projected, status='paused',
                expected_revision=expected_revision)
            staged = _checkpoint(store)
            if (staged is None or staged['revision'] != expected_revision + 1
                    or staged['state'] != projected
                    or checked_active_tag(store, endpoint=endpoint) != baseline):
                raise RoutingError('Simulated baseline routing failed')
        finally:
            store.db.execute('ROLLBACK TO SAVEPOINT athenz_rollback_rehearsal')
            store.db.execute('RELEASE SAVEPOINT athenz_rollback_rehearsal')
    except Exception:
        # No private backend/SQLite error details in the CLI traceback.
        raise RoutingError('Rollback rehearsal failed; no routing change kept') from None
    unchanged = _checkpoint(store)
    if (unchanged is None or unchanged['revision'] != cp['revision']
            or unchanged['state'] != cp['state']):
        raise RoutingError('Rehearsal integrity check failed; inspect local routing')
    return {'revision': expected_revision, 'baseline_smoke_passed': True,
            'projected_checkpoint_tested': True,
            'checkpoint_unchanged': True, 'ready_for_owner_rollback': True,
            'model_called': True, 'routing_changed': False,
            'training_started': False, 'promotion_authorized': False,
            'private_text_returned': False,
            'next_step': 'owner-may-confirm-runtime-rollback'}


def rollback(store: ExperienceStore, *, expected_revision: int,
             confirmed: bool = False, endpoint: str | None = None) -> dict:
    """Restore pinned baseline even if adapter/candidate has been revoked or deleted."""
    if not confirmed:
        raise RoutingError('Explicit --confirm required for model routing rollback')
    cp = _checkpoint(store)
    if (cp is None or type(expected_revision) is not int
            or cp['revision'] != expected_revision
            or cp['state'].get('active_run_id') is None):
        raise RoutingError('No current candidate or runtime revision conflict')
    state = _restore_state(cp['state'])
    if model_digest(state['baseline_tag'], endpoint=endpoint) != state['baseline_digest']:
        raise RoutingError('Pinned baseline digest changed; refusing unsafe rollback')
    store.checkpoint(CHECKPOINT, cp['task'], state, status='paused',
                     expected_revision=cp['revision'])
    return status(store)
