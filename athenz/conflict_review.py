"""Owner-only, digest-bound adjudication of overlapping approved episodes.

Topical overlap is a REVIEW HINT, not proof of semantic contradiction. Nothing
is approved, rejected or superseded by a model or by a preview. All private
text stays in the owner's local CLI output; the repository holds no records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

from .experience import ExperienceStore
from .store import utc_now
from .profile_health import _home_location

MAX_CONFLICTS = 50
_SHA = re.compile(r'[0-9a-f]{64}\Z')


class ConflictReviewError(ValueError):
    """The requested review is absent, stale or not authorized."""


def _existing_home(home: Path | None) -> Path:
    location = _home_location(home)
    db = location / 'identity.sqlite3'
    if not location.is_dir() or db.is_symlink() or not db.is_file():
        raise ConflictReviewError('An existing private AthenZ episode database is required')
    return location


def _row(row) -> dict:
    return {name: row[name] for name in ('id', 'topic', 'detail', 'source', 'source_ref',
                                        'status', 'supersedes_id', 'created_at', 'updated_at')} | {
        'tags': json.loads(row['tags_json'])}


def _snapshot(db, episode_id: int) -> dict:
    if type(episode_id) is not int or episode_id <= 0:
        raise ConflictReviewError('Choose a valid episode ID')
    candidate = db.execute('SELECT * FROM episodes WHERE id=?', (episode_id,)).fetchone()
    if candidate is None or candidate['status'] != 'pending':
        raise ConflictReviewError('Only an existing pending episode may be adjudicated')
    pending = _row(candidate)
    labels = set(pending['tags'])
    matches = []
    if labels:
        for other in db.execute("SELECT * FROM episodes WHERE status='approved' AND id<>?", (episode_id,)):
            record = _row(other)
            common = sorted(labels.intersection(record['tags']))
            if common:
                matches.append((len(common), record['id'], common, record))
        matches.sort(key=lambda x: (-x[0], x[1]))
    if len(matches) > MAX_CONFLICTS:
        # Every competing source needs to be visible before owner approval;
        # truncating the list would make the displayed digest misleading.
        raise ConflictReviewError('Too many overlapping episodes for safe full review')
    reviewed = [{'shared_tags': common, 'episode': record} for _, _, common, record in matches]
    evidence = {'schema': 1, 'candidate': pending, 'overlapping_approved': reviewed}
    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(',', ':'),
                                       ensure_ascii=False).encode('utf-8')).hexdigest()
    return {'review_sha256': digest, **evidence}


def preview(home: Path | None, episode_id: int, *, confirmed: bool = False) -> dict:
    """Print full PRIVATE competing records only after explicit CLI consent."""
    if confirmed is not True:
        raise ConflictReviewError('Explicit --confirm required before displaying private episode details')
    location = _existing_home(home)
    store = ExperienceStore(location)
    try:
        result = _snapshot(store.db, episode_id)
        return {**result, 'automatic_resolution': False, 'semantic_contradiction_proven': False,
                'private_data_in_output': True, 'owner_decision_required': True}
    finally:
        store.close()


def adjudicate(home: Path | None, episode_id: int, *, digest: str,
               decision: str, predecessor_id: int | None = None,
               confirmed: bool = False) -> dict:
    """Atomically apply an owner decision to the EXACT reviewed source set.

    `keep-both` approves without rejecting competing approved evidence.
    `supersede` rejects exactly one selected predecessor and records provenance.
    `reject` declines the candidate and changes no previously approved record.
    """
    if confirmed is not True:
        raise ConflictReviewError('Explicit --confirm required to change reviewed memory')
    if not isinstance(digest, str) or not _SHA.fullmatch(digest):
        raise ConflictReviewError('Exact 64-character review SHA-256 is required')
    if decision not in ('keep-both', 'supersede', 'reject'):
        raise ConflictReviewError('Choose keep-both, supersede or reject')
    if (decision == 'supersede') != (type(predecessor_id) is int and predecessor_id > 0):
        raise ConflictReviewError('Supersede requires exactly one positive predecessor ID')
    location = _existing_home(home)
    store = ExperienceStore(location)
    try:
        with store.db:
            # Lock before reading the candidate and competitors: stale hashes
            # and concurrent second reviewers fail closed, with no partial write.
            store.db.execute('BEGIN IMMEDIATE')
            current = _snapshot(store.db, episode_id)
            if current['review_sha256'] != digest:
                raise ConflictReviewError('Review became stale; preview all records again')
            if decision == 'supersede':
                ids = {r['episode']['id'] for r in current['overlapping_approved']}
                if predecessor_id not in ids:
                    raise ConflictReviewError('Predecessor must be an explicitly reviewed approved overlap')
            # A predeclared supersedes pointer cannot silently override a
            # different action chosen in the current full-record review.
            prior = current['candidate']['supersedes_id']
            if prior is not None and decision != 'reject' and (decision != 'supersede' or prior != predecessor_id):
                raise ConflictReviewError('Candidate already names a predecessor; review that relationship')
            when = utc_now()
            if decision == 'supersede':
                store.db.execute("UPDATE episodes SET status='rejected',updated_at=? WHERE id=? AND status='approved'",
                                 (when, predecessor_id))
                store._event('superseded', 'episodes', predecessor_id)
            state = 'rejected' if decision == 'reject' else 'approved'
            result = store.db.execute(
                'UPDATE episodes SET status=?,supersedes_id=?,updated_at=? WHERE id=? AND status=\'pending\'',
                (state, predecessor_id if decision == 'supersede' else prior, when, episode_id))
            if result.rowcount != 1:
                raise ConflictReviewError('Pending episode changed; preview again')
            store._event('status:' + state, 'episodes', episode_id)
        return {'schema': 1, 'candidate_id': episode_id, 'decision': decision,
                'status': state, 'predecessor_id': predecessor_id,
                'approved_without_automatic_resolution': decision == 'keep-both',
                'review_hash_verified': True, 'private_records_in_output': False,
                'model_approval': False}
    finally:
        store.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Local owner review of possibly conflicting episodes')
    parser.add_argument('--home', type=Path, default=None, help='Existing private profile outside Git')
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('preview', help='Show complete PRIVATE episode records and their digest')
    p.add_argument('episode_id', type=int)
    p.add_argument('--confirm', action='store_true')
    p = sub.add_parser('decide', help='Apply exact-digest owner decision, never from model output')
    p.add_argument('episode_id', type=int)
    p.add_argument('decision', choices=['keep-both', 'supersede', 'reject'])
    p.add_argument('--sha256', required=True)
    p.add_argument('--predecessor', type=int)
    p.add_argument('--confirm', action='store_true')
    args = parser.parse_args(argv)
    if args.action == 'preview':
        out = preview(args.home, args.episode_id, confirmed=args.confirm)
    else:
        out = adjudicate(args.home, args.episode_id, digest=args.sha256,
                         decision=args.decision, predecessor_id=args.predecessor,
                         confirmed=args.confirm)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
