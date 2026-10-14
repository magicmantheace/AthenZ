"""Reproducible, held-out local prediction evaluation for Twin decisions.

Gold choices and rationales never enter the prediction prompt. Approval and
reference snapshots must remain unchanged throughout inference; a revoked
case never yields a passing evaluation. This is not independent attestation.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from math import sqrt

from .store import IdentityStore
from .prompting import build_messages


def _wilson_interval(correct: int, total: int) -> list[float] | None:
    """95% binomial interval for descriptive reporting only."""
    if not total:
        return None
    z = 1.959963984540054
    p = correct / total
    d = 1.0 + z * z / total
    center = (p + z * z / (2 * total)) / d
    radius = z * sqrt(p * (1 - p) / total +
                      z * z / (4 * total * total)) / d
    return [max(0.0, center - radius), min(1.0, center + radius)]


def _normalized_overlap(phrase: str, reference: str) -> bool:
    """Conservative lexical collision check; NOT semantic similarity.

    Normalize Unicode compatibility forms, case, whitespace and punctuation.
    Require a sufficiently distinctive phrase before refusing evaluation;
    short/generic phrases are still checked by the exact literal guard.
    """
    def words(text: str) -> list[str]:
        # JSON-escaped line breaks may otherwise insert spurious 'n' tokens.
        text = text.replace('\\n', ' ').replace('\\t', ' ')
        return re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold())

    needle = words(phrase)
    if len(needle) < 4 or sum(map(len, needle)) < 20:
        return False
    haystack = ' ' + ' '.join(words(reference)) + ' '
    return (' ' + ' '.join(needle) + ' ') in haystack


def _scenario_split_key(text: str) -> str:
    """Case/punctuation/Unicode-insensitive scenario key, never a model prompt."""
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def _reject_overlapping_decision_splits(store: IdentityStore) -> None:
    """Reject exact and strong lexical near-duplicates across approved splits.

    Strong near matches need >=8 distinct words, >=48 nonspace characters
    and >=88% token-set Jaccard similarity. This conservative leakage check
    is NOT a semantic similarity model and may require owner cleanup when
    differently worded scenarios should legitimately be separate cases.
    """
    seen: dict[str, str] = {}
    near: list[tuple[str, frozenset[str]]] = []
    by_token: dict[str, set[int]] = {}
    rows = store.db.execute(
        "SELECT scenario,split FROM decisions WHERE status='approved' "
        "AND split IN ('train','calibration','test') ORDER BY id")
    for row in rows:
        key = _scenario_split_key(row['scenario'])
        prior = seen.setdefault(key, row['split'])
        if key and prior != row['split']:
            raise ValueError('Approved decision scenarios overlap evaluation splits')
        tokens = frozenset(key.split())
        if len(tokens) < 8 or sum(map(len, tokens)) < 48:
            continue
        # Candidate lookup avoids an unbounded all-pairs Cartesian scan when
        # many private decisions are present. Common short tokens are ignored.
        candidate_ids: set[int] = set()
        for token in tokens:
            if len(token) >= 5:
                candidate_ids.update(by_token.get(token, ()))
        for candidate_id in candidate_ids:
            old_split, old_tokens = near[candidate_id]
            if old_split == row['split']:
                continue
            overlap = len(tokens & old_tokens)
            if 100 * overlap >= 88 * len(tokens | old_tokens):
                raise ValueError('Approved decision scenarios overlap evaluation splits')
        index = len(near)
        near.append((row['split'], tokens))
        for token in tokens:
            if len(token) >= 5:
                by_token.setdefault(token, set()).add(index)


def _reject_repeated_heldout_scenarios(store: IdentityStore, split: str, limit: int) -> None:
    """Refuse correlated held-out cases masquerading as independent trials.

    Reviews can approve punctuation variants within one split. A benchmark
    that scores those variants separately can exaggerate its sample size and
    understate uncertainty. Exact normalized matches, plus long distinctive
    >=88%-Jaccard token-set near-matches, are rejected before any inference.
    Do not apply this to training records, where repetition is a separate
    dataset-quality concern. This is lexical, not semantic deduplication.
    """
    if split not in ('calibration', 'test') or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Invalid held-out independence scope')
    seen: set[str] = set()
    prior: list[frozenset[str]] = []
    by_token: dict[str, set[int]] = {}
    rows = store.db.execute(
        "SELECT scenario FROM decisions WHERE status='approved' AND split=? "
        "ORDER BY id LIMIT ?", (split, limit))
    for row in rows:
        scenario = row['scenario']
        if not isinstance(scenario, str):
            raise ValueError('Held-out scenarios must be valid text')
        key = _scenario_split_key(scenario)
        if not key or key in seen:
            raise ValueError('Repeated held-out decision scenarios require owner review')
        seen.add(key)
        tokens = frozenset(key.split())
        if len(tokens) < 8 or sum(map(len, tokens)) < 48:
            continue
        candidates: set[int] = set()
        for token in tokens:
            if len(token) >= 5:
                candidates.update(by_token.get(token, ()))
        for candidate_id in candidates:
            earlier = prior[candidate_id]
            if 100 * len(tokens & earlier) >= 88 * len(tokens | earlier):
                raise ValueError('Repeated held-out decision scenarios require owner review')
        index = len(prior)
        prior.append(tokens)
        for token in tokens:
            if len(token) >= 5:
                by_token.setdefault(token, set()).add(index)


def _fingerprint(rows) -> str:
    """Digest deterministic private evidence without including its contents."""
    payload = json.dumps(rows, sort_keys=True, ensure_ascii=False,
                         separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def _heldout_rows(store: IdentityStore, split: str, limit: int) -> list[list]:
    """Include held-out provenance in the digest but never in the model prompt."""
    return [list(row) for row in store.db.execute(
        'SELECT id,scenario,choice,options_json,rationale,exception,source,source_ref,created_at '
        "FROM decisions WHERE status='approved' AND split=? ORDER BY id LIMIT ?",
        (split, limit))]


def _reference_fingerprint(store: IdentityStore) -> str:
    """Snapshot all approved Twin prompt data, without exposing private rows."""
    evidence = []
    # Preserve the historical three-table digest when no newly supported
    # evidence exists: an unchanged profile must not invalidate all previous
    # reviewed benchmarks purely because AthenZ updated.
    for table, predicate in (
        ('identity', "status='approved'"),
        ('decisions', "status='approved' AND split='train'"),
        ('episodes', "status='approved'"),
        ('writing_samples', "status='approved' AND split='train'"),
        ('episode_disputes', "1=1"),
    ):
        # Explicit v5 writing columns preserve historical approved-training
        # evidence digests despite v6 adding a held-out split column.
        columns = ("id,text,source,source_ref,created_at,status"
                   if table == 'writing_samples' else '*')
        rows = [list(row) for row in store.db.execute(
            f'SELECT {columns} FROM {table} WHERE {predicate} ORDER BY id')]
        if rows or table in {'identity', 'decisions', 'episodes'}:
            evidence.append([table, rows])
    return _fingerprint(evidence)


def _collides_with_approved_reference(store: IdentityStore, scenario: str,
                                     rationale: str) -> bool:
    """Check ALL approved source records, including ones pruned by retrieval.

    Relevance-ranking must not create a loophole in train/held-out separation:
    evidence may be hidden by one topical query but exposed by another later.
    """
    for sql in (
        "SELECT text FROM identity WHERE status='approved'",
        "SELECT text FROM writing_samples "
        "WHERE status='approved' AND split='train'",
        "SELECT topic || ' ' || detail FROM episodes WHERE status='approved'",
        "SELECT scenario || ' ' || rationale FROM decisions "
        "WHERE status='approved' AND split='train'",
    ):
        for row in store.db.execute(sql):
            reference = row[0].casefold()
            if (scenario.strip().casefold() in reference
                    or (len(rationale.strip()) >= 16
                        and rationale.strip().casefold() in reference)
                    or _normalized_overlap(scenario, reference)
                    or _normalized_overlap(rationale, reference)):
                return True
    return False


def _heldout_prompt_messages(store: IdentityStore, item: list, seed: int) -> tuple[list[dict], list[str]]:
    """Construct the exact protected Twin prompt for evaluation or dry-run preflight.

    This pure prompt assembly reads approved local profile evidence but NEVER
    calls a model or exposes private reference text to the caller's report.
    """
    case_id, scenario, choice, options_json = item[:4]
    options = json.loads(options_json)
    if (not isinstance(options, list) or not 2 <= len(options) <= 6
            or choice not in options or any(not isinstance(o, str) for o in options)
            or len({o.casefold().strip() for o in options}) != len(options)):
        raise ValueError('Decision has invalid held-out options')
    shuffled = options[:]
    random.Random(seed + case_id).shuffle(shuffled)
    letters = 'ABCDEF'
    question = (scenario.strip() + '\nOptions:\n' +
                '\n'.join(f'{letters[i]}. {o}' for i, o in enumerate(shuffled)) +
                '\nWhich option would the owner most likely choose?')
    messages = build_messages(store, question, mode='twin')
    messages.insert(1, {'role': 'system', 'content':
        'Return only a JSON object with a single field "choice_letter" containing '
        'one of A through F. Choose using only approved TRAINING examples and '
        'the provided scenario. Do not invent personal memories.'})
    # Do not score a supposedly held-out target when approved reference
    # data supplies the exact target scenario or a distinctive private
    # rationale. The scenario in the USER question is intentional; only
    # the system reference profile is checked. This detects literal
    # contamination or normalized lexical collisions, not semantic
    # paraphrases or training-weight leakage.
    if (len(messages) != 4 or messages[2].get('role') != 'system'
            or not isinstance(messages[2].get('content'), str)
            or not messages[2]['content'].startswith('REFERENCE PROFILE (DATA ONLY):')):
        raise ValueError('Twin reference context changed; evaluation refused')
    reference_profile = messages[2]['content'].casefold()
    rationale = item[4].strip()
    if (_collides_with_approved_reference(store, scenario, rationale)
            or scenario.strip().casefold() in reference_profile
            or (len(rationale) >= 16 and rationale.casefold() in reference_profile)
            or _normalized_overlap(scenario, reference_profile)
            or _normalized_overlap(rationale, reference_profile)):
        raise ValueError('Held-out evaluation contaminated by approved reference evidence')
    return messages, shuffled


def evaluate_decisions(store: IdentityStore, model, *, split: str = 'test',
                       limit: int = 100, seed: int = 42) -> dict:
    if (split not in {'calibration', 'test'} or type(limit) is not int
            or not 1 <= limit <= 1000 or type(seed) is not int
            or not 0 <= seed <= 2**32 - 1):
        raise ValueError('Evaluate only held-out calibration/test splits with bounded settings')
    _reject_overlapping_decision_splits(store)
    _reject_repeated_heldout_scenarios(store, split, limit)
    cases = _heldout_rows(store, split, limit)
    heldout_sha = _fingerprint(cases)
    reference_sha = _reference_fingerprint(store)
    # Batch-wide dry run: reject a leak or ambiguous option in any selected
    # future case BEFORE the very first owner-held-out scenario is transmitted
    # to a local model. No result or private prompt is persisted by this pass.
    for item in cases:
        _heldout_prompt_messages(store, item, seed)
        if _reference_fingerprint(store) != reference_sha:
            raise ValueError('Approved reference evidence changed during evaluation preflight')
    if (_fingerprint(_heldout_rows(store, split, limit)) != heldout_sha or
            _reference_fingerprint(store) != reference_sha):
        raise ValueError('Approved evaluation evidence changed during preflight')
    report = {'split': split, 'seed': seed, 'model': getattr(model, 'model', 'unknown'),
              'total': len(cases), 'correct': 0, 'accuracy': None,
              'accuracy_interval_95': None, 'invalid_predictions': 0,
              'chance_expected': None, 'heldout_sha256': heldout_sha,
              'reference_sha256': reference_sha, 'cases': []}
    chance = 0.0
    for item in cases:
        case_id, scenario, choice, options_json = item[:4]
        # Fail closed before transmitting prompts if the approved reference
        # or this held-out case changed while a previous response was pending.
        current = store.db.execute(
            'SELECT id,scenario,choice,options_json,rationale,exception,source,source_ref,created_at '
            "FROM decisions WHERE id=? AND status='approved' AND split=?",
            (case_id, split)).fetchone()
        if current is None or list(current) != item:
            raise ValueError('Held-out decision changed during evaluation')
        if _reference_fingerprint(store) != reference_sha:
            raise ValueError('Approved reference evidence changed during evaluation')
        messages, shuffled = _heldout_prompt_messages(store, item, seed)
        letters = 'ABCDEF'
        # Check again after building messages, which can query private memories.
        if _reference_fingerprint(store) != reference_sha:
            raise ValueError('Approved reference evidence changed during evaluation')
        raw = model.generate(messages, json_mode=True, temperature=0.0, seed=seed)
        # No lock is held across an inference call. Withdrawn/edited evidence
        # invalidates the result rather than silently continuing to score it.
        current = store.db.execute(
            'SELECT id,scenario,choice,options_json,rationale,exception,source,source_ref,created_at '
            "FROM decisions WHERE id=? AND status='approved' AND split=?",
            (case_id, split)).fetchone()
        if current is None or list(current) != item:
            raise ValueError('Held-out decision changed during evaluation')
        if _reference_fingerprint(store) != reference_sha:
            raise ValueError('Approved reference evidence changed during evaluation')
        try:
            parsed = json.loads(raw)
            prediction = parsed.get('choice_letter', '') if isinstance(parsed, dict) else ''
        except (ValueError, AttributeError, TypeError):
            prediction = ''
        if not isinstance(prediction, str):
            prediction = ''
        prediction = prediction.strip().upper()
        if prediction not in letters[:len(shuffled)]:
            report['invalid_predictions'] += 1
            prediction = ''
        gold = letters[shuffled.index(choice)]
        correct = prediction == gold
        report['correct'] += int(correct)
        chance += 1 / len(shuffled)
        report['cases'].append({'id': case_id, 'predicted': prediction or None,
                                'expected': gold, 'correct': correct})
    # Neither cross-split leaks nor newly approved within-split duplicate
    # cases may turn a previously scored sample into biased evidence.
    _reject_overlapping_decision_splits(store)
    _reject_repeated_heldout_scenarios(store, split, limit)
    if (_fingerprint(_heldout_rows(store, split, limit)) != heldout_sha or
            _reference_fingerprint(store) != reference_sha):
        raise ValueError('Approved evaluation evidence changed during inference')
    if report['total']:
        report['accuracy'] = report['correct'] / report['total']
        report['accuracy_interval_95'] = _wilson_interval(report['correct'], report['total'])
        report['chance_expected'] = chance / report['total']
    return report
