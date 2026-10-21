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

    def test_childhood_synonym_retrieves_only_approved_history(self):
        approved = self.store.propose(
            "identity", "SYNTHETIC_OWNER was raised in a fictional valley",
            source="synthetic", approved=True)
        self.store.propose(
            "identity", "PENDING_OWNER was raised on a secret moon",
            source="synthetic", approved=False)
        question = "Where did I grow up?"
        result = json.dumps(profile(self.store, question))
        self.assertIn("SYNTHETIC_OWNER", result)
        self.assertNotIn("PENDING_OWNER", result)
        self.assertIn("Approved topical reference data",
                      build_messages(self.store, question, "twin")[0]["content"])
        self.store.status(approved, "rejected")
        revoked = json.dumps(profile(self.store, question))
        self.assertNotIn("SYNTHETIC_OWNER", revoked)
        self.assertIn("No topically matching approved owner fact",
                      build_messages(self.store, question, "twin")[0]["content"])

    def test_growing_up_and_hometown_phrasings_retrieve_approved_origin(self):
        self.store.propose(
            "identity", "SYNTHETIC_ORIGIN was raised in a fictional valley",
            source="synthetic", approved=True)
        for question in (
            "Where did I grow up?",
            "Where did I grew up?",
            "Where have I grown up?",
            "Tell me about my childhood",
            "What is my hometown?",
        ):
            with self.subTest(question=question):
                result = profile(self.store, question)
                self.assertIn("SYNTHETIC_ORIGIN", json.dumps(result))
                self.assertIn(
                    "Approved topical reference data",
                    build_messages(self.store, question, "twin")[0]["content"])

    def test_favorite_colour_spelling_retrieves_reviewed_preference(self):
        self.store.propose(
            "preference", "My favourite colour is ultraviolet",
            source="synthetic", approved=True)
        result = profile(self.store, "What is my favorite color?")
        self.assertIn("ultraviolet", json.dumps(result))
        self.assertIn("Approved topical reference data",
                      build_messages(self.store, "What is my favorite color?",
                                     "twin")[0]["content"])

    def test_style_does_not_count_as_supported_owner_biography(self):
        self.store.propose("style", "Use crisp short paragraphs",
                           source="synthetic", approved=True)
        self.store.propose("identity", "SYNTHETIC_OWNER studies astronomy",
                           source="synthetic", approved=True)
        messages = build_messages(self.store, "What is my favorite animal?", "twin")
        self.assertIn("Use crisp short paragraphs", messages[1]["content"])
        self.assertNotIn("SYNTHETIC_OWNER", messages[1]["content"])
        self.assertIn("No topically matching approved owner fact",
                      messages[0]["content"])
        self.assertIn("Ordinary nonpersonal conversation can proceed normally",
                      build_messages(self.store, "Tell me a joke", "twin")[0]["content"])
        self.assertNotIn("TWIN EVIDENCE STATUS",
                         build_messages(self.store, "Do my work", "agent")[0]["content"])

    def test_oversized_relevant_memory_does_not_claim_available_evidence(self):
        self.store.propose(
            "identity", "SYNTHETIC_ULTRA_FICTIONAL quantumzebra " + ("x" * 8000),
            source="synthetic", approved=True)
        messages = build_messages(
            self.store, "What is my quantumzebra identity?", "twin")
        self.assertNotIn("SYNTHETIC_ULTRA_FICTIONAL",
                         messages[1]["content"])
        self.assertIn("No topically matching approved owner fact",
                      messages[0]["content"])
        self.assertEqual(
            json.loads(messages[1]["content"].split("\n", 1)[1])["approved_identity"],
            [])

    def test_topically_relevant_packed_memory_counts_as_available(self):
        self.store.propose(
            "identity", "SYNTHETIC_OWNER researched quantumzebra mapping",
            source="synthetic", approved=True)
        messages = build_messages(
            self.store, "What is my quantumzebra research?", "twin")
        self.assertIn("SYNTHETIC_OWNER", messages[1]["content"])
        self.assertIn("Approved topical reference data",
                      messages[0]["content"])

    def test_generic_preference_words_do_not_make_unrelated_evidence_topical(self):
        self.store.propose("preference", "I prefer synthetic granite counters",
                           source="synthetic", approved=True)
        self.store.add_decision(
            "Would I choose synthetic granite for the kitchen?",
            "Granite", "Granite finish preference", source="synthetic",
            approved=True)
        episode_id = self.store.observe(
            "Synthetic granite purchase", "I prefer synthetic granite",
            tags=["granite"], source="synthetic")
        self.store.review_episode(episode_id, "approved")
        messages = build_messages(self.store, "Do I prefer thunderstorms?", "twin")
        contents = messages[1]["content"]
        self.assertNotIn("synthetic granite", contents)
        self.assertIn("No topically matching approved owner fact",
                      messages[0]["content"])
        self.assertEqual(profile(self.store, "Do I prefer thunderstorms?")[
            "approved_decisions"], [])
        self.assertEqual(profile(self.store, "Do I prefer thunderstorms?")[
            "approved_relevant_episodes"], [])

    def test_older_topical_episode_survives_generic_word_crowding(self):
        target = self.store.observe(
            "Synthetic thunderstorms", "SYNTHETIC_RAIN_TARGET checked forecast",
            tags=[], source="synthetic")
        self.store.review_episode(target, "approved")
        for i in range(12):
            unrelated = self.store.observe(
                "Unrelated synthetic ceramics " + str(i),
                "I prefer pottery in synthetic study",
                tags=[], source="synthetic")
            self.store.review_episode(unrelated, "approved")
        evidence = profile(self.store, "Do I prefer thunderstorms?")
        self.assertIn("SYNTHETIC_RAIN_TARGET",
                      json.dumps(evidence["approved_relevant_episodes"]))
        self.assertNotIn("pottery", json.dumps(evidence))
        self.assertIn("Approved topical reference data",
                      build_messages(self.store, "Do I prefer thunderstorms?",
                                     "twin")[0]["content"])

    def test_question_scaffolding_does_not_select_unrelated_choices(self):
        self.store.add_decision(
            "Which synthetic fence coating would I choose?",
            "Blue coating", "A synthetic fence design",
            source="synthetic", approved=True)
        self.store.propose(
            "preference", "Which synthetic fence coating do I prefer?",
            source="synthetic", approved=True)
        result = build_messages(
            self.store, "Which kitchen tool do I prefer?", "twin")
        self.assertEqual(
            json.loads(result[1]["content"].split("\n", 1)[1])[
                "approved_decisions"], [])
        self.assertNotIn("synthetic fence coating", result[1]["content"])
        self.assertIn("No topically matching approved owner fact",
                      result[0]["content"])

    def test_twin_specific_filter_does_not_change_agent_retrieval(self):
        self.store.add_decision(
            "Which synthetic fixture should I choose?",
            "Fixture A", "Older independent Agent retrieval behavior",
            source="synthetic", approved=True)
        question = "Which kitchen appliance should I choose?"
        twin = profile(self.store, question, "twin")
        agent = profile(self.store, question, "agent")
        self.assertEqual(twin["approved_decisions"], [])
        self.assertIn("Fixture A", json.dumps(agent["approved_decisions"]))
        self.assertNotIn(
            "TWIN EVIDENCE STATUS",
            build_messages(self.store, question, "agent")[0]["content"])

    def test_broad_preference_question_retrieves_approved_preferences(self):
        self.store.propose("preference", "I prefer synthetic granite counters",
                           source="synthetic", approved=True)
        messages = build_messages(self.store, "What are my preferences?", "twin")
        self.assertIn("synthetic granite counters", messages[1]["content"])
        self.assertIn("Approved topical reference data",
                      messages[0]["content"])

    def test_specific_question_does_not_confuse_different_favorites(self):
        self.store.propose("preference", "My favorite synthetic color is copper",
                           source="synthetic", approved=True)
        msgs = build_messages(self.store, "What is my favorite animal?", "twin")
        self.assertNotIn("synthetic color is copper", msgs[1]["content"])
        self.assertIn("No topically matching approved owner fact",
                      msgs[0]["content"])

    def test_input_without_evidence_abstains_from_personal_claims(self):
        p = profile(self.store, "What would my position be on this?")
        self.assertEqual(p["approved_identity"], [])
        self.assertEqual(p["approved_decisions"], [])
        self.assertIn("acknowledge uncertainty",
                      build_messages(self.store, "Question", "twin")[0]["content"])


if __name__ == "__main__":
    unittest.main()
