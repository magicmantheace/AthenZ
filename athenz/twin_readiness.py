"""Read-only owner-private Twin evaluation readiness using existing checks.

This entry point collects *aggregate* readiness for a standalone Twin, rather
than creating a second benchmark or exposing held-out prompts to the CLI.
It never calls a model or writes approvals, chat, training, or predictions.
The private SQLite profile must already exist when invoked from the CLI.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .experience import ExperienceStore
from .model_gate import inspect_heldout_readiness
from .style_readiness import style_readiness

DECISION_TARGET = 30
STYLE_RATING_TARGET = 20


def inspect_twin_readiness(store: ExperienceStore, *,
                           decision_target: int = DECISION_TARGET,
                           case_limit: int = 100) -> dict:
    """Read approved counts and protected held-out eligibility, never text."""
    if (type(decision_target) is not int or type(case_limit) is not int
            or not 2 <= decision_target <= case_limit <= 1000):
        raise ValueError("Choose a bounded held-out decision target and limit")
    # This is one SELECT and a bounded approved-reference preflight. Neither
    # owner prose nor IDs leave the aggregate report.
    counts = {
        row["kind"]: int(row["n"]) for row in store.db.execute(
            "SELECT kind,COUNT(*) AS n FROM identity "
            "WHERE status='approved' GROUP BY kind")
    }
    episodes = int(store.db.execute(
        "SELECT COUNT(*) FROM episodes WHERE status='approved'"
    ).fetchone()[0])
    identity = counts.get("identity", 0)
    preferences = counts.get("preference", 0)
    values = counts.get("value", 0)
    style = style_readiness(store)
    heldout = inspect_heldout_readiness(
        store, split="test", limit=case_limit,
        min_cases=decision_target)
    # A lexical clean preflight does not prove independence. The owner's
    # separate case/category review and real-device inference are essential.
    missing = []
    if not (identity or preferences or values or episodes):
        missing.append("approve-owner-facts-or-preferences")
    if not heldout["minimum_cases_met"]:
        missing.append("review-more-independent-heldout-decisions")
    if not heldout["split_independence_check"] == "lexical-pass":
        missing.append("resolve-cross-split-decision-overlap")
    if not heldout["selected_cases_independent"]:
        missing.append("review-duplicate-heldout-decisions")
    if not heldout["heldout_options_valid"]:
        missing.append("repair-heldout-decision-options")
    if not heldout["reference_profile_clean"]:
        missing.append("resolve-heldout-reference-contamination")
    if not heldout["evidence_snapshot_stable"]:
        missing.append("repeat-check-after-evidence-change")
    if style["approved_counts"]["train"] < 3:
        missing.append("approve-independent-training-writing-examples")
    if style["approved_counts"]["test"] < 3:
        missing.append("approve-independent-heldout-writing-examples")
    if style["cross_split_normalized_duplicates"]:
        missing.append("resolve-writing-split-duplicates")
    return {
        "schema": 1,
        "kind": "standalone-twin-evaluation-readiness",
        "approved_references": {
            "identity": identity,
            "preferences": preferences,
            "values": values,
            "style_rules": counts.get("style", 0),
            "episodes": episodes,
        },
        "heldout_decisions": {
            "target_independent_cases": decision_target,
            "approved_test_cases": heldout["approved_cases"],
            "selected_cases": heldout["selected_cases"],
            "minimum_met": heldout["minimum_cases_met"],
            "split_independence_lexical_check":
                heldout["split_independence_check"],
            "selected_cases_independent_lexical_check":
                heldout["selected_cases_independent"],
            "options_valid": heldout["heldout_options_valid"],
            "approved_reference_collision_free_lexical_check":
                heldout["reference_profile_clean"],
            "snapshot_stable": heldout["evidence_snapshot_stable"],
            "ready_for_owner_review": heldout["ready_for_owner_review"],
        },
        "writing": {
            "approved_by_split": style["approved_counts"],
            "pending_by_split": style["pending_counts"],
            "cross_split_normalized_duplicates":
                style["cross_split_normalized_duplicates"],
            "pilot_samples_ready": style["pilot_evaluation_sufficient"],
            "target_owner_blinded_ratings": STYLE_RATING_TARGET,
            "owner_blinded_ratings_measured_here": False,
        },
        "next_actions": missing,
        "data_preflight_ready": (not missing),
        "model_called": False,
        "private_text_returned": False,
        "training_started": False,
        "personality_similarity_measured": False,
        "windows_hardware_validated": False,
        "limitations": (
            "Approved-count and conservative lexical preflight only. "
            "Independent categories, blinded writing ratings, actual "
            "Ollama scoring and target-PC GPU tests remain separate, "
            "owner-controlled steps."
        ),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Local aggregate-only Twin evaluation readiness")
    parser.add_argument("--home", type=Path, required=True,
                        help="Existing private AthenZ profile outside Git")
    parser.add_argument("--decision-target", type=int, default=DECISION_TARGET)
    parser.add_argument("--case-limit", type=int, default=100)
    args = parser.parse_args(argv)
    # Readiness cannot silently initialize an empty private profile or pick
    # another directory: the owner must explicitly select existing data.
    path = args.home / "identity.sqlite3"
    if (not path.is_file() or path.is_symlink()
            or getattr(path, "is_junction", lambda: False)()):
        parser.error("Select an existing local AthenZ profile")
    try:
        store = ExperienceStore(args.home)
        try:
            report = inspect_twin_readiness(
                store, decision_target=args.decision_target,
                case_limit=args.case_limit)
        finally:
            store.close()
    except (ValueError, OSError):
        parser.error("Twin readiness check refused; inspect local data")
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
