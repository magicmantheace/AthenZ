"""Aggregate-only offline preflight for protected Twin writing-style evaluation.

This does NOT score a model or claim personality/style similarity. It detects
missing independent review samples and obvious exact/normalized duplicates.
Never print or persist owner-authored text, excerpts, hashes or row IDs.
"""
from __future__ import annotations

import re
import unicodedata

from .store import IdentityStore


def _normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def style_readiness(store: IdentityStore) -> dict:
    """Summarize reviewed train/calibration/test partition health privately."""
    approved = {"train": 0, "calibration": 0, "test": 0}
    pending = {"train": 0, "calibration": 0, "test": 0}
    rejected = {"train": 0, "calibration": 0, "test": 0}
    occurrences: dict[str, set[str]] = {}
    for row in store.db.execute(
        "SELECT text, status, split FROM writing_samples ORDER BY id"
    ):
        split, status = row["split"], row["status"]
        if split not in approved or status not in ("approved", "pending", "rejected"):
            raise ValueError("Writing evidence has invalid split or approval state")
        {"approved": approved, "pending": pending, "rejected": rejected}[status][split] += 1
        if status == "approved":
            normalized = _normalized(row["text"])
            if not normalized:
                raise ValueError("Approved writing sample is empty after normalization")
            occurrences.setdefault(normalized, set()).add(split)
    cross_split_duplicates = sum(
        1 for splits in occurrences.values() if len(splits) > 1)
    return {
        "schema": 1,
        "kind": "offline-style-evidence-readiness",
        "approved_counts": approved,
        "pending_counts": pending,
        "rejected_counts": rejected,
        "cross_split_normalized_duplicates": cross_split_duplicates,
        "pilot_evaluation_sufficient": (approved["train"] >= 3
                                       and approved["test"] >= 3
                                       and cross_split_duplicates == 0),
        "owner_style_accuracy_evaluated": False,
        "model_called": False,
        "private_text_returned": False,
        "evaluation_caveat": (
            "Only sample counts and obvious normalized duplicates are checked; "
            "no model accuracy, semantic overlap or independence is proven."
        ),
    }
