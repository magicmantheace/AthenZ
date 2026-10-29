"""Batch authoring aid for owner held-out decision cases (scaffolding).

Authoring the 30 independent held-out cases the Twin evaluation needs, one
CLI call at a time, is slow and error-prone. This tool validates a whole
owner-written JSON batch BEFORE anything is stored, then inserts the cases
as *pending* decisions in one split. It never approves a case, never calls
a model, and never echoes scenario text back: errors and reports carry
only case indexes and fixed categories. The owner's per-case approval via
the existing decision-status flow remains the review act, and the frozen
test-plan machinery still governs any later evaluation.

Refusals mirror the evaluation module's own leakage standards: exact
normalized duplicates (against every existing decision and within the
batch), distinctive-phrase containment, and >=88% token-set Jaccard
near-duplicates under the same size floors the split-overlap guard uses.
Lexical screening is conservative, not semantic independence proof.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluation import _normalized_overlap, _scenario_split_key
from .experience import ExperienceStore

MAX_CASES = 200
MAX_FILE_BYTES = 2 * 1024 * 1024
SPLITS = ('calibration', 'test')
_FIELDS = {'scenario', 'choice', 'rationale', 'options', 'exception', 'source_ref'}


class HeldoutImportError(ValueError):
    """A held-out batch did not meet its authoring boundaries."""


def _tokens(scenario: str) -> frozenset:
    return frozenset(_scenario_split_key(scenario).split())


def _near_duplicate(a: frozenset, b: frozenset) -> bool:
    """The split-overlap guard's rule: >=8 tokens, >=48 chars, >=88% Jaccard."""
    if len(a) < 8 or len(b) < 8:
        return False
    if sum(map(len, a)) < 48 or sum(map(len, b)) < 48:
        return False
    return 100 * len(a & b) >= 88 * len(a | b)


def _validate_case(raw, index: int) -> dict:
    if not isinstance(raw, dict) or not set(raw) <= _FIELDS:
        raise HeldoutImportError(f'case {index}: malformed case object')
    case = {}
    for field in ('scenario', 'choice', 'rationale'):
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise HeldoutImportError(f'case {index}: missing or empty {field}')
        case[field] = value
    options = raw.get('options')
    if (not isinstance(options, list) or not 2 <= len(options) <= 6
            or not all(isinstance(o, str) and o.strip() for o in options)
            or len({o.casefold().strip() for o in options}) != len(options)):
        raise HeldoutImportError(f'case {index}: options must be 2-6 unique choices')
    if case['choice'] not in options:
        raise HeldoutImportError(f'case {index}: choice is not one of the options')
    case['options'] = options
    for field in ('exception', 'source_ref'):
        value = raw.get(field, '')
        if not isinstance(value, str):
            raise HeldoutImportError(f'case {index}: malformed {field}')
        case[field] = value
    return case


def load_batch(path: Path) -> list[dict]:
    """Parse and schema-validate the batch file; no store is touched."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise HeldoutImportError('Batch file is missing or unsafe')
    if path.stat().st_size > MAX_FILE_BYTES:
        raise HeldoutImportError('Batch file is too large')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise HeldoutImportError('Batch file is not valid UTF-8 JSON') from None
    if not isinstance(data, list) or not 1 <= len(data) <= MAX_CASES:
        raise HeldoutImportError(f'Batch must contain 1-{MAX_CASES} cases')
    return [_validate_case(raw, i) for i, raw in enumerate(data)]


def screen_batch(store: ExperienceStore, cases: list[dict]) -> None:
    """Leakage screen against existing decisions and within the batch."""
    existing = [row['scenario'] for row in store.db.execute(
        'SELECT scenario FROM decisions')]
    existing_keys = {_scenario_split_key(s) for s in existing}
    existing_tokens = [_tokens(s) for s in existing]
    batch_keys: set[str] = set()
    batch_tokens: list[frozenset] = []
    for i, case in enumerate(cases):
        key = _scenario_split_key(case['scenario'])
        if key in existing_keys or key in batch_keys:
            raise HeldoutImportError(f'case {i}: duplicate scenario')
        for prior in existing:
            if (_normalized_overlap(case['scenario'], prior)
                    or _normalized_overlap(prior, case['scenario'])):
                raise HeldoutImportError(
                    f'case {i}: scenario contains or is contained in an existing decision')
        tokens = _tokens(case['scenario'])
        for prior_tokens in (*existing_tokens, *batch_tokens):
            if _near_duplicate(tokens, prior_tokens):
                raise HeldoutImportError(f'case {i}: near-duplicate scenario')
        batch_keys.add(key)
        batch_tokens.append(tokens)


def import_batch(store: ExperienceStore, cases: list[dict], *, split: str,
                 confirmed: bool = False) -> dict:
    """Validate everything, then insert pending cases (all-or-nothing)."""
    if split not in SPLITS:
        raise HeldoutImportError('Held-out import only writes calibration or test splits')
    if not 1 <= len(cases) <= MAX_CASES:
        raise HeldoutImportError(f'Batch must contain 1-{MAX_CASES} cases')
    # Normalize here as well as in load_batch: direct callers must get the
    # same schema defaults and refusals as file-based imports.
    cases = [_validate_case(raw, i) for i, raw in enumerate(cases)]
    screen_batch(store, cases)
    report = {'schema': 1, 'kind': 'heldout-decision-import', 'split': split,
              'cases': len(cases), 'imported': 0, 'ids': [], 'approved': False,
              'model_called': False}
    if not confirmed:
        report['dry_run'] = True
        return report
    inserted: list[int] = []
    try:
        for case in cases:
            inserted.append(store.add_decision(
                case['scenario'], case['choice'], case['rationale'],
                source='owner:heldout-import', source_ref=case['source_ref'],
                exception=case['exception'], options=case['options'],
                split=split, approved=False))
    except Exception:
        # Compensating cleanup: a partial batch must never survive, or the
        # owner could approve a set that was screened as a different whole.
        for decision_id in inserted:
            store.delete('decisions', decision_id)
        raise HeldoutImportError(
            'Import failed partway; the partial batch was removed') from None
    report['imported'] = len(inserted)
    report['ids'] = inserted
    report['dry_run'] = False
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description='Validate and import owner-authored held-out decision cases (pending only)')
    parser.add_argument('--home', type=Path, required=True,
                        help='Existing private AthenZ profile outside Git')
    parser.add_argument('file', type=Path, help='JSON array of decision cases')
    parser.add_argument('--split', choices=SPLITS, default='test')
    parser.add_argument('--confirm', action='store_true',
                        help='Actually insert; without it the batch is only validated')
    args = parser.parse_args(argv)
    path = args.home / 'identity.sqlite3'
    if (not path.is_file() or path.is_symlink()
            or getattr(path, 'is_junction', lambda: False)()):
        parser.error('Select an existing local AthenZ profile')
    try:
        cases = load_batch(args.file)
        store = ExperienceStore(args.home)
        try:
            report = import_batch(store, cases, split=args.split,
                                  confirmed=args.confirm)
        finally:
            store.close()
    except HeldoutImportError as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
