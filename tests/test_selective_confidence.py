"""Synthetic, aggregate-only selective confidence threshold checks."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from athenz.experience import ExperienceStore
from athenz.paired_decisions import evaluate_paired_decisions
from athenz.paired_stats import SelectiveConfidenceAccumulator


class ConfidenceModel:
    model = "synthetic-local"
    def __init__(self):
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        # Deterministic local synthetic-only case ID and confidence.
        # The answer is a prediction, never the correct choice from storage.
        scenario = messages[-1]["content"]
        number = next(int(x) for x in scenario.replace("?", " ").split()
                      if x.isdigit())
        return json.dumps({"choice_letter": "A",
                           "confidence": (0.55, 0.65, 0.75, 0.85, 0.95)[number % 5]})


class SelectiveConfidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ExperienceStore(Path(temp.name) / "private")
        self.addCleanup(self.store.close)
        self.store.propose("style", "Prefer testing assumptions",
                           source="synthetic", approved=True)
        for index in range(20):
            self.store.add_decision(
                f"Synthetic calibration question {index}?",
                "Option 1", "Synthetic-only preference",
                source="synthetic", approved=True,
                split="calibration", options=["Option 1", "Option 2"])

    def evaluate(self, model=None, **options):
        return evaluate_paired_decisions(
            self.store, model or ConfidenceModel(),
            split="calibration", limit=20, seed=19,
            score_confidence=True, **options)

    def test_threshold_grid_is_aggregate_and_exploratory(self):
        model = ConfidenceModel()
        report = self.evaluate(model, calibration_grid=True,
                               confidence_cutoff=0.7)
        self.assertEqual(report["schema"], 7)
        self.assertEqual(report["total"], 20)
        self.assertEqual(report["model_requests"], 40)
        self.assertEqual(len(model.calls), 40)
        self.assertTrue(report["confidence_selection"]["enabled"])
        self.assertTrue(report["confidence_selection"]["raw_prediction_accuracy_unchanged"])
        self.assertFalse(report["confidence_selection"]["selected_cutoff_applies_to_inference"])
        for arm in ("twin", "neutral"):
            data = report["confidence_selection"][arm]
            self.assertEqual(data["scored_predictions"], 20)
            self.assertEqual(data["selected_cutoff"], 0.7)
            self.assertEqual(data["selected_metrics"]["status"], "descriptive")
            self.assertEqual(len(data["calibration_grid"]["thresholds"]), 5)
            self.assertFalse(data["cutoff_chosen_by_algorithm"])
            self.assertFalse(data["confidence_is_calibrated"])
        self.assertNotIn("Synthetic calibration question", json.dumps(report))
        self.assertNotIn("Synthetic-only preference", json.dumps(report))
        self.assertNotIn('"cases"', json.dumps(report))
        baseline = self.evaluate(calibration_grid=False)
        for field in ("twin_correct", "neutral_correct", "twin_only_correct",
                      "neutral_only_correct", "both_correct", "both_wrong",
                      "exact_mcnemar_two_sided_p", "heldout_sha256"):
            self.assertEqual(report[field], baseline[field])

    def test_calibration_grid_not_available_on_test_split(self):
        model = ConfidenceModel()
        with self.assertRaises(ValueError):
            evaluate_paired_decisions(
                self.store, model, split="test", limit=20, seed=19,
                score_confidence=True, calibration_grid=True)
        self.assertEqual(model.calls, [])

    def test_confidence_threshold_requires_confidence_output(self):
        model = ConfidenceModel()
        with self.assertRaises(ValueError):
            evaluate_paired_decisions(
                self.store, model, split="calibration", limit=20, seed=19,
                confidence_cutoff=0.7)
        self.assertEqual(model.calls, [])

    def test_cutoff_input_is_strict(self):
        for value in (True, False, -0.1, 0.0, 0.4, 0.55, 0.91,
                      1.0, "0.7", float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SelectiveConfidenceAccumulator.validate_cutoff(value)
        for value in (0.5, 0.6, 0.7, 0.8, 0.9):
            self.assertEqual(
                SelectiveConfidenceAccumulator.validate_cutoff(value), value)

    def test_small_accepted_groups_are_suppressed(self):
        data = SelectiveConfidenceAccumulator()
        for index in range(20):
            data.add(0.95 if index < 4 else 0.55, correct=index % 2 == 0)
        report = data.report(20, cutoff=0.9, calibration_grid=True)
        self.assertEqual(report["selected_metrics"]["status"],
                         "insufficient-accepted-cases")
        self.assertIsNone(report["selected_metrics"]["accuracy"])
        self.assertIsNone(report["selected_metrics"]["coverage"])
        for item in report["calibration_grid"]["thresholds"]:
            if item["cutoff"] == 0.9:
                self.assertIsNone(item["accuracy"])
        self.assertNotIn("correct", json.dumps(report))

    def test_small_calibration_set_never_claims_grid_support(self):
        data = SelectiveConfidenceAccumulator()
        for _ in range(7):
            data.add(0.85, correct=True)
        report = data.report(7, calibration_grid=True)
        self.assertEqual(report["calibration_grid"]["thresholds"], [])
        self.assertEqual(report["calibration_grid"]["status"],
                         "insufficient-calibration-samples")

    def test_cutoff_coverage_uses_all_cases_not_just_scored(self):
        data = SelectiveConfidenceAccumulator()
        for index in range(10):
            data.add(0.95 if index < 5 else 0.5, correct=index < 5)
        report = data.report(20, cutoff=0.9)
        self.assertEqual(report["selected_metrics"]["coverage"], 0.25)
        self.assertEqual(report["selected_metrics"]["accuracy"], 1.0)
        self.assertEqual(report["scored_predictions"], 10)
        self.assertFalse(report["selective_scores_are_independent_tests"])


if __name__ == "__main__":
    unittest.main()
