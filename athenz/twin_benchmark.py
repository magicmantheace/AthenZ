"""Offline synthetic Twin context retrieval benchmark; no owner data or model calls."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

from .experience import ExperienceStore
from .prompting import build_messages


def run_benchmark() -> dict:
    """Report retrieval coverage, irrelevant evidence and revoked-data leakage.

    Synthetic tests are NOT evidence of personality fidelity or model accuracy.
    """
    with tempfile.TemporaryDirectory(prefix="athenz-twin-bench-") as directory:
        store = ExperienceStore(Path(directory))
        try:
            target = store.propose(
                "identity", "I enjoy restoring antique telescopes",
                source="synthetic:benchmark", approved=True)
            for index in range(260):
                store.propose(
                    "identity", f"My synthetic preference for garden plot {index} is shade",
                    source="synthetic:benchmark", approved=True)
            queries = (
                ("Tell me about restoring antique telescopes", "antique telescopes", True),
                ("Tell me about repairing a diesel engine", "antique telescopes", False),
            )
            hits = 0
            unrelated = 0
            for query, marker, expected in queries:
                messages = build_messages(store, query, "twin")
                profile = json.loads(messages[1]["content"].split("\n", 1)[1])
                selected = json.dumps(profile)
                present = marker in selected
                hits += int(present == expected)
                unrelated += int(not expected and present)
            store.status(target, "rejected")
            # Query text is user-supplied, not a retrieved memory. Never
            # confuse words in the question with a revoked reference record.
            messages = build_messages(
                store, "Tell me about restoring antique telescopes", "twin")
            revoked = messages[1]["content"].split("\n", 1)[1]
            return {
                "schema": 1,
                "synthetic_only": True,
                "cases": len(queries),
                "expected_retrievals_correct": hits,
                "irrelevant_evidence_exposures": unrelated,
                "revoked_evidence_exposures": int("antique telescopes" in revoked),
                "real_personality_accuracy_measured": False,
            }
        finally:
            store.close()


def main() -> None:
    print(json.dumps(run_benchmark(), sort_keys=True))


if __name__ == "__main__":
    main()
