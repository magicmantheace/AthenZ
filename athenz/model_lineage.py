"""Aggregate-only audit of AthenZ's local model evidence chain.

This audit never creates, imports, runs or selects a model, nor does it
return paths, model names, digests, private samples or predictions.
Historical/manual-import evidence is explicitly weaker than an observed
local conversion; neither proves the internal semantics of model weights.
"""
from __future__ import annotations

import re

from .adapters import _read_review, selection, verified_registry_entry
from .conversion import conversion_status
from .experience import ExperienceStore
from .finetune import RUN_ID
from .ollama_import import verify_import
from .runtime import _check_lineage, model_digest


_SHA = re.compile(r'[0-9a-f]{64}\Z')
_EXPECTED_ERRORS = (ValueError, OSError, TypeError, KeyError, UnicodeError, IndexError)


class LineageAuditError(ValueError):
    """Invalid request for an offline private model-lineage check."""


def inspect_model_lineage(store: ExperienceStore, run_id: str, *,
                          check_ollama: bool = False) -> dict:
    """Return stage-level evidence for one registered candidate, without mutation.

    The optional Ollama inventory check reads ONLY the specific candidate's
    digest from an already configured loopback instance; no inference. Every
    stronger conclusion requires separately verifiable prior stages.
    """
    if type(run_id) is not str or RUN_ID.fullmatch(run_id) is None:
        raise LineageAuditError('Invalid opaque training run ID')
    if type(check_ollama) is not bool:
        raise LineageAuditError('Invalid local inventory option')

    stages = dict.fromkeys(
        ('adapter', 'conversion', 'import', 'evaluation', 'selection',
         'routing', 'ollama_candidate'), 'not-checked')
    evidence = {'provenance': 'not-established'}
    registry = None
    converted = None
    imported = None
    reviewed = None

    # Stage 1: Private adapter registration includes current owner consent,
    # source data, LoRA base, adapter bytes and immutable event anchoring.
    try:
        registry = verified_registry_entry(store, run_id)
        stages['adapter'] = 'verified'
    except _EXPECTED_ERRORS:
        stages['adapter'] = 'invalid-or-missing'

    if registry is not None:
        # Stages 2-3: Preserve an important distinction: historical imports
        # are owner-attested, not independently verified LoRA/GGUF lineage.
        conversion_cp = store.get_checkpoint('convert_' + run_id)
        if conversion_cp is None:
            stages['conversion'] = 'not-recorded'
        elif conversion_cp['status'] != 'complete':
            stages['conversion'] = 'not-complete'
        else:
            try:
                converted = conversion_status(store, run_id)
                if (converted['status'] != 'complete'
                        or not isinstance(converted.get('artifact'), dict)
                        or not isinstance(converted['artifact'].get('sha256'), str)
                        or _SHA.fullmatch(converted['artifact']['sha256']) is None):
                    raise LineageAuditError('Conversion evidence incomplete')
                stages['conversion'] = 'verified'
            except _EXPECTED_ERRORS:
                stages['conversion'] = 'invalid'

        import_cp = store.get_checkpoint('ollama_import_' + run_id)
        if import_cp is None:
            stages['import'] = 'not-recorded'
        else:
            try:
                imported = verify_import(store, run_id, verify_ollama=False)
                digest = imported.get('candidate_digest')
                if (imported['status'] != 'complete'
                        or imported.get('deployment') != 'created-local-not-selected'
                        or imported.get('candidate_tag') != registry['candidate_model']
                        or type(digest) is not str or _SHA.fullmatch(digest) is None):
                    stages['import'] = 'not-complete'
                    imported = None
                elif converted is not None and (
                        imported['gguf_sha256'] != converted['artifact']['sha256']
                        or 'local-conversion-observed' not in imported['lineage']):
                    stages['import'] = 'invalid'
                    imported = None
                elif conversion_cp is not None and converted is None:
                    stages['import'] = 'invalid'
                    imported = None
                else:
                    stages['import'] = 'verified'
                    evidence['provenance'] = ('local-conversion-observed'
                        if converted is not None else 'owner-attested-manual-merge')
            except _EXPECTED_ERRORS:
                stages['import'] = 'invalid'
                imported = None

        # Stage 4: A selected review must match exact registered candidate,
        # reviewed training source and current held-out evidence. An unselected
        # report is not invented by searching directories or invoking models.
        selected_cp = store.get_checkpoint('adapter_selection')
        selected_state = selected_cp['state'] if selected_cp is not None else {}
        if selected_state.get('active_run_id') != run_id:
            stages['selection'] = 'not-selected'
            stages['evaluation'] = 'not-linked'
        else:
            try:
                selected = selection(store)
                if (selected['active_run_id'] != run_id
                        or selected.get('owner_lineage_acknowledged') is not True):
                    raise LineageAuditError('No reviewed candidate selection')
                stages['selection'] = 'verified'
                reviewed = _read_review(store, selected['evaluation_sha256'])
                if (reviewed['dataset_sha256'] != registry['dataset_sha256']
                        or reviewed['candidate'] != registry['candidate_model']
                        or (imported is not None and
                            reviewed['candidate_digest'] != imported['candidate_digest'])):
                    raise LineageAuditError('Review disagrees with model lineage')
                stages['evaluation'] = 'verified'
            except _EXPECTED_ERRORS:
                if stages['selection'] != 'verified':
                    stages['selection'] = 'invalid'
                stages['evaluation'] = 'invalid'
                reviewed = None

        # Stage 5: Current routing is only verifiable if it points to this
        # exact run and its digest/selection matches the reviewed evidence.
        runtime_cp = store.get_checkpoint('ollama_runtime')
        runtime_state = runtime_cp['state'] if runtime_cp is not None else {}
        if runtime_state.get('active_run_id') != run_id:
            stages['routing'] = 'not-active'
        elif reviewed is None or imported is None:
            stages['routing'] = 'incomplete-lineage'
        else:
            try:
                _check_lineage(store, runtime_state)
                if (runtime_state.get('active_tag') != registry['candidate_model']
                        or runtime_state.get('active_digest') != imported['candidate_digest']
                        or runtime_state.get('evaluation_sha256') !=
                            selected_state.get('evaluation_sha256')
                        or runtime_state.get('baseline_tag') != reviewed['baseline']
                        or runtime_state.get('baseline_digest') != reviewed['baseline_digest']):
                    raise LineageAuditError('Runtime evidence does not match reviewed import')
                stages['routing'] = 'verified'
            except _EXPECTED_ERRORS:
                stages['routing'] = 'invalid'

        # The sole optional external lookup. Never claim installed model
        # verification from a database fingerprint alone.
        if not check_ollama:
            stages['ollama_candidate'] = 'not-checked'
        elif imported is None or reviewed is None:
            stages['ollama_candidate'] = 'not-eligible'
        else:
            try:
                actual = model_digest(registry['candidate_model'])
                stages['ollama_candidate'] = (
                    'verified' if actual == imported['candidate_digest']
                    and actual == reviewed['candidate_digest'] else 'digest-mismatch')
            except _EXPECTED_ERRORS:
                stages['ollama_candidate'] = 'unavailable-or-invalid'

    complete_local = all(stages[k] == 'verified' for k in (
        'adapter', 'conversion', 'import', 'evaluation', 'selection', 'routing'))
    inventory_match = stages['ollama_candidate'] == 'verified'
    if stages['adapter'] != 'verified':
        next_step = 'review-adapter-registration-and-consent'
    elif stages['conversion'] == 'invalid' or stages['import'] == 'invalid':
        next_step = 'review-tampered-or-stale-conversion-import'
    elif stages['conversion'] == 'not-complete':
        next_step = 'complete-or-recover-local-conversion'
    elif stages['import'] != 'verified':
        next_step = 'review-and-complete-local-model-import'
    elif stages['evaluation'] != 'verified' or stages['selection'] != 'verified':
        next_step = 'review-model-comparison-and-selection'
    elif stages['routing'] != 'verified':
        next_step = 'review-current-runtime-routing'
    elif stages['conversion'] != 'verified':
        next_step = 'manual-merge-is-not-locally-conversion-verified'
    elif not check_ollama:
        next_step = 'check-loopback-candidate-inventory'
    elif not inventory_match:
        next_step = 'review-installed-candidate-digest'
    else:
        next_step = 'all-recorded-local-stages-current'

    return {
        'schema': 1, 'type': 'read-only-model-lineage-audit',
        'stages': stages,
        'provenance': evidence['provenance'],
        'complete_local_record_chain': complete_local,
        'installed_candidate_digest_matches': inventory_match,
        'all_recorded_local_stages_current': complete_local and inventory_match,
        'independently_proven_model_derivation': False,
        'next_step': next_step,
        'model_called': False, 'training_started': False,
        'routing_changed': False, 'model_imported': False,
        'promotion_authorized': False, 'private_text_returned': False,
    }
