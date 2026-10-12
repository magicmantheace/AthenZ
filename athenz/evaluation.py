"""Reproducible, held-out local prediction evaluation for Twin decisions.

Gold choices and rationales never enter the prediction prompt. Approval and
reference snapshots must remain unchanged throughout inference; a revoked
case never yields a passing evaluation. This is not independent attestation.
"""
from __future__ import annotations

import hashlib
import json
import random

from .store import IdentityStore
from .prompting import build_messages


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
    for table, predicate in (
        ('identity', "status='approved'"),
        ('decisions', "status='approved' AND split='train'"),
        ('episodes', "status='approved'"),
    ):
        # Table names and predicates are constants here, never user input.
        rows = [list(row) for row in store.db.execute(
            f'SELECT * FROM {table} WHERE {predicate} ORDER BY id')]
        evidence.append([table, rows])
    return _fingerprint(evidence)


def evaluate_decisions(store: IdentityStore, model, *, split: str = 'test',
                       limit: int = 100, seed: int = 42) -> dict:
    if (split not in {'calibration', 'test'} or type(limit) is not int
            or not 1 <= limit <= 1000 or type(seed) is not int
            or not 0 <= seed <= 2**32 - 1):
        raise ValueError('Evaluate only held-out calibration/test splits with bounded settings')
    cases = _heldout_rows(store, split, limit)
    heldout_sha = _fingerprint(cases)
    reference_sha = _reference_fingerprint(store)
    report = {'split': split, 'seed': seed, 'model': getattr(model, 'model', 'unknown'),
              'total': len(cases), 'correct': 0, 'accuracy': None,
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
        options = json.loads(options_json)
        if (not isinstance(options, list) or not 2 <= len(options) <= 6
                or choice not in options or any(not isinstance(o, str) for o in options)):
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
        # contamination, not semantic paraphrases or training-weight leakage.
        reference_profile = messages[2]['content'].casefold()
        rationale = item[4].strip()
        if (scenario.strip().casefold() in reference_profile
                or (len(rationale) >= 16 and rationale.casefold() in reference_profile)):
            raise ValueError('Held-out evaluation contaminated by approved reference evidence')
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
        gold = letters[shuffled.index(choice)]
        correct = prediction == gold
        report['correct'] += int(correct)
        chance += 1 / len(options)
        report['cases'].append({'id': case_id, 'predicted': prediction or None,
                                'expected': gold, 'correct': correct})
    if (_fingerprint(_heldout_rows(store, split, limit)) != heldout_sha or
            _reference_fingerprint(store) != reference_sha):
        raise ValueError('Approved evaluation evidence changed during inference')
    if report['total']:
        report['accuracy'] = report['correct'] / report['total']
        report['chance_expected'] = chance / report['total']
    return report
