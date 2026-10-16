"""Private, aggregate-only same-model Twin/neutral decision evaluation tests."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from athenz.experience import ExperienceStore
from athenz.paired_decisions import evaluate_paired_decisions, main


class PairedModel:
    model = "synthetic-local"

    def __init__(self, callback=None, response=None):
        self.calls = []
        self.callback = callback
        self.response = response

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.callback is not None:
            self.callback(len(self.calls))
        if isinstance(self.response, BaseException):
            raise self.response
        if self.response is not None:
            return self.response
        msg = messages[-1]["content"]
        options = dict(re.findall(r"(?m)^([A-F])\. ([^\n]+)$", msg))
        inverse = {v: k for k, v in options.items()}
        twin = "REFERENCE PROFILE" in str(messages)
        if "parser patch" in msg:
            choice = "Wait for tests" if twin else "Ship now"
        elif "neighbor invitation" in msg:
            choice = "Decline invite" if twin else "Accept invite"
        elif "documentation clarity" in msg:
            choice = "Review docs"  # correct under both arms
        else:
            choice = "Fast shortcut"  # wrong under both arms
        return json.dumps({"choice_letter": inverse[choice]})


class ConfidenceModel(PairedModel):
    def generate(self, messages, **kwargs):
        raw = super().generate(messages, **kwargs)
        payload = json.loads(raw)
        payload["confidence"] = 0.5
        return json.dumps(payload)


class PairedDecisionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = ExperienceStore(Path(tmp.name) / "private")
        self.addCleanup(self.store.close)
        self.store.propose(
            "style", "Prefer precise, thoughtful explanations",
            source="synthetic:owner", approved=True)
        samples = [
            ("When I need to deploy a parser patch before tests finish, "
             "which approach would I choose?",
             ["Ship now", "Wait for tests"], "Wait for tests"),
            ("How do I respond to a neighbor invitation for a quick visit?",
             ["Decline invite", "Accept invite"], "Accept invite"),
            ("When considering documentation clarity for a package, "
             "which process do I prefer?",
             ["Review docs", "Skip review"], "Review docs"),
            ("For an isolated synthetic question about a project board "
             "which option is selected?",
             ["Fast shortcut", "Careful analysis"], "Careful analysis"),
        ]
        self.ids = []
        for i, (scenario, options, gold) in enumerate(samples):
            self.ids.append(self.store.add_decision(
                scenario, gold, f"PRIVATE_GOLD_REASON_{i}_NO_MODEL_ACCESS",
                source="synthetic:owner", approved=True, split="test",
                options=options))

    def evaluate(self, model=None, **kwargs):
        model = model or PairedModel()
        options = {"split": "test", "limit": 4, "seed": 19}
        options.update(kwargs)
        return evaluate_paired_decisions(self.store, model, **options)

    def test_paired_contingency_and_same_model_option_order(self):
        model = PairedModel()
        report = self.evaluate(model)
        self.assertEqual(report["total"], 4)
        self.assertEqual(report["model_requests"], 8)
        self.assertEqual(report["twin_only_correct"], 1)
        self.assertEqual(report["neutral_only_correct"], 1)
        self.assertEqual(report["both_correct"], 1)
        self.assertEqual(report["both_wrong"], 1)
        self.assertEqual(report["twin_correct"], 2)
        self.assertEqual(report["neutral_correct"], 2)
        self.assertEqual(report["twin_accuracy"], 0.5)
        self.assertEqual(report["neutral_accuracy"], 0.5)
        self.assertEqual(report["paired_accuracy_difference"], 0.0)
        self.assertEqual(report["discordant_pairs"], 2)
        self.assertEqual(report["twin_wins_given_discordance"], 0.5)
        self.assertEqual(report["exact_mcnemar_two_sided_p"], 1.0)
        self.assertEqual(len(report["twin_wins_given_discordance_interval_95"]), 2)
        self.assertEqual(report["twin_coverage"], 1.0)
        self.assertEqual(report["neutral_coverage"], 1.0)
        self.assertEqual(report["chance_expected"], 0.5)
        self.assertEqual(report["twin_invalid_predictions"], 0)
        self.assertEqual(report["neutral_invalid_predictions"], 0)
        self.assertEqual(len(model.calls), 8)
        for i in range(0, 8, 2):
            a, b = model.calls[i], model.calls[i + 1]
            self.assertEqual(a[1], b[1])
            self.assertEqual(a[0][-1]["content"], b[0][-1]["content"])
            self.assertEqual(
                sum("REFERENCE PROFILE" in str(call[0]) for call in (a, b)), 1)
        all_sent = str(model.calls)
        self.assertNotIn("PRIVATE_GOLD_REASON", all_sent)
        self.assertNotIn("What I actually chose", all_sent)
        self.assertTrue(report["case_text_in_report"] is False)
        self.assertFalse(report["personality_or_identity_certified"])
        self.assertNotIn("parser patch", json.dumps(report))
        self.assertNotIn("PRIVATE_GOLD_REASON", json.dumps(report))
        self.assertNotIn('"cases"', json.dumps(report))

    def test_reproducible_seed_and_descriptive_intervals(self):
        first = self.evaluate(PairedModel())
        second = self.evaluate(PairedModel())
        self.assertEqual(first, second)
        self.assertEqual(len(first["twin_accuracy_interval_95"]), 2)
        self.assertEqual(len(first["neutral_accuracy_interval_95"]), 2)
        self.assertIn("descriptive", first["limitations"])

    def test_no_owner_profile_in_neutral_messages(self):
        model = PairedModel()
        self.evaluate(model)
        neutral = [call[0] for call in model.calls
                   if "REFERENCE PROFILE" not in str(call[0])]
        self.assertEqual(len(neutral), 4)
        for m in neutral:
            self.assertEqual(len(m), 2)
            self.assertEqual(m[0]["role"], "system")
            self.assertNotIn("thoughtful explanations", str(m))
            self.assertNotIn("approved_identity", str(m))

    def test_midflight_heldout_consent_revocation_drops_report(self):
        def change(n):
            if n == 1:
                self.store.decision_status(self.ids[0], "rejected")
        model = PairedModel(callback=change)
        with self.assertRaisesRegex(ValueError, "evidence changed|Held-out decision changed"):
            self.evaluate(model)
        self.assertEqual(len(model.calls), 1)

    def test_midflight_training_memory_change_drops_report(self):
        rid = self.store.db.execute(
            "SELECT id FROM identity WHERE status='approved' LIMIT 1").fetchone()[0]
        def change(n):
            if n == 1:
                self.store.status(rid, "rejected")
        model = PairedModel(callback=change)
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            self.evaluate(model)
        self.assertEqual(len(model.calls), 1)

    def test_model_identity_guard_interruption_fails_closed(self):
        calls = [0]
        def guard():
            calls[0] += 1
            if calls[0] >= 4:
                raise ValueError("The pinned local model changed")
        with self.assertRaisesRegex(ValueError, "pinned local model"):
            self.evaluate(PairedModel(), model_guard=guard)

    def test_model_exception_sanitized_without_gold_data(self):
        model = PairedModel(response=RuntimeError(
            "PRIVATE_GOLD_REASON_UNTRUSTED_MODEL_EXCEPTION"))
        with self.assertRaisesRegex(ValueError, "Local paired decision inference failed") as caught:
            self.evaluate(model)
        self.assertNotIn("PRIVATE_GOLD_REASON", str(caught.exception))
        self.assertEqual(len(model.calls), 1)

    def test_invalid_choices_are_wrong_not_accepted_as_success(self):
        report = self.evaluate(PairedModel(response='{"choice_letter":"Z"}'))
        self.assertEqual(report["twin_invalid_predictions"], 4)
        self.assertEqual(report["neutral_invalid_predictions"], 4)
        self.assertEqual(report["both_wrong"], 4)
        self.assertEqual(report["twin_correct"], 0)
        self.assertEqual(report["neutral_correct"], 0)

    def test_explicit_abstention_is_separate_from_invalid_predictions(self):
        model = PairedModel(response='{"choice_letter":"ABSTAIN"}')
        result = self.evaluate(model, allow_abstain=True)
        self.assertEqual(result["model_requests"], 8)
        self.assertEqual(result["twin_abstentions"], 4)
        self.assertEqual(result["neutral_abstentions"], 4)
        self.assertEqual(result["twin_invalid_predictions"], 0)
        self.assertEqual(result["neutral_invalid_predictions"], 0)
        self.assertEqual(result["twin_coverage"], 0.0)
        self.assertIsNone(result["twin_answered_accuracy"])
        self.assertIsNone(result["exact_mcnemar_two_sided_p"])
        self.assertTrue(all("ABSTAIN" in call[0][0]["content"]
                            or "ABSTAIN" in call[0][1]["content"]
                            for call in model.calls))
        self.assertNotIn("PRIVATE_GOLD_REASON", str(model.calls))

    def test_abstain_is_not_accepted_without_opt_in(self):
        result = self.evaluate(PairedModel(response='{"choice_letter":"ABSTAIN"}'))
        self.assertEqual(result["twin_abstentions"], 0)
        self.assertEqual(result["neutral_abstentions"], 0)
        self.assertEqual(result["twin_invalid_predictions"], 4)
        self.assertEqual(result["twin_coverage"], 0.0)
        self.assertFalse(result["allow_abstain"])

    def test_opt_in_confidence_reports_aggregate_calibration_only(self):
        model = ConfidenceModel()
        report = self.evaluate(model, score_confidence=True)
        self.assertEqual(report["schema"], 7)
        self.assertTrue(report["score_confidence"])
        self.assertEqual(report["total"], 4)
        self.assertEqual(report["model_requests"], 8)
        self.assertEqual(report["twin_invalid_predictions"], 0)
        self.assertEqual(report["neutral_invalid_predictions"], 0)
        for arm in ("twin", "neutral"):
            scores = report["confidence_calibration"][arm]
            self.assertEqual(scores["samples"], 4)
            self.assertEqual(scores["mean_reported_confidence"], 0.5)
            self.assertEqual(scores["accuracy_on_scored_responses"], 0.5)
            self.assertAlmostEqual(scores["chosen_answer_brier_score"], 0.25)
            self.assertAlmostEqual(scores["expected_calibration_error_10bins"], 0.0)
        self.assertTrue(all("confidence" in str(c[0]) for c in model.calls))
        self.assertNotIn("PRIVATE_GOLD_REASON", str(model.calls))
        self.assertNotIn("parser patch", json.dumps(report))
        self.assertNotIn("confidence", str(self.store.db.execute(
            "SELECT rationale FROM decisions LIMIT 1").fetchone()[0]))

    def test_confidence_mode_rejects_missing_or_untrusted_probabilities(self):
        invalid = [
            '{"choice_letter":"A"}',
            '{"choice_letter":"A","confidence":"0.9"}',
            '{"choice_letter":"A","confidence":true}',
            '{"choice_letter":"A","confidence":NaN}',
            '{"choice_letter":"A","confidence":Infinity}',
            '{"choice_letter":"A","confidence":-0.01}',
            '{"choice_letter":"A","confidence":1.01}',
            '{"choice_letter":"A","confidence":0.5,"rationale":"private"}',
            '{"choice_letter":"ABSTAIN","confidence":0.3}',
        ]
        for response in invalid:
            with self.subTest(response=response):
                report = self.evaluate(PairedModel(response=response),
                                       score_confidence=True)
                self.assertEqual(report["twin_invalid_predictions"], 4)
                self.assertEqual(report["neutral_invalid_predictions"], 4)
                self.assertEqual(report["twin_correct"], 0)
                self.assertEqual(report["twin_coverage"], 0.0)
                self.assertEqual(report["confidence_calibration"]["twin"]["samples"], 0)
                self.assertIsNone(report["confidence_calibration"]["twin"][
                    "expected_calibration_error_10bins"])

    def test_default_ignores_confidence_field_in_optional_model_output(self):
        report = self.evaluate(ConfidenceModel())
        self.assertFalse(report["score_confidence"])
        self.assertEqual(report["twin_correct"], 2)
        self.assertEqual(report["neutral_correct"], 2)
        self.assertEqual(report["confidence_calibration"]["twin"]["samples"], 0)

    def test_stability_repeats_compare_semantic_options_not_letters(self):
        base = self.evaluate(PairedModel())
        model = PairedModel()
        report = self.evaluate(model, stability_trials=2)
        self.assertEqual(report["schema"], 7)
        self.assertEqual(report["total"], 4)
        self.assertEqual(report["model_requests"], 16)
        self.assertEqual(len(model.calls), 16)
        self.assertEqual({call[1]["seed"] for call in model.calls},
                         {19, 19 + 1_000_003})
        for field in ("twin_correct", "neutral_correct",
                      "paired_accuracy_difference", "discordant_pairs",
                      "exact_mcnemar_two_sided_p", "heldout_sha256"):
            self.assertEqual(report[field], base[field])
        stability = report["stability"]
        self.assertTrue(stability["enabled"])
        self.assertEqual(stability["trials_per_case"], 2)
        self.assertFalse(stability["repeated_trials_count_as_independent_cases"])
        for arm in ("twin", "neutral"):
            self.assertEqual(stability[arm]["cases"], 4)
            self.assertEqual(stability[arm]["valid_pair_comparisons"], 4)
            self.assertEqual(stability[arm]["agreeing_pairs"], 4)
            self.assertEqual(stability[arm]["unanimous_rate_on_fully_answered_cases"], 1.0)
        self.assertNotIn("PRIVATE_GOLD_REASON", str(model.calls))
        self.assertNotIn("parser patch", json.dumps(report))
        self.assertNotIn('"cases": [', json.dumps(report))

    def test_stability_detects_seed_sensitive_semantic_choice_changes(self):
        class SeedSensitiveModel(PairedModel):
            def generate(self, messages, **kwargs):
                self.calls.append((messages, kwargs))
                choices = list(dict(re.findall(
                    r"(?m)^([A-F])\. ([^\n]+)$", messages[-1]["content"])).items())
                # Never use the shuffled LETTER as a stable target.
                target = sorted(value for _, value in choices)[kwargs["seed"] % 2]
                return json.dumps({"choice_letter": dict(
                    (value, letter) for letter, value in choices)[target]})

        report = self.evaluate(SeedSensitiveModel(), stability_trials=2)
        for arm in ("twin", "neutral"):
            self.assertEqual(report["stability"][arm]["valid_pair_comparisons"], 4)
            self.assertEqual(report["stability"][arm]["agreeing_pairs"], 0)
            self.assertEqual(report["stability"][arm]["unanimous_rate_on_fully_answered_cases"], 0.0)

    def test_invalid_and_abstention_trials_are_not_stable_choices(self):
        for response, abstain in (('{"choice_letter":"Z"}', False),
                                  ('{"choice_letter":"ABSTAIN"}', True)):
            with self.subTest(response=response):
                result = self.evaluate(
                    PairedModel(response=response), stability_trials=2,
                    allow_abstain=abstain)
                for arm in ("twin", "neutral"):
                    data = result["stability"][arm]
                    self.assertEqual(data["cases_with_all_valid_choices"], 0)
                    self.assertEqual(data["valid_pair_comparisons"], 0)
                    self.assertIsNone(data["pairwise_semantic_agreement"])
                    self.assertIsNone(data["unanimous_rate_on_fully_answered_cases"])
                    self.assertEqual(data["abstention_trials"], 8 if abstain else 0)
                    self.assertEqual(data["invalid_trials"], 0 if abstain else 8)

    def test_valid_option_named_abstain_is_not_a_refusal(self):
        # This is a real choice option, not the model's opt-in ABSTAIN token.
        with self.store.db:
            self.store.db.execute(
                "UPDATE decisions SET choice=?, options_json=? WHERE id=?",
                ("ABSTAIN", json.dumps(["ABSTAIN", "Wait for tests"]),
                 self.ids[0]))

        class ChooseNamedOption(PairedModel):
            def generate(self, messages, **kwargs):
                self.calls.append((messages, kwargs))
                options = dict(re.findall(
                    r"(?m)^([A-F])\. ([^\n]+)$", messages[-1]["content"]))
                selected = next(letter for letter, option in options.items()
                                if option == "ABSTAIN")
                return json.dumps({"choice_letter": selected})

        model = ChooseNamedOption()
        result = self.evaluate(model, limit=1, stability_trials=2,
                               allow_abstain=True)
        self.assertEqual(result["twin_abstentions"], 0)
        self.assertEqual(result["neutral_abstentions"], 0)
        for arm in ("twin", "neutral"):
            self.assertEqual(result["stability"][arm]["valid_trials"], 2)
            self.assertEqual(result["stability"][arm]["abstention_trials"], 0)
            self.assertEqual(result["stability"][arm]["agreeing_pairs"], 1)
            self.assertEqual(result["stability"][arm]["unanimous_cases"], 1)

    def test_repeat_guard_invalidates_everything_on_consent_revocation(self):
        def revoke(call):
            if call == 3:
                self.store.decision_status(self.ids[0], "rejected")
        model = PairedModel(callback=revoke)
        with self.assertRaisesRegex(ValueError, "evidence changed|Held-out decision changed"):
            self.evaluate(model, stability_trials=2)
        self.assertEqual(len(model.calls), 3)

    def test_repeat_settings_fail_closed_before_any_inference(self):
        model = PairedModel()
        for kw in ({"stability_trials": 0}, {"stability_trials": 4},
                   {"stability_trials": True}, {"stability_trials": "2"},
                   {"stability_trials": 2, "limit": 151},
                   {"stability_trials": 3, "limit": 101}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.evaluate(model, **kw)
        self.assertEqual(model.calls, [])

    def test_preflight_rejects_late_case_leak_before_any_model_call(self):
        row = self.store.db.execute(
            "SELECT scenario FROM decisions WHERE id=?", (self.ids[-1],)).fetchone()
        self.store.propose(
            "identity", row["scenario"],
            source="synthetic:leak-fixture", approved=True)
        model = PairedModel()
        with self.assertRaisesRegex(ValueError, "contaminated|overlap"):
            self.evaluate(model)
        self.assertEqual(model.calls, [])

    def test_same_scenario_across_training_and_test_fails_without_inference(self):
        scenario = self.store.db.execute(
            "SELECT scenario FROM decisions WHERE id=?", (self.ids[0],)).fetchone()[0]
        # Simulate pre-existing/tampered split data directly; the normal
        # add_decision API already blocks this accidental duplication.
        from athenz.store import utc_now
        with self.store.db:
            self.store.db.execute(
                """INSERT INTO decisions
                (scenario,choice,rationale,exception,source,source_ref,status,
                 created_at,options_json,split)
                 VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (scenario, "Ship now", "synthetic training rationale", "",
                 "synthetic", "", "approved", utc_now(),
                 json.dumps(["Ship now", "Wait for tests"]), "train"))
        model = PairedModel()
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.evaluate(model)
        self.assertEqual(len(model.calls), 0)

    def test_repeated_heldout_scenarios_refused_before_inference(self):
        scenario = self.store.db.execute(
            "SELECT scenario FROM decisions WHERE id=?", (self.ids[0],)).fetchone()[0]
        self.store.add_decision(
            "  " + scenario.upper() + "!", "Ship now",
            "synthetic duplicated heldout rationale", source="synthetic",
            split="test", approved=True,
            options=["Ship now", "Wait for tests"])
        model = PairedModel()
        with self.assertRaisesRegex(ValueError, "Repeated held-out"):
            self.evaluate(model, limit=5)
        self.assertEqual(model.calls, [])

    def test_no_approved_heldout_cases_cannot_claim_personalization(self):
        self.store.db.execute(
            "UPDATE decisions SET status='rejected' WHERE split='test'")
        self.store.db.commit()
        result = self.evaluate(PairedModel())
        self.assertEqual(result["total"], 0)
        self.assertIsNone(result["twin_accuracy"])
        self.assertIsNone(result["paired_accuracy_difference"])

    def test_invalid_scope_refused_before_model_call(self):
        model = PairedModel()
        for options in ({"split":"train"}, {"split":""}, {"limit":0},
                        {"limit":1001}, {"seed":-1}, {"seed":True},
                        {"allow_abstain": 1}, {"score_confidence": 1},
                        {"allow_abstain": True, "score_confidence": True},
                        {"require_category_diversity": True},
                        {"require_category_diversity": 1}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    self.evaluate(model, **options)
        self.assertEqual(model.calls, [])

    def test_cli_refuses_inference_without_explicit_owner_confirmation(self):
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit) as stopped:
                main(["--home", str(self.store.home), "--split", "test"])
        self.assertEqual(stopped.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
