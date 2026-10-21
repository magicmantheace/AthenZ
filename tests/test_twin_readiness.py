"""Read-only, aggregate-only Twin evaluation readiness on fictional profiles."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.experience import ExperienceStore
from athenz.twin_readiness import inspect_twin_readiness, main


class TwinReadinessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "fictional-owner-profile"
        self.store = ExperienceStore(self.home)
        self.addCleanup(self.store.close)

    def add_writing(self):
        # Different domains/syntax keep held-out examples independent from
        # training samples under the existing lexical near-copy guard.
        training = (
            "Fictional lighthouse keeper repairs rusted pulleys in heavy rain.",
            "An imaginary mechanic explains gearbox lubrication for toy trains.",
            "A pretend botanist describes unusual moss on distant cliff faces.",
        )
        heldout = (
            "The painted observatory dome rotates toward six distant galaxies.",
            "A quiet ceramic studio glazes bowls using mineral-rich pigments.",
            "Morning orchestra rehearsal begins with cellos tuning long notes.",
        )
        for split, texts in (("train", training), ("test", heldout)):
            for text in texts:
                mid = self.store.add_sample(
                    text, source="synthetic", split=split)
                self.store.set_review("writing_samples", mid, "approved")

    def add_heldout(self, total=2):
        for i in range(total):
            self.store.add_decision(
                "In fictional scenario #"+str(i)+", select first or second?",
                "First", "Independent synthetic held-out reason " + str(i),
                source="synthetic", approved=True, split="test",
                options=["First", "Second"])

    def test_empty_profile_shows_gaps_without_exposing_content(self):
        self.store.propose(
            "identity", "SYNTHETIC_PENDING_SECRET", source="synthetic")
        self.store.add_decision(
            "Synthetic pending question?", "First", "SECRET_GOLD",
            source="synthetic", split="test",
            options=["First", "Second"])
        before = tuple(self.store.db.execute(
            "SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in ("identity", "decisions", "messages", "test_runs"))
        result = inspect_twin_readiness(
            self.store, decision_target=2, case_limit=5)
        after = tuple(self.store.db.execute(
            "SELECT COUNT(*) FROM " + table).fetchone()[0]
            for table in ("identity", "decisions", "messages", "test_runs"))
        self.assertEqual(before, after)
        self.assertFalse(result["data_preflight_ready"])
        self.assertFalse(result["model_called"])
        self.assertFalse(result["personality_similarity_measured"])
        self.assertFalse(result["private_text_returned"])
        self.assertEqual(result["heldout_decisions"]["approved_test_cases"], 0)
        self.assertIn("approve-owner-facts-or-preferences",
                      result["next_actions"])
        self.assertIn("review-more-independent-heldout-decisions",
                      result["next_actions"])
        result_json = json.dumps(result)
        self.assertNotIn("SYNTHETIC_PENDING_SECRET", result_json)
        self.assertNotIn("SECRET_GOLD", result_json)

    def test_full_fictional_preflight_reuses_existing_gates(self):
        self.store.propose(
            "identity", "SYNTHETIC_APPROVED_ORIGIN in a fictional town",
            source="synthetic", approved=True)
        self.add_heldout()
        self.add_writing()
        with patch("athenz.chat.OllamaClient",
                   side_effect=AssertionError("No Ollama allowed")):
            result = inspect_twin_readiness(
                self.store, decision_target=2, case_limit=5)
        self.assertTrue(result["data_preflight_ready"])
        self.assertEqual(result["next_actions"], [])
        self.assertEqual(result["heldout_decisions"]["selected_cases"], 2)
        self.assertTrue(result["heldout_decisions"]["ready_for_owner_review"])
        self.assertTrue(result["writing"]["pilot_samples_ready"])
        self.assertEqual(result["writing"]["approved_by_split"]["train"], 3)
        self.assertEqual(result["writing"]["approved_by_split"]["test"], 3)
        self.assertFalse(result["writing"]["owner_blinded_ratings_measured_here"])
        self.assertEqual(result["writing"]["target_owner_blinded_ratings"], 20)
        self.assertNotIn("SYNTHETIC_APPROVED_ORIGIN", json.dumps(result))

    def test_exact_approved_reference_collision_blocks_readiness(self):
        scenario = "In the synthetic workshop, do we ship an untested gizmo?"
        self.store.propose(
            "identity", "SYNTHETIC_PROTECTED " + scenario,
            source="synthetic", approved=True)
        self.store.add_decision(
            scenario, "Wait", "Gold never disclosed", source="synthetic",
            options=["Ship", "Wait"], split="test", approved=True)
        self.add_writing()
        report = inspect_twin_readiness(
            self.store, decision_target=2, case_limit=5)
        self.assertFalse(report["data_preflight_ready"])
        self.assertFalse(
            report["heldout_decisions"]["approved_reference_collision_free_lexical_check"])
        self.assertIn("resolve-heldout-reference-contamination",
                      report["next_actions"])
        self.assertNotIn("SYNTHETIC_PROTECTED", json.dumps(report))
        self.assertNotIn(scenario, json.dumps(report))

    def test_invalid_bounds_refuse_before_store_access(self):
        for target, limit in ((True, 50), (1, 30), (20, 10),
                              (2, 1001), (2, 2.5)):
            with self.subTest(target=target, limit=limit):
                with patch("athenz.twin_readiness.style_readiness",
                           side_effect=AssertionError("unexpected query")):
                    with self.assertRaises(ValueError):
                        inspect_twin_readiness(
                            self.store, decision_target=target,
                            case_limit=limit)

    def test_cli_refuses_missing_profile_without_creation(self):
        empty = self.home.parent / "not-a-profile"
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(["--home", str(empty)])
        self.assertFalse(empty.exists())

    def test_cli_reports_only_aggregate_and_no_model(self):
        self.store.propose(
            "preference", "SYNTHETIC_HIDDEN_PREF likes paper",
            source="synthetic", approved=True)
        self.add_heldout()
        self.add_writing()
        buf = io.StringIO()
        with redirect_stdout(buf), patch(
            "athenz.chat.OllamaClient",
            side_effect=AssertionError("No Ollama allowed")
        ):
            main(["--home", str(self.home), "--decision-target", "2",
                  "--case-limit", "5"])
        obj = json.loads(buf.getvalue())
        self.assertTrue(obj["data_preflight_ready"])
        self.assertEqual(obj["approved_references"]["preferences"], 1)
        self.assertNotIn("SYNTHETIC_HIDDEN_PREF", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
