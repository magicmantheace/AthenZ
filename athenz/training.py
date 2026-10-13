"""Owner-controlled SFT dataset preparation; never trains a model.

Only reviewed training pairs are eligible. A deterministic manifest makes exports
reproducible and invalidatable when consent, source records, or content changes.
This module never talks to Ollama, a network, or a training runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata

from .experience import ExperienceStore


class DatasetError(ValueError):
    """A review, privacy, integrity, or readiness gate rejected the dataset."""


def normalized(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def _normalized_words(text: str) -> str:
    """Unicode/spacing/punctuation-insensitive words for held-out overlap only.

    Unlike the training-pair deduplication key, this does not alter answer
    punctuation or the exported training text.
    """
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def _protected_phrase_index(phrases: set[str]) -> dict[tuple[str, ...], list[tuple[str, ...]]]:
    """Compile distinctive held-out phrases once for linear-time export scans.

    A four-token prefix narrows candidates; the entire normalized phrase must
    still match consecutively, so sharing a common beginning is insufficient.
    """
    index: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for phrase in phrases:
        words = tuple(phrase.split())
        if len(words) >= 4 and sum(map(len, words)) >= 20:
            index.setdefault(words[:4], []).append(words)
    return index


def _distinctive_embedded(
        text_words: str,
        protected: dict[tuple[str, ...], list[tuple[str, ...]]]) -> bool:
    """Find exact normalized word-sequence overlaps without all-pairs scans."""
    tokens = tuple(text_words.split())
    for start in range(max(0, len(tokens) - 3)):
        for phrase in protected.get(tokens[start:start + 4], ()):
            if tokens[start:start + len(phrase)] == phrase:
                return True
    return False


def _near_overlap_index(protected: set[str]) -> dict[str, set[frozenset[str]]]:
    """Index long distinctive protected phrases for strong lexical similarity."""
    by_token: dict[str, set[frozenset[str]]] = {}
    for phrase in protected:
        tokens = frozenset(phrase.split())
        if len(tokens) < 8 or sum(map(len, tokens)) < 48:
            continue
        for token in tokens:
            if len(token) >= 5:
                by_token.setdefault(token, set()).add(tokens)
    return by_token


def _strong_near_overlap(text_words: str,
                         protected: dict[str, set[frozenset[str]]]) -> bool:
    """Conservative 88%-Jaccard near-match; never semantic inference."""
    words = frozenset(text_words.split())
    if len(words) < 8 or sum(map(len, words)) < 48:
        return False
    candidates: set[frozenset[str]] = set()
    for word in words:
        if len(word) >= 5:
            candidates.update(protected.get(word, ()))
    return any(100 * len(words & target) >= 88 * len(words | target)
               for target in candidates)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _private_root(store: ExperienceStore) -> Path:
    home = store.home.expanduser().resolve(strict=True)
    if any((p / '.git').exists() or (p / '.git').is_symlink()
           for p in (home, *home.parents)):
        raise DatasetError('ATHENZ_HOME must be outside any Git checkout')
    dest = home / 'datasets'
    if dest.is_symlink():
        raise DatasetError('Private dataset folder may not be a symlink')
    dest.mkdir(mode=0o700, exist_ok=True)
    if dest.resolve(strict=True) != dest:
        raise DatasetError('Private dataset folder is not secure')
    try:
        dest.chmod(0o700)
    except OSError:
        pass
    return dest


def _read_approved(store: ExperienceStore) -> tuple[list[tuple[int, str, str]], dict]:
    protected_rows = store.db.execute(
        "SELECT scenario,rationale FROM decisions WHERE split IN ('test','calibration')").fetchall()
    scenarios = [r['scenario'] for r in protected_rows]
    heldout = {normalized(scenario) for scenario in scenarios}
    heldout_words = {_normalized_words(scenario) for scenario in scenarios}
    rationale_words = {_normalized_words(r['rationale']) for r in protected_rows}
    protected_index = _protected_phrase_index(heldout_words | rationale_words)
    near_index = _near_overlap_index(heldout_words | rationale_words)
    rows = store.db.execute('''SELECT id,instruction,ideal_answer FROM train_pairs
                               WHERE status='approved' ORDER BY id''').fetchall()
    if len(rows) > 50_000:
        raise DatasetError('Too many approved rows for a single export')
    selected: list[tuple[int, str, str]] = []
    by_instruction: dict[str, tuple[str, int]] = {}
    duplicated = withheld = conflicts = 0
    for r in rows:
        instruction, answer = r['instruction'], r['ideal_answer']
        key, target = normalized(instruction), normalized(answer)
        if not key or not target or len(instruction) > 20_000 or len(answer) > 20_000:
            raise DatasetError('Reviewed pair is empty or oversized; correct source entry')
        instruction_words = _normalized_words(instruction)
        answer_words = _normalized_words(answer)
        if (key in heldout or instruction_words in heldout_words
                or _distinctive_embedded(instruction_words, protected_index)
                or _distinctive_embedded(answer_words, protected_index)
                or _strong_near_overlap(instruction_words, near_index)
                or _strong_near_overlap(answer_words, near_index)):
            withheld += 1
            continue
        prior = by_instruction.get(key)
        if prior is not None:
            if prior[0] != target:
                conflicts += 1
            else:
                duplicated += 1
            continue
        by_instruction[key] = (target, r['id'])
        selected.append((r['id'], instruction, answer))
    return selected, {'approved': len(rows), 'included': len(selected), 'duplicates': duplicated,
                      'heldout_excluded': withheld, 'conflicts': conflicts,
                      'heldout_scenarios': len(heldout)}


def inspect_dataset(store: ExperienceStore) -> dict:
    """Non-sensitive readiness report, without including owner text."""
    _, report = _read_approved(store)
    return report


def _render(rows: list[tuple[int, str, str]]) -> bytes:
    return b''.join((json.dumps({'messages': [
        {'role': 'user', 'content': prompt},
        {'role': 'assistant', 'content': answer}
    ]}, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
        for _, prompt, answer in rows)


def _write_new(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _paths(store: ExperienceStore, sha: str) -> tuple[Path, Path]:
    if not re.fullmatch(r'[a-f0-9]{64}', sha):
        raise DatasetError('Invalid SHA-256 dataset identifier')
    root = _private_root(store)
    name = 'sft-' + sha
    return root / (name + '.jsonl'), root / (name + '.manifest.json')


def build_dataset(store: ExperienceStore, *, confirmed: bool = False) -> dict:
    """Write immutable private JSONL and metadata; requires explicit owner action."""
    if not confirmed:
        raise DatasetError('Explicit --confirm is required; inspect sources first')
    rows, report = _read_approved(store)
    if report['conflicts']:
        raise DatasetError(f"{report['conflicts']} conflicting approved instruction(s); review sources")
    if not rows:
        raise DatasetError('No eligible approved training examples')
    payload = _render(rows)
    sha = _digest(payload)
    data, metadata = _paths(store, sha)
    manifest = {'schema': 1, 'type': 'reviewed-sft', 'sha256': sha,
                'bytes': len(payload), 'count': len(rows), 'source_ids': [r[0] for r in rows],
                'status': 'snapshot-only-not-trained'}
    manifest_bytes = (json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    if data.exists() or metadata.exists() or data.is_symlink() or metadata.is_symlink():
        # Repeated exports can reuse immutable, still-valid bytes; never overwrite.
        verify_dataset(store, sha)
        return {'sha256': sha, 'count': len(rows), 'reused': True,
                'path': str(data), 'manifest': str(metadata), **report}
    _write_new(data, payload)
    try:
        _write_new(metadata, manifest_bytes)
    except BaseException:
        data.unlink(missing_ok=True)
        raise
    return {'sha256': sha, 'count': len(rows), 'reused': False,
            'path': str(data), 'manifest': str(metadata), **report}


def verify_dataset(store: ExperienceStore, sha: str) -> dict:
    """Recheck approval, provenance set and bytes before any future training run."""
    data, meta = _paths(store, sha)
    if data.is_symlink() or meta.is_symlink() or not data.is_file() or not meta.is_file():
        raise DatasetError('Dataset or manifest is missing or symlinked')
    manifest = json.loads(meta.read_text('utf-8'))
    if manifest.get('schema') != 1 or manifest.get('sha256') != sha:
        raise DatasetError('Unrecognized dataset manifest')
    payload = data.read_bytes()
    if _digest(payload) != sha or len(payload) != manifest.get('bytes'):
        raise DatasetError('Private dataset content has changed')
    rows, report = _read_approved(store)
    if report['conflicts'] or _render(rows) != payload or [r[0] for r in rows] != manifest.get('source_ids'):
        raise DatasetError('Dataset is stale: source consent/content or held-out examples changed')
    return {'valid': True, 'sha256': sha, 'count': len(rows), **report}


def delete_dataset(store: ExperienceStore, sha: str, *, confirmed: bool = False) -> bool:
    """Remove only an AthenZ-named local dataset; never delete arbitrary paths."""
    if not confirmed:
        raise DatasetError('Explicit --confirm required to delete a private dataset')
    data, manifest = _paths(store, sha)
    # Do not chase symlinks; unlink AthenZ's own named entries only.
    existed = False
    for path in (data, manifest):
        if path.exists() or path.is_symlink():
            path.unlink()
            existed = True
    return existed
