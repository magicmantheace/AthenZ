"""Synthetic Twin personality and memory retrieval safety and relevance."""
import json
from pathlib import Path
import tempfile
import unittest

from athenz.evaluation import _reference_fingerprint, evaluate_decisions
from athenz.experience import ExperienceStore
from athenz.prompting import build_messages, MAX_PROFILE_CHARS


def profile(store, question, mode="twin"):
    result = build_messages(store, question, mode)
    assert result[1]["content"].startswith("REFERENCE PROFILE (DATA ONLY):\n")
    return json.loads(result[1]["content"].split("\n", 1)[1])


class TwinContextTests(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.store = ExperienceStore(Path(home.name) / "local")
        self.addCleanup(self.store.close)

    def test_topic_relevance_finds_old_decision_beyond_latest_twenty(self):
        self.store.add_decision(
            "Should I test the parser before deployment?", "Test it",
            "Verify correctness before merging", source="synthetic", approved=True)
        for i in range(35):
            self.store.add_decision(
                "Should the tomato harvest be stored in basket " + str(i) + "?",
                "Basket", "Keep garden vegetables dry", source="synthetic",
                approved=True)
        relevant = profile(self.store, "Should I test the parser for deployment?")
        self.assertEqual(len(relevant["approved_decisions"]), 1)
        self.assertEqual(relevant["approved_decisions"][0]["choice"], "Test it")
        self.assertNotIn("garden vegetables", json.dumps(relevant))

    def test_unrelated_personal_identity_is_not_injected(self):
        self.store.propose("identity", "PRIVATE_BIO_SYNTHETIC likes snowboarding",
                           source="synthetic", approved=True)
        self.store.propose("style", "Prefer concise structured explanations",
                           source="synthetic", approved=True)
        p = profile(self.store, "How should I structure this Python code?")
        self.assertIn("Prefer concise structured explanations", json.dumps(p))
        self.assertNotIn("PRIVATE_BIO_SYNTHETIC", json.dumps(p))
        self.assertIn("PRIVATE_BIO_SYNTHETIC", json.dumps(
            profile(self.store, "What is my profile or background?")))

    def test_approved_writing_samples_are_twin_only_and_review_gated(self):
        pending = self.store.add_sample(
            "UNREVIEWED_SYNTHETIC_STYLE", source="synthetic")
        approved = self.store.add_sample(
            "SYNTHETIC_REVIEWED_STYLE uses short clear paragraphs and measured claims",
            source="owner:synthetic")
        self.assertNotIn("SYNTHETIC_REVIEWED_STYLE",
                         json.dumps(profile(self.store, "How would I write this?")))
        self.store.set_review("writing_samples", approved, "approved")
        twin = profile(self.store, "How would I write this?")
        self.assertIn("SYNTHETIC_REVIEWED_STYLE", json.dumps(twin))
        self.assertNotIn("UNREVIEWED_SYNTHETIC_STYLE", json.dumps(twin))
        agent = profile(self.store, "How would I write this?", "agent")
        self.assertNotIn("approved_writing_examples", agent)
        self.store.set_review("writing_samples", approved, "rejected")
        self.assertNotIn("SYNTHETIC_REVIEWED_STYLE",
                         json.dumps(profile(self.store, "How would I write this?")))
        self.assertEqual(self.store.list_items("writing_samples", "approved"), [])
        self.assertIsNotNone(pending)

    def test_heldout_decisions_never_become_twin_examples(self):
        self.store.add_decision(
            "Should this private heldout deployment be authorized?",
            "No", "PRIVATE_GOLD_SYNTHETIC", source="synthetic",
            split="test", options=["Yes", "No"], approved=True)
        self.store.add_decision(
            "Would I authorize the tested deployment?", "No",
            "Favor reviewed tests", source="synthetic", approved=True)
        p = profile(self.store, "Would I authorize a deployment?")
        self.assertNotIn("PRIVATE_GOLD_SYNTHETIC", json.dumps(p))
        self.assertIn("Favor reviewed tests", json.dumps(p))
        self.assertEqual(len(p["approved_decisions"]), 1)

    def test_json_profile_never_truncates_mid_record(self):
        for i in range(7):
            self.store.propose(
                "style", f"synthetic approved writing style number {i}: " + ("x" * 6000),
                source="synthetic", approved=True)
        for i in range(12):
            self.store.add_decision(
                "Which parser choice handles framework " + str(i) + "?",
                "Choice", "synthetic parser " + ("y" * 2400),
                source="synthetic", approved=True)
        payload = build_messages(self.store, "Which parser choice?", "twin")[1]["content"]
        parsed = json.loads(payload.split("\n", 1)[1])
        self.assertLessEqual(len(payload.split("\n", 1)[1]), MAX_PROFILE_CHARS)
        self.assertIsInstance(parsed["approved_identity"], list)
        self.assertIsInstance(parsed["approved_decisions"], list)
        for row in parsed["approved_identity"]:
            self.assertFalse(row["text"].endswith("x" * 100) and len(row["text"]) < 6000)

    def test_disputed_episodes_not_returned_as_facts(self):
        a = self.store.observe(
            "Python parser preference", "Always use classic parser",
            tags=["python", "parser"], source="synthetic")
        b = self.store.observe(
            "Python parser preference", "Always use a fast parser",
            tags=["python", "parser"], source="synthetic")
        self.store.review_episode(a, "approved")
        self.store.review_episode(b, "approved")
        self.assertIn("classic parser", json.dumps(
            profile(self.store, "Python parser")))
        self.store.dispute(a, b, "Synthetic records conflict")
        contested = json.dumps(profile(self.store, "Python parser"))
        self.assertNotIn("classic parser", contested)
        self.assertNotIn("fast parser", contested)

    def test_unchanged_profile_retains_historical_reference_digest(self):
        from athenz.evaluation import _fingerprint
        self.store.propose("style", "Synthetic reviewed preference",
                           source="synthetic", approved=True)
        self.store.add_decision("What is our test plan?", "Review",
                                "Evidence before action", source="synthetic",
                                approved=True)
        core = []
        for table, predicate in (
            ("identity", "status='approved'"),
            ("decisions", "status='approved' AND split='train'"),
            ("episodes", "status='approved'"),
        ):
            rows = [list(row) for row in self.store.db.execute(
                f"SELECT * FROM {table} WHERE {predicate} ORDER BY id")]
            core.append([table, rows])
        historical = _fingerprint(core)
        self.assertEqual(_reference_fingerprint(self.store), historical)
        sample = self.store.add_sample("SYNTHETIC PENDING WRITING",
                                       source="synthetic")
        self.assertEqual(_reference_fingerprint(self.store), historical)
        self.store.set_review("writing_samples", sample, "approved")
        self.assertNotEqual(_reference_fingerprint(self.store), historical)
        self.store.set_review("writing_samples", sample, "rejected")
        self.assertEqual(_reference_fingerprint(self.store), historical)

    def test_reference_fingerprint_follows_approved_style_and_disputes(self):
        before = _reference_fingerprint(self.store)
        sample = self.store.add_sample("Example of my own writing, synthetic",
                                       source="synthetic")
        self.assertEqual(_reference_fingerprint(self.store), before)
        self.store.set_review("writing_samples", sample, "approved")
        after = _reference_fingerprint(self.store)
        self.assertNotEqual(before, after)
        first = self.store.observe("Feature A", "A preference",
                                   tags=["python"], source="synthetic")
        second = self.store.observe("Feature B", "B preference",
                                    tags=["python"], source="synthetic")
        self.store.review_episode(first, "approved")
        self.store.review_episode(second, "approved")
        current = _reference_fingerprint(self.store)
        self.store.dispute(first, second, "Owner will review")
        self.assertNotEqual(_reference_fingerprint(self.store), current)

    def test_writing_approval_midflight_invalidates_heldout_evaluation(self):
        self.store.add_decision(
            "Would this safely sourced synthetic decision be acceptable?",
            "Yes", "Private protected rationale", source="synthetic",
            approved=True, split="test", options=["Yes", "No"])
        sample = self.store.add_sample("Short style example",
                                       source="synthetic")
        store = self.store
        class AlteringLocalModel:
            model = "synthetic"
            def generate(self, messages, **kwargs):
                store.set_review("writing_samples", sample, "approved")
                return '{"choice_letter":"A"}'
        with self.assertRaisesRegex(ValueError, "reference evidence changed"):
            evaluate_decisions(store, AlteringLocalModel(), split="test")

    def test_old_approved_identity_beyond_200_is_retrieved_without_context_window(self):
        self.store.propose(
            "identity", "SYNTHETIC_ANCIENT_LIDAR developed precision inertial navigation",
            source="synthetic", approved=True)
        for i in range(310):
            self.store.propose(
                "identity", "Unrelated synthetic ceramic pottery detail " + str(i),
                source="synthetic", approved=True)
        from unittest.mock import patch
        with patch.object(self.store, "context",
                          side_effect=AssertionError("No latest-200 context shortcut")):
            result = profile(self.store, "What did I develop for inertial navigation?")
        self.assertIn("SYNTHETIC_ANCIENT_LIDAR", json.dumps(result))
        self.assertNotIn("ceramic pottery", json.dumps(result))

    def test_old_decisions_beyond_latest_200_and_no_heldout_leak(self):
        self.store.add_decision(
            "Should we calibrate our inertial guidance sensors?",
            "Calibrate sensors", "synthetic confidence in navigation calibration",
            source="synthetic", approved=True)
        self.store.add_decision(
            "Should we calibrate our inertial guidance prototype?",
            "No", "PRIVATE_TEST_GOLD_UNAVAILABLE", source="synthetic",
            options=["No", "Yes"], split="test", approved=True)
        for i in range(315):
            self.store.add_decision(
                "Where should we store the synthetic orchard crates number " + str(i) + "?",
                "In barn", "synthetic garden harvest logistics",
                source="synthetic", approved=True)
        selected = profile(
            self.store, "How would I handle inertial navigation sensor calibration?")
        self.assertIn("Calibrate sensors", json.dumps(selected))
        self.assertNotIn("PRIVATE_TEST_GOLD_UNAVAILABLE", json.dumps(selected))
        self.assertNotIn("garden harvest logistics", json.dumps(selected))

    def test_old_reviewed_writing_snippet_finds_match_beyond_opening(self):
        sample = self.store.add_sample(
            ("Synthetic filler prose for an approved style sample. " * 20) +
            "microphonetics grounded precise explanations for this topic",
            source="synthetic:older")
        self.store.set_review("writing_samples", sample, "approved")
        for i in range(225):
            other = self.store.add_sample(
                "Newer approved plant and fertilizer sample " + str(i),
                source="synthetic:newer")
            self.store.set_review("writing_samples", other, "approved")
        messages = profile(self.store, "Explain microphonetics in my style")
        samples = messages["approved_writing_examples"]
        self.assertTrue(any("microphonetics" in x["excerpt"] for x in samples))
        self.assertTrue(all(len(x["excerpt"]) <= 700 for x in samples))
        self.assertTrue(any(x["excerpt_truncated"] for x in samples))
        self.assertLessEqual(len(build_messages(
            self.store, "Explain microphonetics in my style", "twin")[1]["content"]),
            MAX_PROFILE_CHARS + 32)

    def test_revoked_older_approval_excluded_immediately(self):
        item = self.store.propose(
            "identity", "SYNTHETIC_OLD_PRIVATE_EXAMPLE archaeological ocean research",
            source="synthetic", approved=True)
        for i in range(210):
            self.store.propose(
                "identity", "Noisy unrelated synthetic building fixture " + str(i),
                source="synthetic", approved=True)
        self.assertIn("SYNTHETIC_OLD_PRIVATE_EXAMPLE", json.dumps(
            profile(self.store, "archaeological ocean research")))
        self.store.status(item, "rejected")
        self.assertNotIn("SYNTHETIC_OLD_PRIVATE_EXAMPLE", json.dumps(
            profile(self.store, "archaeological ocean research")))

    def test_tie_order_and_profile_budget_stable_over_full_history(self):
        for i in range(270):
            self.store.propose(
                "preference", "synthetic reviewable analysis " + str(i),
                source="synthetic", approved=True)
        once = build_messages(self.store, "reviewable analysis", "twin")
        twice = build_messages(self.store, "reviewable analysis", "twin")
        self.assertEqual(once, twice)
        content = once[1]["content"].split("\n", 1)[1]
        self.assertLessEqual(len(content), MAX_PROFILE_CHARS)
        selected = json.loads(content)["approved_identity"]
        self.assertLessEqual(len(selected), 20)
        self.assertIn("synthetic reviewable analysis 269", str(selected))
        self.assertNotIn("synthetic reviewable analysis 0", str(selected))

    def test_input_without_evidence_abstains_from_personal_claims(self):
        p = profile(self.store, "What would my position be on this?")
        self.assertEqual(p["approved_identity"], [])
        self.assertEqual(p["approved_decisions"], [])
        self.assertIn("acknowledge uncertainty",
                      build_messages(self.store, "Question", "twin")[0]["content"])


if __name__ == "__main__":
    unittest.main()
