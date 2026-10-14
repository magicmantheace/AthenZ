"""Synthetic-only Twin retrieval quality benchmark. No model or private profile.

Run python -m athenz.twin_retrieval_benchmark and compare aggregate metrics.
This is not an evaluation of real personal style, decisions or model quality.
"""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .experience import ExperienceStore
from .prompting import MAX_PROFILE_CHARS, build_messages


def _payload(store: ExperienceStore, query: str) -> str:
    messages = build_messages(store, query, mode="twin")
    raw = messages[1]["content"].split("\n", 1)[1]
    json.loads(raw)  # enforce whole-record, valid JSON context
    return raw


def run_synthetic_benchmark() -> dict:
    """Score retrieval, prompt size, revocation, held-out separation and replay."""
    with TemporaryDirectory(prefix="athenz-twin-synthetic-") as home:
        store = ExperienceStore(Path(home) / "private")
        try:
            old_id = store.propose(
                "identity", "ASTRONOMY_OLD_TARGET synthetic orbital spectrometry method",
                source="synthetic", approved=True)
            old_decision = store.add_decision(
                "How would I manage an antique gyroscope bearing repair?",
                "Inspect first", "GYROSCOPE_OLD_TARGET reproducible calibration",
                source="synthetic", approved=True)
            old_writing = store.add_sample(
                ("Synthetic descriptive paragraph without topic terms. " * 19) +
                "murmuration OLD_WRITING_TARGET carefully measured prose",
                source="synthetic")
            store.set_review("writing_samples", old_writing, "approved")
            for i in range(255):
                store.propose(
                    "identity", "Synthetic garden pottery catalogue " + str(i),
                    source="synthetic", approved=True)
                store.add_decision(
                    "Which garden crate should hold carrots batch " + str(i) + "?",
                    "Store", "Synthetic vegetable packaging", source="synthetic",
                    approved=True)
                sample = store.add_sample(
                    "Synthetic fruit orchard descriptive writing " + str(i),
                    source="synthetic")
                store.set_review("writing_samples", sample, "approved")

            # Newer but unapproved, explicitly rejected, or held-out evidence.
            store.propose(
                "identity", "PENDING_SECRET_SYNTHETIC orbital spectrometry",
                source="synthetic")
            denied = store.propose(
                "identity", "REJECTED_SECRET_SYNTHETIC orbital spectrometry",
                source="synthetic", approved=True)
            store.status(denied, "rejected")
            store.add_decision(
                "How would I manage an antique gyroscope bearing repair with unknown parts?",
                "Unsafe", "HELDOUT_PRIVATE_GOLD_SYNTHETIC", source="synthetic",
                split="test", options=["Unsafe", "Inspect first"], approved=True)
            store.add_sample(
                "PENDING_STYLE_SECRET_SYNTHETIC murmuration", source="synthetic")

            queries = (
                ("What is my orbital spectrometry method?", "ASTRONOMY_OLD_TARGET"),
                ("Antique gyroscope bearing repair preference?", "GYROSCOPE_OLD_TARGET"),
                ("How would I describe murmuration?", "OLD_WRITING_TARGET"),
            )
            retrieved = 0
            isolated = True
            deterministic = True
            for query, needle in queries:
                raw = _payload(store, query)
                retrieved += needle in raw
                deterministic &= raw == _payload(store, query)
                isolated &= len(raw) <= MAX_PROFILE_CHARS
                isolated &= not any(bad in raw for bad in (
                    "PENDING_SECRET_SYNTHETIC",
                    "REJECTED_SECRET_SYNTHETIC",
                    "HELDOUT_PRIVATE_GOLD_SYNTHETIC",
                    "PENDING_STYLE_SECRET_SYNTHETIC"))
            recent = store.context()
            recent_samples = store.list_items(
                "writing_samples", "approved", limit=200)
            capped = json.dumps([recent, recent_samples], ensure_ascii=False)
            baseline_hits = sum(needle in capped for _, needle in queries)

            store.status(old_id, "rejected")
            store.decision_status(old_decision, "rejected")
            store.set_review("writing_samples", old_writing, "rejected")
            revoked_clear = all(
                needle not in _payload(store, query)
                for query, needle in queries)
            return {
                "schema": 1, "benchmark": "synthetic-full-history-retrieval",
                "cases": len(queries),
                "full_history_recall_at_prompt": retrieved / len(queries),
                "latest_200_candidate_window_recall": baseline_hits / len(queries),
                "approval_and_heldout_isolation_passed": bool(isolated),
                "deterministic_results": bool(deterministic),
                "revocation_propagates": bool(revoked_clear),
                "model_called": False,
                "real_owner_personality_accuracy_measured": False,
                "private_profile_accessed": False,
            }
        finally:
            store.close()


def main() -> int:
    report = run_synthetic_benchmark()
    print(json.dumps(report, sort_keys=True))
    return int(not (
        report["full_history_recall_at_prompt"] == 1.0
        and report["approval_and_heldout_isolation_passed"]
        and report["deterministic_results"]
        and report["revocation_propagates"]))


if __name__ == "__main__":
    raise SystemExit(main())
