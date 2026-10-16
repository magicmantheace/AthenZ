"""Synthetic-only frozen owner final-test plan integrity tests."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.experience import ExperienceStore
from athenz.family_audit import create_family_template
from athenz.frozen_decision_plan import FrozenTestPlan, freeze_test_plan
from athenz.paired_decisions import evaluate_paired_decisions, main

_DIGEST = "a" * 64
_MODEL = "synthetic-local"


class FixedModel:
    model = _MODEL

    def __init__(self, callback=None):
        self.calls = []
        self.callback = callback

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.callback is not None:
            self.callback(len(self.calls))
        return '{"choice_letter":"A"}'


class FrozenDecisionPlanTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = ExperienceStore(Path(folder.name) / "owner-private")
        self.addCleanup(self.store.close)
        self.store.propose("style", "Write carefully and clearly",
                           source="synthetic", approved=True)
        self.ids = [
            self.store.add_decision(
                "For a model greenhouse, which panel color should be used?",
                "Amber", "Synthetic first test", source="synthetic",
                approved=True, split="test", options=["Amber", "Blue"]),
            self.store.add_decision(
                "For an imaginary planetary rover, which antenna fits?",
                "Short", "Synthetic second test", source="synthetic",
                approved=True, split="test", options=["Short", "Tall"]),
        ]
        self.options = {
            "limit": 2, "seed": 19, "allow_abstain": False,
            "score_confidence": False, "confidence_cutoff": None,
            "family_audit": False,
            "require_category_diversity": False, "stability_trials": 1,
        }
        self.path = self.store.home / "decision-final-test-plan.json"

    def freeze(self, **overrides):
        options = dict(self.options)
        options.update(overrides)
        freeze_test_plan(self.store, model_tag=_MODEL,
                         model_digest=_DIGEST, **options)
        return FrozenTestPlan(self.store)

    def verify(self, plan, **overrides):
        options = dict(self.options)
        options.update(overrides)
        plan.verify(self.store, model_tag=_MODEL,
                    model_digest=_DIGEST, **options)

    def run_eval(self, plan, model=None, **opts):
        kw = dict(self.options)
        kw.update(opts)
        return evaluate_paired_decisions(
            self.store, model or FixedModel(), split="test",
            limit=kw["limit"], seed=kw["seed"],
            allow_abstain=kw["allow_abstain"],
            score_confidence=kw["score_confidence"],
            confidence_cutoff=kw["confidence_cutoff"],
            require_category_diversity=kw["require_category_diversity"],
            stability_trials=kw["stability_trials"],
            family_audit=None, frozen_test_plan=plan,
            model_identity_digest=_DIGEST)

    def test_freeze_exact_settings_and_aggregate_report(self):
        plan = self.freeze()
        self.verify(plan)
        model = FixedModel()
        result = self.run_eval(plan, model)
        self.assertEqual(len(model.calls), 4)
        self.assertEqual(result["schema"], 7)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["frozen_test_plan"]["plan_sha256"],
                         plan.plan_sha256)
        self.assertTrue(result["frozen_test_plan"]["verified"])
        self.assertNotIn("greenhouse", json.dumps(result))
        self.assertNotIn("Amber", json.dumps(result))
        self.assertNotIn("greenhouse", self.path.read_text())
        self.assertNotIn("Amber", self.path.read_text())
        self.assertNotIn("synthetic", self.path.read_text().split('"model_tag"')[0])
        if __import__("os").name != "nt":
            self.assertEqual(self.path.stat().st_mode & 0o077, 0)

    def test_freeze_never_overwrites_an_existing_owner_plan(self):
        self.freeze()
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "exists"):
            self.freeze()
        self.assertEqual(self.path.read_bytes(), original)

    def test_confidence_threshold_is_frozen_and_cannot_be_retuned(self):
        plan = self.freeze(score_confidence=True, confidence_cutoff=0.7)
        self.verify(plan, score_confidence=True, confidence_cutoff=0.7)
        model = FixedModel()
        with self.assertRaisesRegex(ValueError, "model or protocol"):
            self.run_eval(
                plan, model, score_confidence=True, confidence_cutoff=0.8)
        self.assertEqual(model.calls, [])
        with self.assertRaisesRegex(ValueError, "model or protocol"):
            self.verify(plan, score_confidence=False, confidence_cutoff=None)

    def test_protocol_and_model_identity_mismatch_before_model_calls(self):
        plan = self.freeze()
        with self.assertRaisesRegex(ValueError, "model or protocol"):
            self.verify(plan, seed=20)
        with self.assertRaisesRegex(ValueError, "model or protocol"):
            self.verify(plan, allow_abstain=True)
        with self.assertRaisesRegex(ValueError, "model or protocol"):
            plan.verify(self.store, model_tag=_MODEL,
                        model_digest="b" * 64, **self.options)
        with self.assertRaisesRegex(ValueError, "model or protocol"):
            plan.verify(self.store, model_tag="other-model",
                        model_digest=_DIGEST, **self.options)
        model = FixedModel()
        with self.assertRaisesRegex(ValueError, "model or protocol"):
            self.run_eval(plan, model, stability_trials=2)
        self.assertEqual(model.calls, [])

    def test_consent_revocation_or_new_approved_decision_breaks_frozen_plan(self):
        plan = self.freeze()
        self.store.decision_status(self.ids[0], "rejected")
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            self.verify(plan)
        self.store.decision_status(self.ids[0], "approved")
        self.verify(plan)
        self.store.add_decision(
            "For a synthetic book club, choose the meeting room?",
            "North", "Synthetic gold", source="synthetic", approved=True,
            split="train", options=["North", "South"])
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            self.verify(plan)

    def test_evidence_edit_revokes_plan_even_outside_selected_limit(self):
        self.store.add_decision(
            "A test about a toy telescope mount?", "Heavy",
            "Synthetic extra gold", source="synthetic", approved=True,
            split="test", options=["Light", "Heavy"])
        plan = self.freeze()
        with self.store.db:
            self.store.db.execute(
                "UPDATE decisions SET rationale=? WHERE id=(SELECT MAX(id) FROM decisions)",
                ("Reviewed rationale changed",))
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            self.verify(plan)

    def test_mutated_plan_bytes_are_refused_during_inference(self):
        plan = self.freeze()
        text = self.path.read_text()
        self.path.write_text(text + " ")
        self.path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            self.verify(plan)

    def test_model_side_effect_discards_any_partial_report(self):
        plan = self.freeze()

        def revoke(call):
            if call == 1:
                self.store.decision_status(self.ids[0], "rejected")

        model = FixedModel(callback=revoke)
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            self.run_eval(plan, model)
        self.assertEqual(len(model.calls), 1)

    def test_reviewed_family_manifest_is_bound(self):
        create_family_template(self.store)
        family = self.store.home / "decision-family-audit.json"
        data = json.loads(family.read_text())
        for i, item in enumerate(data["cases"]):
            item["family"] = f"family_{i:03d}"
            item["category"] = "planning"
        family.write_text(json.dumps(data))
        family.chmod(0o600)
        opts = dict(self.options, family_audit=True)
        freeze_test_plan(self.store, model_tag=_MODEL,
                         model_digest=_DIGEST, **opts)
        plan = FrozenTestPlan(self.store)
        plan.verify(self.store, model_tag=_MODEL,
                    model_digest=_DIGEST, **opts)
        data["cases"][0]["category"] = "creative"
        family.write_text(json.dumps(data))
        family.chmod(0o600)
        with self.assertRaises(ValueError):
            plan.verify(self.store, model_tag=_MODEL,
                        model_digest=_DIGEST, **opts)

    def test_invalid_plan_schema_or_readable_file_fails(self):
        self.freeze()
        value = json.loads(self.path.read_text())
        value["schema"] = True
        self.path.write_text(json.dumps(value))
        self.path.chmod(0o600)
        with self.assertRaises(ValueError):
            FrozenTestPlan(self.store)
        if __import__("os").name != "nt":
            self.path.chmod(0o644)
            with self.assertRaises(ValueError):
                FrozenTestPlan(self.store)

    def test_bounded_protocol_and_empty_test_refused(self):
        with self.assertRaises(ValueError):
            self.freeze(stability_trials=3, limit=101)
        with self.assertRaises(ValueError):
            self.freeze(allow_abstain=True, score_confidence=True)
        with self.assertRaises(ValueError):
            self.freeze(seed=True)
        self.assertFalse(self.path.exists())
        for item in self.ids:
            self.store.decision_status(item, "rejected")
        with self.assertRaisesRegex(ValueError, "approved"):
            self.freeze()
        self.assertFalse(self.path.exists())

    def test_cli_freeze_and_check_are_not_model_inference(self):
        with patch("athenz.runtime.checked_active_tag", return_value=None):
            with patch("athenz.runtime.model_digest", return_value=_DIGEST):
                with patch("athenz.paired_decisions.OllamaClient") as client:
                    with patch("builtins.print") as printer:
                        main(["--home", str(self.store.home), "--split", "test",
                              "--limit", "2", "--seed", "19", "--model", _MODEL,
                              "--freeze-test-plan", "--confirm"])
                        main(["--home", str(self.store.home), "--split", "test",
                              "--limit", "2", "--seed", "19", "--model", _MODEL,
                              "--check-test-plan", "--confirm"])
                    client.assert_not_called()
        output = printer.call_args[0][0]
        self.assertNotIn("greenhouse", output)
        self.assertEqual(json.loads(output)["frozen_final_test"], "valid")

    def test_cli_wrong_split_or_combined_actions_fail(self):
        with patch("sys.stderr"):
            for flags in (
                ["--freeze-test-plan"],
                ["--check-test-plan"],
                ["--use-test-plan"],
                ["--freeze-test-plan", "--use-test-plan", "--split", "test"],
                ["--freeze-test-plan", "--family-template", "--split", "test"],
            ):
                with self.subTest(flags=flags), self.assertRaises(SystemExit):
                    main(["--home", str(self.store.home), *flags, "--confirm"])
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
