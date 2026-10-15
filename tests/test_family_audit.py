"""Synthetic-only tests for manual semantic family split auditing."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.experience import ExperienceStore
from athenz.family_audit import (
    FamilyAudit, CategoryScores, create_family_template,
)
from athenz.paired_decisions import evaluate_paired_decisions, main


class AlwaysFirstModel:
    model = "synthetic-local-no-inference"

    def __init__(self, callback=None):
        self.calls = []
        self.callback = callback

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.callback:
            self.callback(len(self.calls))
        return '{"choice_letter":"A"}'


class FamilyAuditTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = ExperienceStore(Path(tmp.name) / "private")
        self.addCleanup(self.store.close)
        self.store.propose("style", "Give concise replies", source="synthetic", approved=True)
        self.train = self.store.add_decision(
            "When a release window is approaching, should I review the change log?",
            "Review", "Prefer review", source="synthetic:train", approved=True,
            split="train", options=["Review", "Skip"])
        self.heldout = []
        scenarios = (
            "When decorating a fictional greenhouse, should the panels be translucent?",
            "For a hiking route in a made-up canyon, how should landmarks be marked?",
            "Which optical filter should a model telescope use for a dim nebula?",
            "How should an imaginary orchestra schedule rehearsals for brass sections?",
            "During a simulated ocean cleanup, how should floating debris be categorized?",
        )
        for scenario in scenarios:
            self.heldout.append(self.store.add_decision(
                scenario, "Option one", "Synthetic only", source="synthetic:owner",
                approved=True, split="test", options=["Option one", "Option two"]))

    def manifest(self, *, category="work"):
        create_family_template(self.store)
        path = self.store.home / "decision-family-audit.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload["cases"]:
            item["family"] = f"case_{item['id']:03d}"
            item["category"] = category
        self.write(path, payload)
        return path, payload

    def write(self, path, payload):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        path.chmod(0o600)

    def evaluate(self, model=None, **kwargs):
        audit = kwargs.pop("family_audit", FamilyAudit(self.store))
        return evaluate_paired_decisions(
            self.store, model or AlwaysFirstModel(),
            split="test", limit=5, seed=19, family_audit=audit, **kwargs)

    def test_template_is_private_and_never_overwritten(self):
        path, payload = self.manifest()
        self.assertTrue(path.exists())
        self.assertEqual(len(payload["cases"]), 6)
        self.assertIn("scenario", payload["cases"][0])
        self.assertEqual(payload["schema"], 2)
        self.assertEqual(len(payload["approved_source_sha256"]), 64)
        with self.assertRaisesRegex(ValueError, "exists"):
            create_family_template(self.store)
        if __import__("os").name != "nt":
            self.assertEqual(path.stat().st_mode & 0o077, 0)

    def test_groups_report_only_when_at_least_five_cases(self):
        self.manifest()
        model = AlwaysFirstModel()
        report = self.evaluate(model)
        audit = report["family_audit"]
        self.assertTrue(audit["enabled"])
        self.assertEqual(audit["approved_records_audited"], 6)
        self.assertEqual(audit["selected_cases"], 5)
        self.assertEqual(audit["small_categories_suppressed"], 0)
        self.assertEqual(audit["category_metrics"]["work"]["cases"], 5)
        self.assertEqual(audit["category_metrics"]["work"]["twin_correct"],
                         report["twin_correct"])
        self.assertEqual(len(model.calls), 10)
        self.assertNotIn("case_001", json.dumps(report))
        self.assertNotIn("fictional greenhouse", json.dumps(report))
        self.assertNotIn("case_001", str(model.calls))
        self.assertFalse(audit["semantic_independence_certified"])

    def test_small_group_suppressed_without_name_or_scores(self):
        path, payload = self.manifest()
        for item in payload["cases"][-1:]:
            item["category"] = "creative"
        self.write(path, payload)
        report = self.evaluate()
        audit = report["family_audit"]
        self.assertEqual(audit["category_metrics"], {})
        self.assertEqual(audit["small_categories_suppressed"], 2)
        self.assertNotIn("creative", json.dumps(audit))
        self.assertNotIn("work", json.dumps(audit))

    def test_cross_split_paraphrase_family_refused_before_inference(self):
        path, payload = self.manifest()
        payload["cases"][1]["family"] = payload["cases"][0]["family"]
        self.write(path, payload)
        model = AlwaysFirstModel()
        with self.assertRaisesRegex(ValueError, "cross-split"):
            self.evaluate(model, family_audit=FamilyAudit(self.store))
        self.assertEqual(model.calls, [])

    def test_repeated_heldout_family_refused_before_inference(self):
        path, payload = self.manifest()
        payload["cases"][2]["family"] = payload["cases"][1]["family"]
        self.write(path, payload)
        with self.assertRaisesRegex(ValueError, "repeated held-out"):
            FamilyAudit(self.store)

    def test_missing_stale_unknown_or_duplicate_case_fails(self):
        path, original = self.manifest()
        variants = []
        stale_source = json.loads(json.dumps(original))
        stale_source["approved_source_sha256"] = "0" * 64
        variants.append(stale_source)
        less = json.loads(json.dumps(original))
        less["cases"].pop()
        variants.append(less)
        wrong = json.loads(json.dumps(original))
        wrong["cases"][0]["scenario_sha256"] = "0" * 64
        variants.append(wrong)
        unknown = json.loads(json.dumps(original))
        unknown["cases"][0]["id"] = 999999
        variants.append(unknown)
        duplicate = json.loads(json.dumps(original))
        duplicate["cases"][1]["id"] = duplicate["cases"][0]["id"]
        variants.append(duplicate)
        malformed = json.loads(json.dumps(original))
        malformed["cases"][0]["category"] = ["untrusted"]
        variants.append(malformed)
        empty = json.loads(json.dumps(original))
        empty["cases"][0]["family"] = ""
        variants.append(empty)
        for item in variants:
            with self.subTest(variant=item["cases"][0]):
                self.write(path, item)
                with self.assertRaises(ValueError):
                    FamilyAudit(self.store)
        self.write(path, original)

    def test_revocation_during_model_call_invalidates_report(self):
        self.manifest()

        def on_call(n):
            if n == 1:
                self.store.decision_status(self.train, "rejected")

        model = AlwaysFirstModel(on_call)
        with self.assertRaisesRegex(ValueError, "sources|evidence"):
            self.evaluate(model)
        self.assertEqual(len(model.calls), 1)

    def test_manifest_change_during_model_call_invalidates_report(self):
        path, payload = self.manifest()

        def on_call(n):
            if n == 1:
                payload["cases"][0]["category"] = "planning"
                self.write(path, payload)

        model = AlwaysFirstModel(on_call)
        with self.assertRaisesRegex(ValueError, "sources or owner labels"):
            self.evaluate(model)
        self.assertEqual(len(model.calls), 1)

    def test_symlink_or_world_readable_manifest_refused(self):
        path, payload = self.manifest()
        if __import__("os").name != "nt":
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "owner-only"):
                FamilyAudit(self.store)
            path.chmod(0o600)
        path.unlink()
        if hasattr(Path, "symlink_to"):
            try:
                path.symlink_to(self.store.path)
            except (OSError, NotImplementedError):
                return
            with self.assertRaisesRegex(ValueError, "regular private"):
                FamilyAudit(self.store)

    def test_cli_template_creates_no_model_session(self):
        self.store.db.execute("DELETE FROM decisions")
        self.store.db.commit()
        self.store.add_decision(
            "Would I archive a synthetic file?", "Archive", "Archive preference",
            approved=True, source="synthetic:owner", split="test",
            options=["Archive", "Delete"])
        with patch("athenz.paired_decisions.OllamaClient") as model:
            main(["--home", str(self.store.home), "--family-template", "--confirm"])
            model.assert_not_called()
        self.assertTrue((self.store.home / "decision-family-audit.json").exists())

    def test_source_choice_or_rationale_edit_invalidates_prior_review(self):
        self.manifest()
        with self.store.db:
            self.store.db.execute(
                "UPDATE decisions SET rationale=? WHERE id=?",
                ("Changed interpretation after manual review", self.heldout[0]))
        with self.assertRaisesRegex(ValueError, "incomplete or stale"):
            FamilyAudit(self.store)

    def test_family_check_cli_is_offline_and_rejects_stale_reviews(self):
        self.manifest()
        with patch("athenz.paired_decisions.OllamaClient") as model:
            with patch("builtins.print") as printer:
                main(["--home", str(self.store.home), "--family-check", "--confirm"])
            model.assert_not_called()
        reported = json.loads(printer.call_args[0][0])
        self.assertEqual(reported["status"], "valid")
        self.assertEqual(reported["approved_records_audited"], 6)
        self.assertFalse(reported["source_text_in_report"])
        self.assertNotIn("greenhouse", json.dumps(reported))
        with self.store.db:
            self.store.db.execute("UPDATE decisions SET choice=? WHERE id=?",
                                  ("Option two", self.heldout[0]))
        with patch("athenz.paired_decisions.OllamaClient") as model:
            with self.assertRaisesRegex(SystemExit, "incomplete or stale"):
                main(["--home", str(self.store.home), "--family-check", "--confirm"])
            model.assert_not_called()

    def test_family_cli_actions_mutually_exclusive(self):
        model = AlwaysFirstModel()
        self.manifest()
        with patch("athenz.paired_decisions.OllamaClient") as client:
            with self.assertRaisesRegex(SystemExit, "one family action"):
                main(["--home", str(self.store.home), "--family-check",
                      "--family-audit", "--confirm"])
            client.assert_not_called()
        self.assertEqual(model.calls, [])

    def test_aggregate_rejects_untrusted_categories(self):
        acc = CategoryScores()
        with self.assertRaises(ValueError):
            acc.add("private-sensitive-label", twin_correct=True,
                    neutral_correct=True)
        with self.assertRaises(ValueError):
            acc.add("work", twin_correct=1, neutral_correct=False)
        self.assertEqual(acc.report(0)["category_metrics"], {})


if __name__ == "__main__":
    unittest.main()
