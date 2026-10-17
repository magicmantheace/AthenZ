"""Read-only, deterministic approved-memory consistency hints.

No AI inference, embeddings, automatic approval, revocation or interpretation.
Pattern coverage is deliberately narrow: exact normalized duplicates and
simple first-person preference polarity differences only. Not a truth checker.
"""
from __future__ import annotations

import re
import unicodedata

from .store import IdentityStore


MAX_APPROVED_SCAN = 5000
MAX_PAIRS = 80

# Restrict polarity to first-person statements with the same exact subject,
# action verb and object. This is only a review candidate, never a decision.
_POSITIVE = re.compile(r"^i (prefer|like|want|enjoy) (.+)$")
_NEGATIVE = re.compile(
    r"^i (?:do not|don't|no longer) (prefer|like|want|enjoy) (.+)$"
)


class MemoryConsistencyError(ValueError):
    pass


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = folded.replace("\u2019", "'")
    # Preserve contractions and terms, strip punctuation around words.
    return " ".join(re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", folded))


def _polarity(normalized: str) -> tuple[str, str, str] | None:
    positive = _POSITIVE.fullmatch(normalized)
    if positive:
        return ("positive", positive.group(1), positive.group(2))
    negative = _NEGATIVE.fullmatch(normalized)
    if negative:
        return ("negative", negative.group(1), negative.group(2))
    return None


def audit_approved_memories(store: IdentityStore, *, limit: int = MAX_PAIRS) -> dict:
    """Find bounded high-precision review candidates without emitting text.

    Checks *only* currently approved identity records, considering same-kind
    duplicates and simple first-person negation patterns. No inferred
    contradiction, semantic match, or automatic resolution is claimed.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_PAIRS:
        raise MemoryConsistencyError("Memory audit limit must be 1–80")
    # Read a consistent SQLite snapshot, not a blend of mid-audit approvals.
    if store.db.in_transaction:
        raise MemoryConsistencyError("Memory audit requires an idle database transaction")
    store.db.execute("BEGIN")
    try:
        rows = store.db.execute(
            "SELECT id,kind,text FROM identity WHERE status='approved' "
            "ORDER BY id LIMIT ?", (MAX_APPROVED_SCAN + 1,)
        ).fetchall()
        if len(rows) > MAX_APPROVED_SCAN:
            raise MemoryConsistencyError(
                "Too many approved records for a complete bounded memory audit")
        exact: dict[tuple[str, str], int] = {}
        polarized: dict[tuple[str, str, str, str], int] = {}
        pairs: list[dict] = []
        total = 0
        counts = {"normalized-duplicate": 0, "possible-polarity-conflict": 0}

        for row in rows:
            normalized = _normalize(row["text"])
            if not normalized:
                continue
            kind, memory_id = row["kind"], int(row["id"])
            duplicate = exact.get((kind, normalized))
            if duplicate is None:
                exact[(kind, normalized)] = memory_id
            else:
                counts["normalized-duplicate"] += 1
                total += 1
                if len(pairs) < limit:
                    pairs.append({
                        "kind": "normalized-duplicate",
                        "first_id": duplicate, "second_id": memory_id
                    })
            polarity = _polarity(normalized)
            if polarity is not None:
                sign, verb, object_ = polarity
                other = "negative" if sign == "positive" else "positive"
                matched = polarized.get((kind, other, verb, object_))
                if matched is not None:
                    counts["possible-polarity-conflict"] += 1
                    total += 1
                    if len(pairs) < limit:
                        pairs.append({
                            "kind": "possible-polarity-conflict",
                            "first_id": matched, "second_id": memory_id
                        })
                polarized.setdefault((kind, sign, verb, object_), memory_id)
        return {
            "schema": 1,
            "status": "review-candidates-found" if total else "no-supported-pattern-matches",
            "approved_records_scanned": len(rows),
            "candidate_counts": counts,
            "shown": len(pairs),
            "additional_candidates_not_shown": total - len(pairs),
            "candidates": pairs,
            "automatic_actions_taken": False,
            "unreviewed_records_scanned": False,
            "confirmed_conflicts": False,
            "no_conflicts_proven": False
        }
    finally:
        store.db.rollback()
