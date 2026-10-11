"""Owner-approved *merged GGUF model* handoff to local Ollama.

Ollama's current documented import route is `FROM /path/to/model.gguf`.
This module NEVER pretends a PEFT Qwen LoRA adapter is directly importable.
A person must merge/convert externally and affirm lineage; our SHA-256 links
observed bytes, not a cryptographic proof of the originating adapter.
No model is selected for AthenZ and no remote/push/delete command is exposed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .adapters import ALIAS, verified_registry_entry
from .experience import ExperienceStore
from .finetune import RUN_ID
from .runtime import model_digest
from .training import _private_root, _write_new

MAX_GGUF_BYTES = 24 * 1024**3
OLLAMA_LOCAL = 'http://127.0.0.1:11434'
TAG = re.compile(r'athenz-[a-z0-9][a-z0-9_.-]{0,48}:[a-z0-9][a-z0-9_.-]{0,32}\Z')


class ImportErrorLocal(ValueError):
    """Local model import was denied or its evidence is unverifiable."""


def _source_gguf(path: Path) -> tuple[Path, str, int]:
    p = Path(path).expanduser()
    if p.is_symlink() or not p.is_file() or p.suffix.lower() != '.gguf':
        raise ImportErrorLocal('Select an existing regular, non-symlink merged GGUF file')
    p = p.resolve(strict=True)
    if not p.is_file() or p.is_symlink():
        raise ImportErrorLocal('Invalid GGUF path')
    size = p.stat().st_size
    if size < 32 or size > MAX_GGUF_BYTES:
        raise ImportErrorLocal('GGUF size is missing or exceeds 24 GiB')
    with p.open('rb') as stream:
        header = stream.read(8)
    if header[:4] != b'GGUF' or int.from_bytes(header[4:8], 'little') not in (2, 3):
        raise ImportErrorLocal('GGUF header/version is unsupported (expected v2/v3)')
    sha = hashlib.sha256()
    with p.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(chunk)
    if p.stat().st_size != size:
        raise ImportErrorLocal('GGUF changed while being fingerprinted')
    return p, sha.hexdigest(), size


def _modelfile_path(path: Path) -> str:
    # Use JSON quoting for spaces/backslashes; forbid control characters and
    # quote tricks. Compatibility on all host OSes is not yet hardware-tested.
    raw = str(path)
    if len(raw) > 1000 or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ImportErrorLocal('Model path contains unsafe characters')
    return json.dumps(raw, ensure_ascii=True)


def _conversion_lineage(store: ExperienceStore, run_id: str, gguf_sha: str) -> str:
    """Prefer observed local conversion when available; never infer successful lineage.

    An interrupted/failed conversion must not be silently bypassed by a new
    manual import, and recorded output must be the exact reviewed GGUF bytes.
    """
    cp = store.get_checkpoint('convert_' + run_id)
    if cp is None:
        return 'owner-attested-merge-not-independently-proven'
    from .conversion import conversion_status
    try:
        observed = conversion_status(store, run_id)
    except (ValueError, OSError) as exc:
        raise ImportErrorLocal('Local conversion evidence is not verifiable') from exc
    if (observed['status'] != 'complete' or not observed['artifact']
            or observed['artifact']['sha256'] != gguf_sha):
        raise ImportErrorLocal('GGUF does not match a completed local conversion')
    return 'owner-attested-and-local-conversion-observed-not-independently-proven'


def _verified_source(store: ExperienceStore, run_id: str, state: dict) -> dict:
    entry = verified_registry_entry(store, run_id)
    if (entry['artifact_sha256'] != state['adapter_artifact_sha256']
            or entry['candidate_model'] != state['registry_candidate']
            or entry['dataset_sha256'] != state['dataset_sha256']
            or entry['base_fingerprint'] != state['base_fingerprint']):
        raise ImportErrorLocal('Adapter or owner approval changed since preparation')
    _, sha, size = _source_gguf(Path(state['gguf_path']))
    if sha != state['gguf_sha256'] or size != state['gguf_bytes']:
        raise ImportErrorLocal('Converted GGUF changed since owner review')
    if state.get('lineage') != _conversion_lineage(store, run_id, sha):
        raise ImportErrorLocal('GGUF provenance changed since preparation')
    recipe = (f"FROM {_modelfile_path(Path(state['gguf_path']))}\n").encode('utf-8')
    file = Path(state['modelfile'])
    if file.is_symlink() or not file.is_file() or file.read_bytes() != recipe:
        raise ImportErrorLocal('Private Modelfile was modified or removed')
    if hashlib.sha256(recipe).hexdigest() != state['modelfile_sha256']:
        raise ImportErrorLocal('Modelfile fingerprint mismatch')
    return entry


def prepare_import(store: ExperienceStore, run_id: str, gguf_path: Path,
                   *, candidate_tag: str, confirmed: bool = False,
                   acknowledge_merge: bool = False) -> dict:
    """Stage a private immutable local-only Modelfile. DOES NOT invoke Ollama."""
    if not confirmed or not acknowledge_merge:
        raise ImportErrorLocal('Require --confirm and --ack-merge to record manual lineage')
    if not RUN_ID.fullmatch(run_id):
        raise ImportErrorLocal('Invalid private training run ID')
    if not TAG.fullmatch(candidate_tag) or not ALIAS.fullmatch(candidate_tag):
        raise ImportErrorLocal('Use a dedicated athenz/name:tag candidate name')
    entry = verified_registry_entry(store, run_id)
    if entry['candidate_model'] != candidate_tag:
        raise ImportErrorLocal('Candidate tag must match the registered adapter label')
    path, digest, size = _source_gguf(gguf_path)
    recipe = f'FROM {_modelfile_path(path)}\n'.encode('utf-8')
    root = _private_root(store) / 'ollama-imports'
    if root.is_symlink():
        raise ImportErrorLocal('Private import directory is symlinked')
    root.mkdir(mode=0o700, exist_ok=True)
    if root.resolve(strict=True) != root:
        raise ImportErrorLocal('Unsafe private import directory')
    modelfile = root / f'import-{run_id}-{digest[:16]}.Modelfile'
    state = {'run_id': run_id, 'gguf_path': str(path), 'gguf_sha256': digest,
             'gguf_bytes': size, 'adapter_artifact_sha256': entry['artifact_sha256'],
             'dataset_sha256': entry['dataset_sha256'], 'base_fingerprint': entry['base_fingerprint'],
             'registry_candidate': entry['candidate_model'], 'candidate_tag': candidate_tag,
             'modelfile': str(modelfile), 'modelfile_sha256': hashlib.sha256(recipe).hexdigest(),
             'lineage': _conversion_lineage(store, run_id, digest),
             'format': 'complete-merged-gguf-model', 'deployment': 'not-imported'}
    key = 'ollama_import_' + run_id
    old = store.get_checkpoint(key)
    if old is not None:
        # Do not reset an earlier completed or partially attempted import.
        original = {k: v for k, v in old['state'].items() if k in state}
        if original != state:
            raise ImportErrorLocal('Prepared import is immutable; cannot replace it')
        _verified_source(store, run_id, old['state'])
        return {**old['state'], 'revision': old['revision'], 'status': old['status']}
    # O_EXCL; never overwrite a formerly generated file. No arbitrary destinations.
    _write_new(modelfile, recipe)
    try:
        cp_id = store.checkpoint(key, 'Owner-reviewed merged-GGUF import handoff', state,
                                 status='paused')
    except BaseException:
        modelfile.unlink(missing_ok=True)
        raise
    return {**state, 'revision': 1, 'status': 'paused', 'checkpoint_id': cp_id}


def verify_import(store: ExperienceStore, run_id: str, *, verify_ollama: bool = False,
                  endpoint: str | None = None) -> dict:
    if not RUN_ID.fullmatch(run_id):
        raise ImportErrorLocal('Invalid run ID')
    cp = store.get_checkpoint('ollama_import_' + run_id)
    if cp is None:
        raise ImportErrorLocal('Unknown prepared import')
    state = cp['state']
    _verified_source(store, run_id, state)
    if verify_ollama and cp['status'] != 'complete':
        raise ImportErrorLocal('Model has not been imported into local Ollama')
    if endpoint is not None and endpoint != OLLAMA_LOCAL:
        raise ImportErrorLocal('Import evidence may only use the fixed local Ollama server')
    if cp['status'] == 'complete' and verify_ollama:
        if model_digest(state['candidate_tag'], endpoint=OLLAMA_LOCAL) != state['candidate_digest']:
            raise ImportErrorLocal('Local Ollama candidate tag has changed')
    return {'run_id': run_id, 'candidate_tag': state['candidate_tag'],
            'gguf_sha256': state['gguf_sha256'], 'status': cp['status'],
            'revision': cp['revision'], 'lineage': state['lineage'],
            'candidate_digest': state.get('candidate_digest'),
            'deployment': state['deployment']}


def _not_installed(tag: str, *, endpoint: str | None) -> None:
    """Fail closed for broken inventory, including malformed existing tag rows."""
    from urllib.error import HTTPError, URLError
    from urllib.request import Request, ProxyHandler, build_opener
    from .chat import OllamaClient
    from .runtime import _NoRedirect

    client = OllamaClient(endpoint=endpoint, model=tag)
    req = Request(client.endpoint + '/api/tags', method='GET')
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(req, timeout=8) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ImportErrorLocal('Local Ollama inventory exceeds size bound')
        obj = json.loads(raw)
        entries = obj['models']
        if not isinstance(entries, list) or len(entries) > 10000:
            raise ValueError('Invalid local tag inventory')
    except (HTTPError, URLError, OSError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        raise ImportErrorLocal('Could not safely verify local Ollama tag inventory') from exc
    canonical = tag if ':' in tag else tag + ':latest'
    for entry in entries:
        if not isinstance(entry, dict):
            raise ImportErrorLocal('Malformed Ollama inventory entry')
        if entry.get('name') == canonical or entry.get('model') == canonical:
            raise ImportErrorLocal('Candidate tag already exists; refusing to overwrite it')


def import_local(store: ExperienceStore, run_id: str, *, confirmed: bool = False,
                 endpoint: str | None = None, timeout: int = 1200) -> dict:
    """Explicit `ollama create` for a FULL merged GGUF. Never activates it."""
    if not confirmed:
        raise ImportErrorLocal('Require --confirm before local Ollama model creation')
    if not isinstance(timeout, int) or not 60 <= timeout <= 3600:
        raise ImportErrorLocal('Import timeout must be 60..3600 seconds')
    if not RUN_ID.fullmatch(run_id):
        raise ImportErrorLocal('Invalid run ID')
    key = 'ollama_import_' + run_id
    cp = store.get_checkpoint(key)
    if cp is None:
        raise ImportErrorLocal('Prepare the reviewed import first')
    state = dict(cp['state'])
    _verified_source(store, run_id, state)
    if cp['status'] == 'complete':
        return verify_import(store, run_id, verify_ollama=True, endpoint=endpoint)
    if cp['status'] != 'paused' or state.get('deployment') != 'not-imported':
        raise ImportErrorLocal('Import is already underway or requires manual recovery')
    if not shutil.which('ollama'):
        raise ImportErrorLocal('Local Ollama executable unavailable')
    # Local-only enforced by explicit host and preflight inventory. Custom
    # endpoints are not supported for CLI create; avoid a remote host entirely.
    if endpoint is not None:
        raise ImportErrorLocal('Custom Ollama endpoint not supported for model creation')
    _not_installed(state['candidate_tag'], endpoint=OLLAMA_LOCAL)
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in {'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY',
                                'OLLAMA_HOST','OLLAMA_MODELS'}}
    env['OLLAMA_HOST'] = '127.0.0.1:11434'
    # Record intent BEFORE invoking process. If a crash occurs, do not reuse
    # the candidate name or silently retry; the operator must reconcile it.
    state['deployment'] = 'create-in-progress'
    store.checkpoint(key, cp['task'], state, status='running',
                     expected_revision=cp['revision'])
    argv = ['ollama', 'create', state['candidate_tag'], '-f', state['modelfile']]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, check=False,
                              timeout=timeout, env=env, errors='replace')
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ImportErrorLocal('Ollama create interrupted; inspect candidate tag before recovery') from exc
    if proc.returncode != 0:
        raise ImportErrorLocal('Ollama create failed; inspect local server; no automatic retry or deletion')
    # If bytes/consent changed during import, the candidate must NOT route.
    _verified_source(store, run_id, state)
    candidate_sha = model_digest(state['candidate_tag'], endpoint=OLLAMA_LOCAL)
    current = store.get_checkpoint(key)
    state['candidate_digest'] = candidate_sha
    state['deployment'] = 'created-local-not-selected'
    store.checkpoint(key, cp['task'], state, status='complete',
                     expected_revision=current['revision'])
    return verify_import(store, run_id, verify_ollama=True)
