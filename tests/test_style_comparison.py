"""Synthetic privacy, blinding and provenance regressions for local Twin style pilot."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.experience import ExperienceStore
from athenz.style_comparison import (
    ComparisonArchive, create_comparison, main, _FILENAME,
)
from athenz.style_readiness import style_readiness


class ModelDouble:
    def __init__(self, callback=None, fail_at=None, raw=None):
        self.calls = []
        self.callback = callback
        self.fail_at = fail_at
        self.raw = raw

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.callback:
            self.callback(len(self.calls))
        if self.fail_at == len(self.calls):
            raise RuntimeError("PRIVATE_OWNER_TEXT_MUST_NOT_APPEAR")
        if self.raw is not None:
            return self.raw
        return ("TWIN_SYNTHETIC_ANSWER" if "REFERENCE PROFILE" in str(messages)
                else "NEUTRAL_SYNTHETIC_ANSWER")


class BlindedStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ExperienceStore(Path(self.temp.name) / "private")
        self.addCleanup(self.store.close)
        self.models = []
        for i in range(3):
            train = self.store.add_sample(
                f"Synthetic training writing evidence paragraph number {i}",
                source="synthetic:owner", split="train")
            test = self.store.add_sample(
                f"Synthetic independently withheld evaluation prose number {i} "
                "with a private distinct flourish",
                source="synthetic:owner", split="test")
            self.store.set_review("writing_samples", train, "approved")
            self.store.set_review("writing_samples", test, "approved")
        self.assertTrue(style_readiness(self.store)["pilot_evaluation_sufficient"])
        self.task = "Write a friendly note about caring for a neighbor's garden."

    def archive(self):
        a = ComparisonArchive(self.store)
        self.addCleanup(a.close)
        return a

    def run_case(self, *, model=None, chooser=0, task=None, digest_fn=None):
        model = model or ModelDouble()
        self.models.append(model)
        result = create_comparison(
            self.store, task or self.task, confirmed=True,
            client_factory=lambda tag: model,
            digest_fn=digest_fn or (lambda tag: "a" * 64),
            route_fn=lambda store: "synthetic-local-model",
            chooser=lambda n: chooser)
        return result, model

    def test_blinding_and_model_context_isolation(self):
        case, model = self.run_case(chooser=0)
        self.assertEqual(len(model.calls), 2)
        neutral, twin = model.calls
        self.assertEqual(neutral[0][0]["role"], "system")
        self.assertNotIn("REFERENCE PROFILE", str(neutral))
        self.assertIn("REFERENCE PROFILE", str(twin))
        self.assertIn("Synthetic training writing evidence", str(twin))
        self.assertNotIn("independently withheld evaluation prose", str(model.calls))
        self.assertEqual(neutral[1], twin[1])
        visible = self.archive().show(case)
        self.assertIn("TWIN_SYNTHETIC_ANSWER", visible["A"])
        self.assertIn("NEUTRAL_SYNTHETIC_ANSWER", visible["B"])
        self.assertFalse(visible["rated"])
        self.assertNotIn("twin_option", visible)
        self.assertNotIn("neutral", visible.keys())
        self.assertFalse(self.archive().report(self.store)["model_accuracy_or_identity_certified"])

    def test_randomized_display_and_private_owner_scoring(self):
        case, _ = self.run_case(chooser=1)
        self.assertIn("NEUTRAL_SYNTHETIC_ANSWER", self.archive().show(case)["A"])
        self.assertIn("TWIN_SYNTHETIC_ANSWER", self.archive().show(case)["B"])
        with self.assertRaisesRegex(ValueError, "confirmed"):
            self.archive().rate(self.store, case, "B")
        self.archive().rate(self.store, case, "B", confirmed=True)
        report = self.archive().report(self.store)
        self.assertEqual(report["twin_preferred"], 1)
        self.assertEqual(report["neutral_preferred"], 0)
        self.assertEqual(report["ties"], 0)
        self.assertEqual(report["valid_owner_ratings"], 1)
        self.assertIsNotNone(report["wilson_interval_95"])
        self.assertNotIn(self.task, json.dumps(report))
        self.assertFalse(report["minimum_pilot_non_ties_reached"])
        with self.assertRaisesRegex(ValueError, "already rated"):
            self.archive().rate(self.store, case, "A", confirmed=True)

    def test_neutral_preference_and_tie_are_reported_without_revealing_case_label(self):
        first, _ = self.run_case(chooser=0)
        second, _ = self.run_case(
            chooser=1, task="Write a short postcard about a rainy afternoon.")
        archive = self.archive()
        archive.rate(self.store, first, "B", confirmed=True)
        archive.rate(self.store, second, "tie", confirmed=True)
        report = archive.report(self.store)
        self.assertEqual((report["twin_preferred"], report["neutral_preferred"],
                          report["ties"]), (0, 1, 1))
        self.assertEqual(report["twin_preference_non_tie_rate"], 0.0)

    def test_no_consent_no_model_and_no_archive(self):
        model = ModelDouble()
        with self.assertRaisesRegex(ValueError, "confirmation"):
            create_comparison(self.store, self.task,
                client_factory=lambda tag: model)
        self.assertEqual(model.calls, [])
        self.assertFalse((self.store.home / _FILENAME).exists())

    def test_empty_research_profile_is_not_certified_or_started(self):
        self.store.db.execute(
            "UPDATE writing_samples SET status='rejected' WHERE split='test'")
        self.store.db.commit()
        model = ModelDouble()
        with self.assertRaisesRegex(ValueError, "Review at least"):
            create_comparison(self.store, self.task, confirmed=True,
                client_factory=lambda tag: model)
        self.assertEqual(model.calls, [])

    def test_normalized_duplicate_task_is_refused(self):
        self.run_case()
        with self.assertRaisesRegex(ValueError, "already been compared"):
            self.run_case(task="WRITE a friendly note about caring for a neighbor's garden!")

    def test_heldout_copy_is_refused_before_any_model_call(self):
        example = self.store.db.execute(
            "SELECT text FROM writing_samples WHERE split='test' "
            "ORDER BY id LIMIT 1").fetchone()[0]
        model = ModelDouble()
        with self.assertRaisesRegex(ValueError, "copies protected"):
            create_comparison(
                self.store, "Please copy exactly: " + example, confirmed=True,
                client_factory=lambda tag: model, route_fn=lambda s: "local")
        self.assertEqual(model.calls, [])

    def test_training_revocation_during_model_generation_discards_pair(self):
        row = self.store.db.execute(
            "SELECT id FROM writing_samples WHERE split='train' LIMIT 1").fetchone()
        def change(n):
            if n == 1:
                self.store.set_review("writing_samples", row[0], "rejected")
        model = ModelDouble(callback=change)
        with self.assertRaisesRegex(ValueError, "Source or local model changed"):
            self.run_case(model=model)
        self.assertEqual(len(model.calls), 1)
        self.assertFalse((self.store.home / _FILENAME).exists())

    def test_heldout_change_during_second_generation_discards_pair(self):
        row = self.store.db.execute(
            "SELECT id FROM writing_samples WHERE split='test' LIMIT 1").fetchone()
        def change(n):
            if n == 2:
                self.store.set_review("writing_samples", row[0], "rejected")
        model = ModelDouble(callback=change)
        with self.assertRaisesRegex(ValueError, "Source or local model changed"):
            self.run_case(model=model)
        self.assertEqual(len(model.calls), 2)
        self.assertFalse((self.store.home / _FILENAME).exists())

    def test_local_model_digest_drift_rejects_unpersisted_generation(self):
        digests = iter(["a" * 64, "b" * 64])
        with self.assertRaisesRegex(ValueError, "Source or local model changed"):
            self.run_case(digest_fn=lambda tag: next(digests))
        self.assertFalse((self.store.home / _FILENAME).exists())

    def test_generation_failure_and_oversized_result_leave_no_archive(self):
        for model in (ModelDouble(fail_at=2), ModelDouble(raw="x" * 12001)):
            with self.subTest(kind=str(model.fail_at)):
                try:
                    self.run_case(model=model)
                except (ValueError, RuntimeError):
                    pass
                else:
                    self.fail("Invalid generation accepted")
                self.assertFalse((self.store.home / _FILENAME).exists())

    def test_stale_source_does_not_count_as_current_result(self):
        case, _ = self.run_case()
        archive = self.archive()
        archive.rate(self.store, case, "A", confirmed=True)
        self.assertEqual(archive.report(self.store)["valid_owner_ratings"], 1)
        train_id = self.store.db.execute(
            "SELECT id FROM writing_samples WHERE split='train' LIMIT 1").fetchone()[0]
        self.store.set_review("writing_samples", train_id, "rejected")
        report = archive.report(self.store)
        self.assertEqual(report["stale_cases"], 1)
        self.assertEqual(report["valid_owner_ratings"], 0)

    def test_stale_source_prevents_rating(self):
        case, _ = self.run_case()
        sample = self.store.add_sample(
            "Synthetic extra protected test reference never used by model",
            source="synthetic", split="test")
        self.store.set_review("writing_samples", sample, "approved")
        with self.assertRaisesRegex(ValueError, "Evidence changed"):
            self.archive().rate(self.store, case, "A", confirmed=True)

    def test_private_file_mode_symlink_and_hardlink_fences(self):
        case, _ = self.run_case()
        path = self.store.home / _FILENAME
        self.assertTrue(path.is_file())
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o077, 0)
        if os.name == "nt":
            return  # Windows symlink privileges vary by host policy.
        link = self.store.home / "hardlink.sqlite3"
        os.link(path, link)
        self.addCleanup(lambda: link.unlink(missing_ok=True))
        with self.assertRaisesRegex(ValueError, "owner-only"):
            ComparisonArchive(self.store)
        link.unlink()
        path.unlink()
        path.symlink_to(self.store.path)
        with self.assertRaisesRegex(ValueError, "not regular"):
            ComparisonArchive(self.store)

    def test_delete_requires_confirmation_and_erases_private_pair(self):
        case, _ = self.run_case()
        with self.assertRaisesRegex(ValueError, "confirmation"):
            self.archive().remove(case)
        self.archive().remove(case, confirmed=True)
        self.assertEqual(self.archive().report(self.store)["total_cases"], 0)

    def test_archive_reads_never_create_new_database(self):
        with self.assertRaisesRegex(ValueError, "No private"):
            ComparisonArchive(self.store)
        self.assertFalse((self.store.home / _FILENAME).exists())

    def test_cli_status_is_aggregate_and_does_not_infer_fidelity(self):
        self.run_case()
        with patch("builtins.print") as output:
            main(["--home", str(self.store.home), "report"])
        summary = json.loads(output.call_args.args[0])
        self.assertTrue(summary["owner_text_in_report"] is False)
        self.assertFalse(summary["model_accuracy_or_identity_certified"])
        self.assertEqual(summary["unrated_current_cases"], 1)


if __name__ == "__main__":
    unittest.main()
