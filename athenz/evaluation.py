"""Reproducible, held-out local prediction evaluation for Twin decisions.

Gold choices and private rationales never enter the prediction prompt.
Scores are exploratory and are NOT a substitute for user validation.
"""
from __future__ import annotations

import json
import random
from .store import IdentityStore
from .prompting import build_messages


def evaluate_decisions(store: IdentityStore, model, *, split: str = 'test', limit: int = 100,
                       seed: int = 42) -> dict:
    if split not in {'calibration', 'test'} or not 1 <= limit <= 1000:
        raise ValueError('Evaluate only held-out calibration/test splits')
    cases = store.db.execute('''SELECT id,scenario,choice,options_json FROM decisions
        WHERE status='approved' AND split=? ORDER BY id LIMIT ?''', (split, limit)).fetchall()
    report = {'split': split, 'seed': seed, 'model': getattr(model, 'model', 'unknown'),
              'total': len(cases), 'correct': 0, 'accuracy': None, 'chance_expected': None, 'cases': []}
    chance = 0.0
    for row in cases:
        options = json.loads(row['options_json'])
        if not 2 <= len(options) <= 6 or row['choice'] not in options:
            raise ValueError(f'Decision #{row["id"]} has invalid test options')
        # Stable per-case shuffling prevents the chosen option's authoring order
        # from being a trivial predictor. No gold/rationale in the prompt.
        shuffled = options[:]
        random.Random(seed + row['id']).shuffle(shuffled)
        letters = 'ABCDEF'
        question = (row['scenario'].strip() + '\nOptions:\n' +
                    '\n'.join(f'{letters[i]}. {o}' for i, o in enumerate(shuffled)) +
                    '\nWhich option would the owner most likely choose?')
        messages = build_messages(store, question, mode='twin')
        messages.insert(1, {'role': 'system', 'content':
            'Return only a JSON object with a single field "choice_letter" containing '
            'one of A through F. Choose using only approved TRAINING examples and '
            'the provided scenario. Do not invent personal memories.'})
        raw = model.generate(messages, json_mode=True, temperature=0.0, seed=seed)
        try:
            prediction = json.loads(raw).get('choice_letter', '')
        except (ValueError, AttributeError, TypeError):
            prediction = ''
        if not isinstance(prediction, str):
            prediction = ''
        prediction = prediction.strip().upper()
        gold = letters[shuffled.index(row['choice'])]
        correct = prediction == gold
        report['correct'] += int(correct)
        chance += 1 / len(options)
        report['cases'].append({'id': row['id'], 'predicted': prediction or None,
                                'expected': gold, 'correct': correct})
    if report['total']:
        report['accuracy'] = report['correct'] / report['total']
        report['chance_expected'] = chance / report['total']
    return report
