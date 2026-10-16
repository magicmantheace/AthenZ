"""Synthetic-only category coverage and balanced Twin scoring tests."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from athenz.experience import ExperienceStore
from athenz.family_audit import (
    CategoryScores, FamilyAudit, category_diversity_gate,
    create_family_template,
)
from athenz.paired_decisions import evaluate_paired_decisions


SCENARIOS = (
    "During an equipment handoff, should the inspection checklist be signed?",
    "Which spare-part record should a warehouse team archive after maintenance?",
    "Before a simulated train departure, how should the crew verify brakes?",
    "When reviewing a construction invoice, should quantities be reconciled?",
    "How should a logistics dispatcher communicate a revised route?",
    "For a fictional mountain expedition, should the group plan rest stops?",
    "When mapping an imaginary canal, which symbols best mark locks?",
    "Should a garden planner reserve space for pollinator flowers?",
    "Which order should a public library use for reorganizing the shelves?",
    "When scheduling a museum exhibition, how should works be grouped?",
    "For a fictional film poster, should the title be above the illustration?",
    "How might an orchestral composer arrange a closing brass refrain?",
    "Which palette would fit a watercolor painting of an autumn marsh?",
    "When drafting a fictional dialogue, should the exchange end with a question?",
    "What shape should a sculptor choose for an imaginary stone installation?",
)
DOMAINS = ("work", "planning", "creative")


class ConstantPredictionModel:
    model = "synthetic-constant-model"

    def __init__(self):
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return '{"choice_letter":"A"}'


class CategoryDiversityTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.store = ExperienceStore(Path(t.name) / "owner-local")
        self.addCleanup(self.store.close)
        self.store.propose("style", "Prefer a concise, considered answer",
                           source="synthetic", approved=True)
        self.store.add_decision(
            "When a sandbox build has unverified checks, should it be shipped?",
            "Defer", "Review checks before release", source="synthetic",
            split="train", approved=True, options=["Ship", "Defer"])
        for scenario in SCENARIOS:
            self.store.add_decision(
                scenario, "First option", "Only a synthetic evaluation label",
                source="synthetic", split="test", approved=True,
                options=["First option", "Second option"])
        create_family_template(self.store)
        self.path = self.store.home / "decision-family-audit.json"
        self.payload = json.loads(self.path.read_text(encoding="utf-8"))
        for pos, entry in enumerate(self.payload["cases"]):
            entry["family"] = f"independent_{pos:03d}"
            entry["category"] = "work" if pos == 0 else DOMAINS[(pos - 1) // 5]
        self._save()

    def _save(self):
        self.path.write_text(json.dumps(self.payload, ensure_ascii=False),
                             encoding="utf-8")
        self.path.chmod(0o600)

    def _eval(self, *, model=None, limit=15, require=True):
        model = model or ConstantPredictionModel()
        return evaluate_paired_decisions(
            self.store, model, split="test", limit=limit, seed=19,
            family_audit=FamilyAudit(self.store),
            require_category_diversity=require)

    def test_balanced_fifteen_cases_pass_preflight_and_score(self):
        model = ConstantPredictionModel()
        report = self._eval(model=model)
        self.assertEqual(report["schema"], 7)
        self.assertEqual(report["model_requests"], 30)
        self.assertEqual(len(model.calls), 30)
        self.assertTrue(report["require_category_diversity"])
        audited = report["family_audit"]
        self.assertTrue(audited["broad_coverage_gate_met"])
        self.assertEqual(audited["eligible_category_count"], 3)
        self.assertEqual(set(audited["category_metrics"]), set(DOMAINS))
        self.assertAlmostEqual(audited["macro_twin_accuracy"],
                         report["twin_accuracy"])
        self.assertAlmostEqual(audited["macro_neutral_accuracy"],
                         report["neutral_accuracy"])
        self.assertAlmostEqual(audited["macro_paired_accuracy_difference"],
                         report["paired_accuracy_difference"])
        self.assertNotIn("independent_001", json.dumps(report))
        self.assertNotIn("inspection checklist", json.dumps(report))
        self.assertNotIn("independent_001", str(model.calls))

    def test_unbalanced_or_undersized_selection_refuses_without_model(self):
        model = ConstantPredictionModel()
        with self.assertRaisesRegex(ValueError, "broad independent coverage"):
            self._eval(model=model, limit=10)
        self.assertEqual(len(model.calls), 0)

        self.payload["cases"][15]["category"] = "work"
        self._save()
        with self.assertRaisesRegex(ValueError, "broad independent coverage"):
            self._eval(model=model)
        self.assertEqual(len(model.calls), 0)

    def test_default_audit_remains_optional_and_reports_no_macro(self):
        model = ConstantPredictionModel()
        result = self._eval(model=model, limit=4, require=False)
        self.assertFalse(result["require_category_diversity"])
        audit = result["family_audit"]
        self.assertFalse(audit["broad_coverage_gate_met"])
        self.assertIsNone(audit["macro_paired_accuracy_difference"])
        self.assertEqual(audit["category_metrics"], {})
        self.assertEqual(audit["small_categories_suppressed"], 1)
        self.assertEqual(len(model.calls), 8)

    def test_helper_refuses_bad_input_types_and_domination(self):
        balanced = {i: DOMAINS[i // 5] for i in range(15)}
        self.assertTrue(category_diversity_gate(balanced))
        self.assertFalse(category_diversity_gate({i: "work" for i in range(15)}))
        self.assertFalse(category_diversity_gate({
            i: "work" if i < 16 else "planning" if i < 21 else "creative"
            for i in range(26)}))
        self.assertFalse(category_diversity_gate({
            i: "other" if i < 5 else DOMAINS[0 if i < 10 else 1]
            for i in range(15)}))
        for invalid in (None, [], {True: "work"}, {1: ["work"]}, {1: "personal"}):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    category_diversity_gate(invalid)

    def test_macro_average_equal_weights_for_unequal_eligible_categories(self):
        scores = CategoryScores()
        for category, count, twin, neutral in (
                ("work", 5, 5, 0), ("planning", 5, 0, 5),
                ("creative", 10, 10, 5)):
            for index in range(count):
                scores.add(category, twin_correct=index < twin,
                           neutral_correct=index < neutral)
        report = scores.report(20)
        self.assertTrue(report["broad_coverage_gate_met"])
        self.assertEqual(report["eligible_category_count"], 3)
        self.assertAlmostEqual(report["macro_twin_accuracy"], 2 / 3)
        self.assertAlmostEqual(report["macro_neutral_accuracy"], 0.5)
        self.assertAlmostEqual(report["macro_paired_accuracy_difference"], 1 / 6)

    def test_macro_not_reported_when_only_two_eligible_categories(self):
        scores = CategoryScores()
        for i in range(8):
            scores.add("work" if i < 5 else "planning",
                       twin_correct=True, neutral_correct=False)
        result = scores.report(8)
        self.assertIsNone(result["macro_twin_accuracy"])
        self.assertIsNone(result["macro_paired_accuracy_difference"])
        self.assertEqual(result["eligible_category_count"], 1)
        self.assertNotIn("planning", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
