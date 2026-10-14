"""Private adapter artifacts and owner-review selection, never deployment.

A selection here is bookkeeping only: it cannot replace an Ollama model, load
weights, grant execution privileges, or prove a candidate Ollama tag uses an
adapter. The owner must independently confirm candidate/adapter lineage.
"""
from __future__ import annotations

import hashlib
import json
from math import isfinite
from pathlib import Path
import re

from .experience import ExperienceStore
from .finetune import TrainingError, file_sha256, verify_run
from .model_gate import (_consistent_comparison_metadata, _heldout_fingerprint,
                         _approved_heldout_population)
from .evaluation import (_reference_fingerprint, _reject_overlapping_decision_splits,
                         _reject_repeated_heldout_scenarios)
from .training import DatasetError, _private_root

SHA = re.compile(r'[a-f0-9]{64}\Z')
ALIAS = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.:-]{0,79}\Z')
MAX_ADAPTER_BYTES = 1024 * 1024 * 1024


class AdapterError(ValueError):
    """Adapter lineage, review or private selection could not be validated."""


def inspect_adapter(store: ExperienceStore, run_id: str) -> dict:
    """Verify complete private training result and both expected adapter files."""
    recipe, run, path = verify_run(store, run_id)
    if run['status'] != 'complete':
        raise AdapterError('Only completed, consent-valid local runs may be registered')
    adapter_dir = path / 'adapter'
    if adapter_dir.is_symlink() or not adapter_dir.is_dir():
        raise AdapterError('Completed adapter directory missing or symlinked')
    weights = adapter_dir / 'adapter_model.safetensors'
    config = adapter_dir / 'adapter_config.json'
    files = [weights, config]
    for f in files:
        if f.is_symlink() or not f.is_file() or f.stat().st_size > MAX_ADAPTER_BYTES:
            raise AdapterError('Adapter weights/config missing, symlinked or too large')
    if config.stat().st_size > 1024 * 1024:
        raise AdapterError('Adapter config is too large')
    try:
        obj = json.loads(config.read_text('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise AdapterError('Invalid adapter JSON') from exc
    config_base = obj.get('base_model_name_or_path')
    if obj.get('peft_type') != 'LORA':
        raise AdapterError('Adapter configuration disagrees with reviewed LoRA base')
    if config_base not in (None, ''):
        # Windows may expose an existing directory through short (8.3) and
        # long native spellings. Demand the SAME filesystem object, not
        # matching lexical strings or weakened case-only comparisons.
        if not isinstance(config_base, str):
            raise AdapterError('Adapter configuration disagrees with reviewed LoRA base')
        try:
            same_base = Path(config_base).samefile(Path(recipe['base']['path']))
        except (OSError, ValueError):
            same_base = False
        if not same_base:
            raise AdapterError('Adapter configuration disagrees with reviewed LoRA base')
    weights_sha = file_sha256(weights)
    if weights_sha != run['state'].get('adapter_sha256'):
        raise AdapterError('Adapter weights changed since completed training run')
    config_sha = file_sha256(config)
    return {'run_id': run_id, 'adapter_sha256': weights_sha,
            'config_sha256': config_sha, 'base_fingerprint': recipe['base']['fingerprint'],
            'dataset_sha256': recipe['dataset_sha256'],
            'artifact_sha256': hashlib.sha256((weights_sha + config_sha).encode()).hexdigest(),
            'promotion': 'not-authorized'}


def _registration_anchor(state: dict) -> str:
    """Content digest attached to an immutable local event, never private text."""
    serialized = json.dumps(state, sort_keys=True, separators=(',', ':'),
                            ensure_ascii=False, allow_nan=False).encode('utf-8')
    return 'adapter-registration:' + hashlib.sha256(serialized).hexdigest()


def _registration_events(store: ExperienceStore, checkpoint_id: int) -> list[str]:
    return [row['operation'] for row in store.db.execute(
        "SELECT operation FROM events WHERE subject_type='checkpoints' AND subject_id=? "
        "AND operation LIKE 'adapter-registration:%' ORDER BY id", (checkpoint_id,))]


def register_adapter(store: ExperienceStore, run_id: str, candidate_model: str, *,
                     confirmed: bool = False) -> dict:
    if not confirmed:
        raise AdapterError('Explicit --confirm required to register local adapter')
    if not ALIAS.fullmatch(candidate_model):
        raise AdapterError('Candidate label must be a short explicit local model name')
    evidence = inspect_adapter(store, run_id)
    registered = {**evidence, 'candidate_model': candidate_model,
                  'lineage': 'owner-label-unverified', 'deployment': 'none'}
    key = 'adapter_' + run_id
    # Checkpoint metadata is mutable local SQLite state. Bind its complete
    # canonical registration, including the candidate tag, to the separate
    # append-only events ledger in the SAME database transaction.
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        prior = store.get_checkpoint(key)
        if prior is not None:
            if prior['state'] != registered or prior['status'] != 'complete':
                raise AdapterError('Existing immutable registry entry cannot be replaced')
            checkpoint_id = prior['id']
        else:
            checkpoint_id = store.checkpoint(
                key, 'Private adapter registry entry; not a deployed model',
                registered, status='complete')
        anchor = _registration_anchor(registered)
        events = _registration_events(store, checkpoint_id)
        if events:
            if events != [anchor]:
                raise AdapterError('Existing immutable registry entry cannot be replaced')
        else:
            # Explicit owner confirmation also migrates historical entries
            # lacking an event anchor, but NEVER changes their checkpoint data.
            store._event(anchor, 'checkpoints', checkpoint_id)
    return registered


def verified_registry_entry(store: ExperienceStore, run_id: str) -> dict:
    entry = store.get_checkpoint('adapter_' + run_id)
    if entry is None or entry['status'] != 'complete':
        raise AdapterError('Run is not registered')
    state = entry['state']
    # Verify the ENTIRE immutable registration, not just the weight hashes.
    # In particular the candidate label is authority-bearing metadata: later
    # owner selection compares it to a local Ollama tag and report lineage.
    if not isinstance(state, dict):
        raise AdapterError('Registry entry is stale or tampered')
    candidate = state.get('candidate_model')
    if not isinstance(candidate, str) or not ALIAS.fullmatch(candidate):
        raise AdapterError('Registry entry is stale or tampered')
    expected = {**inspect_adapter(store, run_id),
                'candidate_model': candidate,
                'lineage': 'owner-label-unverified', 'deployment': 'none'}
    if state != expected:
        raise AdapterError('Registry entry is stale or tampered')
    if _registration_events(store, entry['id']) != [_registration_anchor(expected)]:
        raise AdapterError('Registry entry is stale or tampered')
    return state


def _read_review(store: ExperienceStore, sha: str) -> dict:
    if not SHA.fullmatch(sha):
        raise AdapterError('Invalid evaluation report fingerprint')
    folder = _private_root(store) / 'evaluations'
    if folder.is_symlink() or not folder.is_dir():
        raise AdapterError('No private evaluation report directory')
    path = folder / ('eval-' + sha + '.json')
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 128_000:
        raise AdapterError('Private evaluation report missing or invalid')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sha:
        raise AdapterError('Evaluation evidence was modified')
    try:
        report = json.loads(raw)
    except ValueError as exc:
        raise AdapterError('Invalid evaluation report') from exc
    if (type(report.get('schema')) is not int or report['schema'] not in (1, 2)
            or report.get('attestation') != 'local-model-observation-only'
            or report.get('promotion') != 'not-authorized'
            or report.get('split') not in {'calibration', 'test'}
            or not isinstance(report.get('cases'), int) or not 10 <= report['cases'] <= 1000
            or report.get('eligible_for_review') is not True
            or type(report.get('accuracy_gain')) not in (int, float)
            or not isfinite(report['accuracy_gain'])
            or not 0 < report['accuracy_gain'] <= 1):
        raise AdapterError('Evaluation report is not eligible for owner review')
    if not _consistent_comparison_metadata(report):
        raise AdapterError('Evaluation report metadata is inconsistent')
    if report['schema'] == 2:
        # A new out-of-window approved choice or a newly duplicated scored
        # case must also invalidate an already persisted review artifact.
        if _approved_heldout_population(store, report['split']) != (
                report['approved_split_total'], report['approved_split_sha256']):
            raise AdapterError('Held-out population changed; fresh evaluation required')
        try:
            _reject_repeated_heldout_scenarios(
                store, report['split'], report['requested_case_limit'])
        except ValueError as exc:
            raise AdapterError('Held-out sample independence changed; new report required') from exc
    try:
        _reject_overlapping_decision_splits(store)
    except ValueError as exc:
        raise AdapterError('Evaluation partitions overlap; new report required') from exc
    if _heldout_fingerprint(store, report['split'], report['cases']) != report.get('heldout_fingerprint'):
        raise AdapterError('Held-out evaluation evidence is stale')
    if report.get('reference_fingerprint') != _reference_fingerprint(store):
        raise AdapterError('Approved reference evidence is stale; new evaluation required')
    rows = [r[0] for r in store.db.execute(
        'SELECT id FROM decisions WHERE status=? AND split=? ORDER BY id LIMIT ?',
        ('approved', report['split'], report['cases']))]
    if hashlib.sha256(json.dumps(rows).encode()).hexdigest() != report.get('case_ids_sha256'):
        raise AdapterError('Held-out case set changed')
    return report


def selection(store: ExperienceStore) -> dict:
    cp = store.get_checkpoint('adapter_selection')
    if cp is None:
        return {'active_run_id': None, 'history': [], 'revision': 0,
                'deployment': 'none', 'status': 'no-selection'}
    state = cp['state']
    active = state.get('active_run_id')
    if active is not None:
        verified_registry_entry(store, active)
    return {**state, 'revision': cp['revision'], 'deployment': 'none',
            'status': 'selected-for-manual-review' if active else 'no-selection'}


def select_for_review(store: ExperienceStore, run_id: str, report_sha256: str, *,
                      expected_revision: int, confirmed: bool = False,
                      lineage_acknowledged: bool = False) -> dict:
    """Save owner selection only; does NOT activate adapter in Ollama."""
    if not confirmed or not lineage_acknowledged:
        raise AdapterError('Require --confirm and explicit --ack-lineage acknowledgment')
    entry = verified_registry_entry(store, run_id)
    report = _read_review(store, report_sha256)
    if (entry['dataset_sha256'] != report.get('dataset_sha256')
            or entry['candidate_model'] != report.get('candidate')):
        raise AdapterError('Evaluation report does not match the registered dataset/candidate')
    cp = store.get_checkpoint('adapter_selection')
    revision = cp['revision'] if cp else 0
    if expected_revision != revision:
        raise AdapterError('Selection changed; reload before updating')
    prev = cp['state'] if cp else {'active_run_id': None, 'history': []}
    # Preserve only a bounded rollback stack (private IDs, no personal content).
    history = [*prev['history'], prev['active_run_id']][-20:]
    state = {'active_run_id': run_id, 'history': history,
             'evaluation_sha256': report_sha256,
             'deployment': 'none', 'owner_lineage_acknowledged': True}
    store.checkpoint('adapter_selection', 'Owner-selected adapter, not deployed', state,
                     status='paused', expected_revision=revision)
    return selection(store)


def rollback_selection(store: ExperienceStore, *, expected_revision: int,
                       confirmed: bool = False) -> dict:
    if not confirmed:
        raise AdapterError('Explicit --confirm required for selection rollback')
    cp = store.get_checkpoint('adapter_selection')
    if cp is None or cp['revision'] != expected_revision or not cp['state'].get('history'):
        raise AdapterError('No matching selection revision/history to roll back')
    state = cp['state']
    previous = state['history'][-1]
    if previous is not None:
        verified_registry_entry(store, previous)
    new = {'active_run_id': previous, 'history': state['history'][:-1],
           'evaluation_sha256': None, 'deployment': 'none',
           'owner_lineage_acknowledged': False}
    store.checkpoint('adapter_selection', cp['task'], new, status='paused',
                     expected_revision=cp['revision'])
    return selection(store)
