"""Explicit, offline QLoRA training for a local Qwen2-family safetensors model.

The heavyweight backend is optional and imported only after all consent and
provenance checks. No downloads, implicit training, model selection or upload.
A worker crash leaves a recoverable private run; explicit --resume is required.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import secrets

from .experience import ExperienceStore
from .training import DatasetError, _private_root, _write_new, verify_dataset

RUN_ID = re.compile(r"[a-f0-9]{24}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
MAX_MODEL_BYTES = 12 * 1024**3
MAX_EXAMPLES = 50_000


class TrainingError(RuntimeError):
    """Refused unsafe training launch or mismatched private run state."""


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as fp:
        for block in iter(lambda: fp.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def _model_snapshot(model_dir: Path) -> dict:
    """Fingerprint exact local config, tokenizer and safetensors weights."""
    if model_dir.is_symlink() or not model_dir.is_dir():
        raise TrainingError('Base model must be an existing non-symlink directory')
    root = model_dir.resolve(strict=True)
    config_path = root / 'config.json'
    if config_path.is_symlink() or not config_path.is_file():
        raise TrainingError('Local model config.json missing or symlinked')
    try:
        config = json.loads(config_path.read_text('utf-8'))
    except (UnicodeError, ValueError) as exc:
        raise TrainingError('Invalid local model config') from exc
    if config.get('model_type') != 'qwen2':
        raise TrainingError('Only the reviewed Qwen2/Qwen2.5 local architecture is supported')
    if not (root / 'tokenizer.json').is_file() or (root / 'tokenizer.json').is_symlink():
        raise TrainingError('Fast local tokenizer.json is required')
    weights = sorted(root.glob('*.safetensors'))
    if not weights or len(weights) > 24:
        raise TrainingError('Expected 1-24 local safetensors model shards')
    files = [config_path, root / 'tokenizer.json', *weights]
    for name in ('tokenizer_config.json', 'special_tokens_map.json', 'generation_config.json', 'model.safetensors.index.json'):
        if (root / name).exists() or (root / name).is_symlink():
            files.append(root / name)
    total = 0
    entries = []
    for file in sorted(files, key=lambda f: f.name):
        if file.is_symlink() or not file.is_file():
            raise TrainingError('Symlink or irregular base-model file is not allowed')
        size = file.stat().st_size
        total += size
        if size > 8 * 1024**3 or total > MAX_MODEL_BYTES:
            raise TrainingError('Base model exceeds supported local resource limit')
        entries.append({'name': file.name, 'bytes': size, 'sha256': file_sha256(file)})
    fingerprint = hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'path': str(root), 'model_type': 'qwen2', 'files': entries,
            'fingerprint': fingerprint, 'bytes': total}


def _runs_dir(store: ExperienceStore) -> Path:
    root = _private_root(store).parent / 'runs'
    if root.is_symlink():
        raise TrainingError('Private runs folder cannot be a symlink')
    root.mkdir(mode=0o700, exist_ok=True)
    if root.resolve() != root:
        raise TrainingError('Private runs folder is unsafe')
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def _run_path(store: ExperienceStore, run_id: str) -> Path:
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise TrainingError('Invalid run ID')
    root = _runs_dir(store)
    path = root / ('qlora-' + run_id)
    if path.is_symlink():
        raise TrainingError('Private run must not be a symlink')
    return path


def create_run(store: ExperienceStore, dataset_sha256: str, model_dir: Path, *,
               max_steps: int = 80, seq_length: int = 512, seed: int = 42,
               confirmed: bool = False) -> dict:
    """Immutable, bounded private training recipe; not a training launch."""
    if not confirmed:
        raise TrainingError('Explicit --confirm required to prepare a training run')
    if not SHA.fullmatch(dataset_sha256):
        raise TrainingError('Invalid dataset SHA-256')
    if not 1 <= max_steps <= 500 or not 128 <= seq_length <= 1024 or not 0 <= seed < 2**32:
        raise TrainingError('Training bounds: steps 1..500, sequence 128..1024, seed uint32')
    verified = verify_dataset(store, dataset_sha256)
    if not 1 <= verified['count'] <= MAX_EXAMPLES:
        raise TrainingError('Invalid approved dataset size')
    base = _model_snapshot(Path(model_dir).expanduser())
    run_id = secrets.token_hex(12)
    run_path = _run_path(store, run_id)
    run_path.mkdir(mode=0o700)
    recipe = {'schema': 1, 'run_id': run_id, 'dataset_sha256': dataset_sha256,
              'base': base, 'max_steps': max_steps, 'seq_length': seq_length, 'seed': seed,
              'lora_r': 8, 'lora_alpha': 16, 'lora_dropout': 0.05,
              'gradient_accumulation': 8, 'micro_batch': 1, 'checkpoint_steps': 25,
              'quantization': 'nf4-4bit', 'trainer': 'local-qwen2-qlora',
              'promotion': 'not-authorized', 'state': 'prepared'}
    content = (json.dumps(recipe, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    try:
        _write_new(run_path / 'recipe.json', content)
        store.checkpoint('train_' + run_id, 'Private owner-approved QLoRA run',
                         {'run_id': run_id, 'recipe_sha256': hashlib.sha256(content).hexdigest(),
                          'dataset_sha256': dataset_sha256}, status='queued')
    except BaseException:
        # No personal records are exported to logs or Git; leave possible
        # partial private run available for explicit inspection/recovery.
        raise
    return {'run_id': run_id, 'recipe_sha256': hashlib.sha256(content).hexdigest(),
            'dataset_sha256': dataset_sha256, 'base_fingerprint': base['fingerprint'],
            'max_steps': max_steps, 'state': 'prepared', 'training_started': False}


def verify_run(store: ExperienceStore, run_id: str) -> tuple[dict, dict, Path]:
    run_path = _run_path(store, run_id)
    recipe_file = run_path / 'recipe.json'
    if recipe_file.is_symlink() or not recipe_file.is_file():
        raise TrainingError('Private recipe missing or symlinked')
    body = recipe_file.read_bytes()
    try:
        recipe = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise TrainingError('Invalid private recipe') from exc
    checkpoint = store.get_checkpoint('train_' + run_id)
    if (checkpoint is None or recipe.get('schema') != 1 or recipe.get('run_id') != run_id
            or hashlib.sha256(body).hexdigest() != checkpoint['state'].get('recipe_sha256')):
        raise TrainingError('Recipe and checkpoint provenance disagree')
    verify_dataset(store, recipe['dataset_sha256'])
    if _model_snapshot(Path(recipe['base']['path'])) != recipe['base']:
        raise TrainingError('Base-model weights/config changed after preparation')
    return recipe, checkpoint, run_path


def encode_example(tokenizer, user: str, assistant: str, max_tokens: int) -> dict | None:
    """Supervised completion only: prompt tokens are never trained as targets."""
    conversation = [{'role': 'user', 'content': user}]
    prefix = tokenizer.apply_chat_template(conversation, tokenize=True, add_generation_prompt=True)
    whole = tokenizer.apply_chat_template(conversation + [{'role':'assistant','content':assistant}],
                                          tokenize=True, add_generation_prompt=False)
    if not isinstance(prefix, list) or not isinstance(whole, list) or whole[:len(prefix)] != prefix:
        raise TrainingError('Tokenizer lacks a safe and consistent chat template')
    if len(whole) > max_tokens or len(whole) <= len(prefix):
        return None
    return {'input_ids': whole, 'attention_mask': [1] * len(whole),
            'labels': [-100] * len(prefix) + whole[len(prefix):]}


def _train_backend(recipe: dict, run_path: Path, dataset_path: Path, *, resume: bool) -> dict:
    """Optional real GPU backend. Never imported by ordinary local CLI/tests."""
    try:
        import torch
        from transformers import (AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig,
                                  Trainer, TrainingArguments, TrainerCallback)
        from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training
    except ImportError as exc:
        raise TrainingError('Install trusted local CUDA PyTorch, transformers, peft, accelerate and bitsandbytes') from exc
    if not torch.cuda.is_available():
        raise TrainingError('CUDA GPU is required; never fall back to CPU training')
    if torch.cuda.get_device_properties(0).total_memory < 8 * 1024**3:
        raise TrainingError('Requires a GPU with at least 8 GiB VRAM')
    torch.cuda.set_per_process_memory_fraction(0.85, 0)
    torch.manual_seed(recipe['seed'])
    root = recipe['base']['path']
    tokenizer = AutoTokenizer.from_pretrained(root, local_files_only=True, trust_remote_code=False,
                                               use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        root, local_files_only=True, trust_remote_code=False,
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                               bnb_4bit_use_double_quant=True,
                                               bnb_4bit_compute_dtype=torch.float16),
        device_map={'': 0}, torch_dtype=torch.float16)
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(
        r=recipe['lora_r'], lora_alpha=recipe['lora_alpha'],
        lora_dropout=recipe['lora_dropout'], task_type=TaskType.CAUSAL_LM,
        target_modules=['q_proj','k_proj','v_proj','o_proj','gate_proj','up_proj','down_proj']))
    rows = []
    with dataset_path.open('r', encoding='utf-8') as stream:
        for line in stream:
            if not line.strip():
                continue
            parsed = json.loads(line)['messages']
            if len(parsed) != 2 or [m['role'] for m in parsed] != ['user', 'assistant']:
                raise TrainingError('Unexpected SFT row shape')
            encoded = encode_example(tokenizer, parsed[0]['content'],
                                     parsed[1]['content'], recipe['seq_length'])
            if encoded is not None:
                rows.append(encoded)
    if not rows:
        raise TrainingError('No examples fit the sequence length; increase it or edit examples')
    class Dataset:
        def __len__(self): return len(rows)
        def __getitem__(self, n): return rows[n]
    def collate(items):
        maximum = max(len(item['input_ids']) for item in items)
        def padded(name, value):
            return [item[name] + [value] * (maximum - len(item[name])) for item in items]
        return {'input_ids': torch.tensor(padded('input_ids', tokenizer.pad_token_id)),
                'attention_mask': torch.tensor(padded('attention_mask', 0)),
                'labels': torch.tensor(padded('labels', -100))}
    output = run_path / 'checkpoints'
    if output.is_symlink():
        raise TrainingError('Training checkpoint folder must not be symlinked')
    output.mkdir(mode=0o700, exist_ok=True)
    existing = sorted(p for p in output.glob('checkpoint-*') if p.is_dir() and not p.is_symlink())
    if resume and not existing:
        raise TrainingError('No checkpoint exists to resume')
    if not resume and existing:
        raise TrainingError('Checkpoints already exist; use explicit --resume')
    options = TrainingArguments(
        output_dir=str(output), max_steps=recipe['max_steps'],
        per_device_train_batch_size=recipe['micro_batch'],
        gradient_accumulation_steps=recipe['gradient_accumulation'],
        learning_rate=2e-4, warmup_ratio=0.03, lr_scheduler_type='cosine',
        save_strategy='steps', save_steps=recipe['checkpoint_steps'], save_total_limit=2,
        logging_steps=5, seed=recipe['seed'], data_seed=recipe['seed'],
        fp16=True, report_to='none', push_to_hub=False, dataloader_num_workers=0)
    trainer = Trainer(model=model, args=options, train_dataset=Dataset(), data_collator=collate)
    trainer.train(resume_from_checkpoint=True if resume else None)
    adapter_path = run_path / 'adapter'
    if adapter_path.exists() or adapter_path.is_symlink():
        raise TrainingError('Refusing to replace existing adapter')
    adapter_path.mkdir(mode=0o700)
    model.save_pretrained(str(adapter_path), safe_serialization=True)
    return {'examples_used': len(rows), 'adapter_dir': str(adapter_path),
            'steps': recipe['max_steps'], 'runtime': 'cuda-qlora-local'}


def execute_run(store: ExperienceStore, run_id: str, *, confirmed: bool = False,
                resume: bool = False, backend=None) -> dict:
    """Owner-triggered bounded training; no scheduler and no auto-promotion."""
    if not confirmed:
        raise TrainingError('Explicit --confirm required to begin training')
    recipe, item, run_path = verify_run(store, run_id)
    if item['status'] == 'complete':
        raise TrainingError('Completed run is immutable')
    if item['status'] not in ({'running','paused','failed'} if resume else {'queued'}):
        raise TrainingError('Run status requires explicit --resume or a new run')
    if (run_path / 'adapter').exists() or (run_path / 'adapter').is_symlink():
        raise TrainingError('Adapter exists; never silently overwrite')
    state = dict(item['state'])
    state['started'] = True
    key = 'train_' + run_id
    store.checkpoint(key, item['task'], state, status='running',
                     expected_revision=item['revision'])
    running_revision = item['revision'] + 1

    def current_running_checkpoint() -> dict:
        current = store.get_checkpoint(key)
        if (current is None or current['revision'] != running_revision
                or current['status'] != 'running'):
            raise TrainingError('Training authorization checkpoint changed during execution')
        return current

    data_path = _private_root(store) / ('sft-' + recipe['dataset_sha256'] + '.jsonl')
    try:
        result = (backend or _train_backend)(recipe, run_path, data_path, resume=resume)
        verify_run(store, run_id)  # consent and model may have changed during training
        if result.get('adapter_dir') != str(run_path / 'adapter'):
            raise TrainingError('Trainer returned an unexpected adapter destination')
        weights = run_path / 'adapter' / 'adapter_model.safetensors'
        if weights.is_symlink() or not weights.is_file():
            raise TrainingError('Trainer produced no safe safetensors adapter')
        if (type(result.get('examples_used')) is not int or
                not 1 <= result['examples_used'] <= MAX_EXAMPLES):
            raise TrainingError('Trainer returned an invalid number of examples')
        # Recheck the exact launch authority after long-running GPU work.
        current_running_checkpoint()
    except BaseException:
        # A concurrent owner pause/revision takes precedence; do not turn the
        # owner's newer checkpoint into a failed or completed run.
        now = store.get_checkpoint(key)
        if (now is not None and now['revision'] == running_revision
                and now['status'] == 'running'):
            try:
                store.checkpoint(key, now['task'], now['state'], status='failed',
                                 expected_revision=running_revision)
            except ValueError:
                pass  # concurrent owner update won its compare-and-swap
        raise
    now = current_running_checkpoint()
    state = dict(now['state'])
    state['adapter_sha256'] = file_sha256(weights)
    state['examples_used'] = result['examples_used']
    # Commit CAS detects a later pause even after the final authority check.
    store.checkpoint(key, now['task'], state, status='complete',
                     expected_revision=running_revision)
    return {'run_id': run_id, 'status': 'complete', 'adapter_sha256': state['adapter_sha256'],
            'examples_used': state['examples_used'], 'promotion': 'not-authorized'}


def describe_run(store: ExperienceStore, run_id: str) -> dict:
    recipe, item, _ = verify_run(store, run_id)
    return {'run_id': run_id, 'status': item['status'], 'revision': item['revision'],
            'base_fingerprint': recipe['base']['fingerprint'],
            'dataset_sha256': recipe['dataset_sha256'],
            'max_steps': recipe['max_steps'], 'adapter_sha256': item['state'].get('adapter_sha256'),
            'promotion': 'not-authorized'}
