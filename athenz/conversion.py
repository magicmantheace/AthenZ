"""Explicit offline PEFT-to-merged-GGUF conversion for reviewed private adapters.

This is *not* a sandbox. The caller explicitly trusts their installed Python,
transformers/PEFT packages and a fingerprint-pinned local llama.cpp converter.
No downloads, remote publishing, automatic model creation, or routing occur.

The full FP16 Qwen model is assembled on CPU, which may need substantially more
host RAM than the 12 GB target GPU. Real hardware integration is not verified.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from .adapters import verified_registry_entry
from .experience import ExperienceStore
from .finetune import RUN_ID, file_sha256, verify_run
from .ollama_import import _source_gguf
from .training import _private_root, _write_new

SHA = re.compile(r'[0-9a-f]{64}\Z')
MAX_SCRIPT_BYTES = 4 * 1024 * 1024
MAX_ATTEMPTS = 3


class ConversionError(ValueError):
    """Conversion scope, consent, prerequisites or output evidence is invalid."""


def _converter(path: Path, expected_sha256: str) -> Path:
    """Pin a *reviewed* local Python script; never look up or download one."""
    if not isinstance(expected_sha256, str) or not SHA.fullmatch(expected_sha256):
        raise ConversionError('Converter must have an explicitly supplied SHA-256')
    candidate = Path(path).expanduser()
    if candidate.is_symlink() or not candidate.is_file() or candidate.suffix != '.py':
        raise ConversionError('Converter must be a regular non-symlink local Python file')
    candidate = candidate.resolve(strict=True)
    if candidate.stat().st_size < 32 or candidate.stat().st_size > MAX_SCRIPT_BYTES:
        raise ConversionError('Converter size outside permitted range')
    if file_sha256(candidate) != expected_sha256:
        raise ConversionError('Converter source digest differs from approved script')
    return candidate


def _folder(store: ExperienceStore, run_id: str) -> Path:
    if not RUN_ID.fullmatch(run_id):
        raise ConversionError('Invalid private training run ID')
    root = _private_root(store).parent / 'conversions'
    if root.is_symlink():
        raise ConversionError('Conversion storage cannot be symlinked')
    root.mkdir(mode=0o700, exist_ok=True)
    if root.resolve(strict=True) != root:
        raise ConversionError('Invalid private conversion directory')
    dest = root / ('merge-' + run_id)
    if dest.is_symlink():
        raise ConversionError('Conversion directory cannot be symlinked')
    return dest


def _sources(store: ExperienceStore, run_id: str, state: dict) -> tuple[dict, Path]:
    entry = verified_registry_entry(store, run_id)
    recipe, run, _ = verify_run(store, run_id)
    if run['status'] != 'complete':
        raise ConversionError('Training run must be complete')
    if (entry['artifact_sha256'] != state['adapter_artifact_sha256']
            or entry['dataset_sha256'] != state['dataset_sha256']
            or entry['base_fingerprint'] != state['base_fingerprint']):
        raise ConversionError('Approved adapter/base/dataset lineage changed')
    script = _converter(Path(state['converter']), state['converter_sha256'])
    return recipe, script


def prepare_conversion(store: ExperienceStore, run_id: str, converter: Path, *,
                       converter_sha256: str, confirmed: bool = False,
                       trust_converter: bool = False) -> dict:
    """Freeze a reviewed conversion plan; does not execute Python or touch weights."""
    if not confirmed or not trust_converter:
        raise ConversionError('Require --confirm and --trust-converter; this script executes on the host')
    entry = verified_registry_entry(store, run_id)
    script = _converter(converter, converter_sha256)
    key = 'convert_' + run_id
    state = {'run_id': run_id, 'adapter_artifact_sha256': entry['artifact_sha256'],
             'dataset_sha256': entry['dataset_sha256'], 'base_fingerprint': entry['base_fingerprint'],
             'converter': str(script), 'converter_sha256': converter_sha256,
             'format': 'qwen2-merged-f16-gguf', 'attempts': 0, 'artifact': None,
             'deployment': 'not-imported'}
    prior = store.get_checkpoint(key)
    if prior is not None:
        if {k: prior['state'].get(k) for k in state if k not in ('attempts','artifact')} != {
                k: state[k] for k in state if k not in ('attempts','artifact')}:
            raise ConversionError('Existing conversion recipe is immutable')
        _sources(store, run_id, prior['state'])
        return conversion_status(store, run_id)
    directory = _folder(store, run_id)
    if directory.exists():
        raise ConversionError('Existing partial output directory needs manual review')
    # The actual attempt directory is allocated only by execute_conversion.
    store.checkpoint(key, 'Owner-reviewed offline adapter/FF16 GGUF conversion', state,
                     status='queued')
    return conversion_status(store, run_id)


def _cpu_merge(recipe: dict, adapter_path: Path, destination: Path) -> None:
    """Merge full-precision PEFT weights on CPU. May need significant system RAM."""
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import PeftModel
    except ImportError as exc:
        raise ConversionError('Install trusted local CPU PyTorch, transformers and PEFT packages') from exc
    base = recipe['base']['path']
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True,
                                               trust_remote_code=False, use_fast=True)
    model = AutoModelForCausalLM.from_pretrained(
        base, local_files_only=True, trust_remote_code=False,
        torch_dtype=torch.float16, device_map='cpu', low_cpu_mem_usage=True)
    model = PeftModel.from_pretrained(model, str(adapter_path), is_trainable=False,
                                    local_files_only=True)
    merged = model.merge_and_unload(safe_merge=True)
    if not destination.is_dir():
        raise ConversionError('Expected private merged-model destination')
    merged.save_pretrained(str(destination), safe_serialization=True, max_shard_size='2GB')
    tokenizer.save_pretrained(str(destination))


def _backend(recipe: dict, adapter_path: Path, converter: Path, directory: Path) -> Path:
    """Run fixed merge+conversion stages offline; no downloaded executables."""
    merged = directory / 'merged-hf'
    merged.mkdir(mode=0o700)
    _cpu_merge(recipe, adapter_path, merged)
    target = directory / 'merged-f16.gguf'
    env = {k:v for k,v in os.environ.items() if k.upper() not in {
        'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','OLLAMA_HOST','HF_TOKEN','HUGGING_FACE_HUB_TOKEN'}}
    env.update({'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
                'HF_DATASETS_OFFLINE': '1', 'NO_PROXY': '*', 'PYTHONNOUSERSITE': '1'})
    argv = [sys.executable, '-I', str(converter), str(merged),
            '--outfile', str(target), '--outtype', 'f16']
    try:
        finished = subprocess.run(argv, cwd=directory, env=env, timeout=7200,
                                  capture_output=True, check=False, text=True, errors='replace')
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConversionError('Trusted local converter failed or timed out; see private attempt') from exc
    if finished.returncode != 0:
        raise ConversionError('Trusted local converter returned nonzero; see private attempt')
    return target


def pause_conversion(store: ExperienceStore, run_id: str, *,
                     confirmed: bool = False) -> dict:
    """Owner revokes conversion checkpoint authority without activating a model.

    The CPU process may continue until the current backend returns. The old
    worker's revision fence prevents its output from being adopted. Resuming
    always creates a NEW attempt and requires a fresh explicit owner action.
    """
    if not confirmed:
        raise ConversionError('Explicit --confirm required to pause conversion')
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise ConversionError('Invalid private conversion run ID')
    key = 'convert_' + run_id
    item = store.get_checkpoint(key)
    if item is None:
        raise ConversionError('Unknown reviewed conversion')
    if item['status'] in {'complete', 'failed'}:
        raise ConversionError('Completed/failed conversion cannot be paused')
    if item['status'] not in {'queued', 'running', 'paused'}:
        raise ConversionError('Conversion cannot be paused in its current state')
    if item['status'] != 'paused':
        store.checkpoint(key, item['task'], item['state'], status='paused',
                         expected_revision=item['revision'])
    after = store.get_checkpoint(key)
    return {'run_id': run_id, 'status': 'paused', 'revision': after['revision'],
            'backend_interrupted': False, 'output_adopted': False,
            'resume_requires_confirmation': True}


def execute_conversion(store: ExperienceStore, run_id: str, *, confirmed: bool = False,
                       resume: bool = False, backend=None) -> dict:
    """One explicit attempt; failed or crashed attempts require explicit --resume.

    Prior attempts are never overwritten or removed. A successful result is
    revalidated after CPU merge and conversion before it is recorded.
    """
    if not confirmed:
        raise ConversionError('Explicit --confirm required to merge and execute trusted local Python')
    key = 'convert_' + run_id
    cp = store.get_checkpoint(key)
    if cp is None:
        raise ConversionError('Prepare reviewed conversion first')
    if cp['status'] not in ({'running','failed','paused'} if resume else {'queued'}):
        raise ConversionError('Conversion is not resumable in this state; inspect existing attempts')
    state = dict(cp['state'])
    if state['attempts'] >= MAX_ATTEMPTS:
        raise ConversionError('Conversion attempt budget exhausted')
    recipe, script = _sources(store, run_id, state)
    root = _folder(store, run_id)
    root.mkdir(mode=0o700, exist_ok=True)
    attempt = state['attempts'] + 1
    target_dir = root / f'attempt-{attempt}'
    if target_dir.exists() or target_dir.is_symlink():
        raise ConversionError('Existing conversion attempt cannot be overwritten')
    target_dir.mkdir(mode=0o700)
    state['attempts'] = attempt
    state['artifact'] = None
    store.checkpoint(key, cp['task'], state, status='running', expected_revision=cp['revision'])
    running_revision = cp['revision'] + 1

    def current_authorized_checkpoint() -> dict:
        current = store.get_checkpoint(key)
        if (current is None or current['status'] != 'running'
                or current['revision'] != running_revision):
            raise ConversionError('Conversion authorization changed during execution')
        return current

    from .finetune import _run_path
    adapter_path = _run_path(store, run_id) / 'adapter'
    try:
        gguf = (backend or _backend)(recipe, adapter_path, script, target_dir)
        gguf = Path(gguf)
        if gguf != target_dir / 'merged-f16.gguf':
            raise ConversionError('Converter output path differs from private destination')
        _sources(store, run_id, state)  # consent and converter must remain unchanged
        path, sha, size = _source_gguf(gguf)
        state['artifact'] = {'path': str(path), 'sha256': sha, 'bytes': size,
                             'adapter_artifact_sha256': state['adapter_artifact_sha256'],
                             'converter_sha256': state['converter_sha256'],
                             'status': 'local-merge-claimed-not-gpu-verified'}
        current_authorized_checkpoint()
        # Completion uses the revision observed at launch, not the latest
        # revision: a concurrent pause or new owner run always wins the CAS.
        store.checkpoint(key, cp['task'], state, status='complete',
                         expected_revision=running_revision)
    except BaseException:
        # If the owner paused or another operation changed the checkpoint,
        # do not overwrite that new decision, even when a stale worker fails.
        current = store.get_checkpoint(key)
        if (current is not None and current['status'] == 'running'
                and current['revision'] == running_revision):
            try:
                store.checkpoint(key, current['task'], current['state'],
                                 status='failed', expected_revision=running_revision)
            except ValueError:
                pass  # A newer owner decision won the concurrent CAS.
        raise
    return conversion_status(store, run_id)


def conversion_status(store: ExperienceStore, run_id: str) -> dict:
    cp = store.get_checkpoint('convert_' + run_id)
    if cp is None:
        raise ConversionError('Unknown reviewed conversion')
    state = cp['state']
    _sources(store, run_id, state)
    artifact = state.get('artifact')
    if cp['status'] == 'complete':
        if not isinstance(artifact, dict):
            raise ConversionError('Completed conversion lacks artifact')
        path, sha, size = _source_gguf(Path(artifact['path']))
        if sha != artifact['sha256'] or size != artifact['bytes']:
            raise ConversionError('Merged GGUF changed after conversion')
    return {'run_id': run_id, 'status': cp['status'], 'attempts': state['attempts'],
            'converter_sha256': state['converter_sha256'],
            'artifact': artifact, 'deployment': 'not-imported',
            'lineage': 'local-conversion-observation-not-independent-attestation'}
