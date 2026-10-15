"""Synthetic near-copy leakage checks and model-cohort pilot accounting."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from athenz.experience import ExperienceStore
from athenz.style_overlap import strongly_overlaps
from athenz.style_comparison import create_comparison, ComparisonArchive
from athenz.style_tasks import StyleTaskBank
from athenz.style_readiness import style_readiness


class LocalDouble:
    def __init__(self):
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return "PERSONALIZED_SYNTHETIC" if "REFERENCE PROFILE" in str(messages) else "NEUTRAL_SYNTHETIC"


class StyleEvaluationIntegrityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ExperienceStore(Path(temp.name) / "private")
        self.addCleanup(self.store.close)
        for index in range(3):
            train = self.store.add_sample(
                f"My approach to concrete delivery involves inspecting "
                f"the equipment and confirming the schedule before leaving on job {index}.",
                source="synthetic:owner", split="train")
            withheld = self.store.add_sample(
                f"When writing to a neighbor about their garden I keep the "
                f"message personal specific and encouraging without making "
                f"unnecessary promises and use example {index}.",
                source="synthetic:owner", split="test")
            self.store.set_review("writing_samples", train, "approved")
            self.store.set_review("writing_samples", withheld, "approved")
        self.assertTrue(style_readiness(self.store)["pilot_evaluation_sufficient"])

    def compare(self, task, *, tag="synthetic-local", fingerprint=None, chooser=0):
        model = LocalDouble()
        case = create_comparison(
            self.store, task, confirmed=True, model_tag=tag,
            route_fn=lambda s: "synthetic-active",
            digest_fn=lambda selected: fingerprint or "a" * 64,
            client_factory=lambda _: model, chooser=lambda bound: chooser)
        return case, model

    def archive(self):
        archive = ComparisonArchive(self.store)
        self.addCleanup(archive.close)
        return archive

    def test_exact_and_unicode_compatibility_normalization(self):
        self.assertTrue(strongly_overlaps(
            "Ｔｈｅ engineer plans carefully.", "the ENGINEER, plans carefully!"))
        self.assertTrue(strongly_overlaps("Short text", "short-text"))
        self.assertFalse(strongly_overlaps(
            "A short thank you", "A long weather forecast"))
        self.assertFalse(strongly_overlaps("", "Nonempty text"))

    def test_near_copy_substitutions_detected_without_requiring_exact_quote(self):
        reference = (
            "Before starting a demanding workday I inspect all the equipment, "
            "confirm the weather conditions, check my route, and document "
            "anything unusual for the crew.")
        disguised = (
            "Please revise: Before beginning a demanding workday I inspect "
            "all the equipment, confirm weather conditions, check my route, "
            "and document anything unusual for the crew.")
        self.assertTrue(strongly_overlaps(disguised, reference))
        self.assertFalse(strongly_overlaps(
            "Write a respectful note to the neighborhood association "
            "about scheduling some weekend volunteer events.",
            reference))

    def test_long_verbatim_fragment_of_longer_reference_is_blocked(self):
        reference = (
            "The owner describes a detailed journey along the river and "
            "explains the changing weather conditions, navigation signals, "
            "and many careful decisions across the entire passage. " * 20)
        task = ("Write a short summary of changing weather conditions "
                "navigation signals and many careful decisions across "
                "the entire passage.")
        self.assertTrue(strongly_overlaps(reference, task))

    def test_test_split_near_copy_fails_before_model_call(self):
        text = self.store.db.execute(
            "SELECT text FROM writing_samples WHERE split='test' LIMIT 1"
        ).fetchone()[0]
        task = "Please rephrase this passage: " + text.replace(
            "personal specific", "warm specific", 1)
        model = LocalDouble()
        with self.assertRaisesRegex(ValueError, "copies protected"):
            create_comparison(
                self.store, task, confirmed=True,
                route_fn=lambda s: "synthetic-local",
                client_factory=lambda _: model)
        self.assertEqual(model.calls, [])
        self.assertFalse((self.store.home / "twin-style-comparisons.sqlite3").exists())

    def test_training_split_near_copy_refuses_memorization_bonus(self):
        text = self.store.db.execute(
            "SELECT text FROM writing_samples WHERE split='train' LIMIT 1"
        ).fetchone()[0]
        task = "Rewrite the next example in the author's style: " + text.replace(
            "the schedule", "my schedule")
        model = LocalDouble()
        with self.assertRaisesRegex(ValueError, "copies approved training"):
            create_comparison(
                self.store, task, confirmed=True,
                route_fn=lambda s: "synthetic-local",
                client_factory=lambda _: model)
        self.assertEqual(model.calls, [])

    def test_task_bank_review_rejects_hidden_near_copy(self):
        text = self.store.db.execute(
            "SELECT text FROM writing_samples WHERE split='test' LIMIT 1"
        ).fetchone()[0]
        bank = StyleTaskBank(self.store, create=True)
        self.addCleanup(bank.close)
        number = bank.add("Please rewrite: " + text.replace(
            "their garden", "the garden"), confirmed=True)
        with self.assertRaisesRegex(ValueError, "copies protected"):
            bank.review(self.store, number, "approved", confirmed=True)
        self.assertEqual(bank.summary(self.store)["pending"], 1)

    def test_cross_split_near_copy_cannot_receive_owner_approval(self):
        train = self.store.add_sample(
            "Before making a difficult decision I carefully inspect the "
            "available evidence, discuss the options with my team and record "
            "the practical reasons that support the final choice.",
            source="synthetic:owner", split="train")
        self.store.set_review("writing_samples", train, "approved")
        test = self.store.add_sample(
            "Before making a difficult decision I carefully review the "
            "available evidence, discuss the options with my team and record "
            "practical reasons supporting the final choice.",
            source="synthetic:owner", split="test")
        with self.assertRaisesRegex(ValueError, "Duplicate writing sample"):
            self.store.set_review("writing_samples", test, "approved")
        self.assertEqual(self.store.db.execute(
            "SELECT status FROM writing_samples WHERE id=?", (test,)
        ).fetchone()[0], "pending")

    def test_mixed_models_hide_pooled_win_rate_but_keep_honest_counts(self):
        a, _ = self.compare(
            "Write a short thank-you note to a helpful colleague.",
            tag="synthetic-local-a", fingerprint="a" * 64)
        b, _ = self.compare(
            "Write a supportive greeting for a new neighbor.",
            tag="synthetic-local-b", fingerprint="b" * 64, chooser=1)
        bank = self.archive()
        bank.rate(self.store, a, "A", confirmed=True)  # Twin wins
        bank.rate(self.store, b, "A", confirmed=True)  # Neutral wins
        report = bank.report(self.store)
        self.assertEqual(report["valid_owner_ratings"], 2)
        self.assertEqual(report["twin_preferred"], 1)
        self.assertEqual(report["neutral_preferred"], 1)
        self.assertEqual(report["model_cohort_count"], 2)
        self.assertTrue(report["mixed_model_pooled_rate_suppressed"])
        self.assertIsNone(report["twin_preference_non_tie_rate"])
        self.assertIsNone(report["wilson_interval_95"])
        self.assertFalse(report["minimum_pilot_non_ties_reached"])
        self.assertEqual({c["twin_preferred"] for c in report["model_cohorts"]},
                         {0, 1})
        for c in report["model_cohorts"]:
            self.assertEqual(len(c["cohort_id"]), 16)
            self.assertEqual(c["valid_owner_ratings"], 1)
        redacted = json.dumps(report)
        self.assertNotIn("synthetic-local-a", redacted)
        self.assertNotIn("synthetic-local-b", redacted)
        self.assertNotIn("helpful colleague", redacted)
        self.assertFalse(report["model_digest_rechecked_during_report"])

    def test_same_name_new_digest_forms_distinct_studies(self):
        a, _ = self.compare(
            "Write a friendly card to a neighbor who helped with leaves.",
            tag="same-tag", fingerprint="a" * 64)
        b, _ = self.compare(
            "Write a heartfelt card celebrating a friend's promotion.",
            tag="same-tag", fingerprint="b" * 64)
        archive = self.archive()
        archive.rate(self.store, a, "A", confirmed=True)
        archive.rate(self.store, b, "A", confirmed=True)
        self.assertEqual(archive.report(self.store)["model_cohort_count"], 2)

    def test_single_model_has_regular_pilot_metrics(self):
        a, _ = self.compare(
            "Write a warm message to a retiring coworker.",
            fingerprint="a" * 64)
        b, _ = self.compare(
            "Write a thoughtful note to someone recovering from illness.",
            fingerprint="a" * 64)
        archive = self.archive()
        archive.rate(self.store, a, "A", confirmed=True)
        archive.rate(self.store, b, "tie", confirmed=True)
        report = archive.report(self.store)
        self.assertFalse(report["mixed_model_pooled_rate_suppressed"])
        self.assertEqual(report["model_cohort_count"], 1)
        self.assertEqual(report["twin_preference_non_tie_rate"], 1.0)
        self.assertEqual(report["model_cohorts"][0]["ties"], 1)
        self.assertFalse(report["model_accuracy_or_identity_certified"])

    def test_stale_model_group_excluded_after_approval_revoked(self):
        a, _ = self.compare("Write a respectful note for the local volunteer club.")
        self.archive().rate(self.store, a, "A", confirmed=True)
        example = self.store.db.execute(
            "SELECT id FROM writing_samples WHERE split='train' LIMIT 1"
        ).fetchone()[0]
        self.store.set_review("writing_samples", example, "rejected")
        report = self.archive().report(self.store)
        self.assertEqual(report["stale_cases"], 1)
        self.assertEqual(report["model_cohort_count"], 0)
        self.assertFalse(report["mixed_model_pooled_rate_suppressed"])
        self.assertIsNone(report["twin_preference_non_tie_rate"])

    def test_unrated_second_model_is_not_treated_as_a_rated_cohort(self):
        a, _ = self.compare("Write a short note celebrating a new project.", tag="a")
        b, _ = self.compare("Write an invitation to an autumn barbecue.", tag="b")
        self.archive().rate(self.store, a, "A", confirmed=True)
        report = self.archive().report(self.store)
        self.assertEqual(report["model_cohort_count"], 1)
        self.assertEqual(report["unrated_current_cases"], 1)
        self.assertIsNotNone(report["twin_preference_non_tie_rate"])
        self.assertGreater(b, a)


if __name__ == "__main__":
    unittest.main()
