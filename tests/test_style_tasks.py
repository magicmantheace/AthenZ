"""Synthetic, owner-only reviewed writing-task bank acceptance tests."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.experience import ExperienceStore
from athenz.style_comparison import ComparisonArchive, create_comparison, main
from athenz.style_tasks import StyleTaskBank, start_next


class LocalModelDouble:
    def __init__(self, callback=None):
        self.calls = []
        self.callback = callback

    def generate(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        if self.callback:
            self.callback(len(self.calls))
        return ("PERSONALIZED_SYNTHETIC" if "REFERENCE PROFILE" in str(messages)
                else "NEUTRAL_SYNTHETIC")


class IndependentWritingTaskTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = ExperienceStore(Path(temp.name) / "private")
        self.addCleanup(self.store.close)
        for i in range(3):
            tr = self.store.add_sample(
                f"Reviewed owner training paragraph about spruce trees {i}.",
                source="synthetic:owner", split="train")
            te = self.store.add_sample(
                f"Withheld private evaluation writing about sea otters {i} "
                "and southern coastline weather.",
                source="synthetic:owner", split="test")
            self.store.set_review("writing_samples", tr, "approved")
            self.store.set_review("writing_samples", te, "approved")
        self.task = "Write a brief thank-you note to a helpful neighbor."
        self.bank = StyleTaskBank(self.store, create=True)
        self.addCleanup(self.bank.close)

    def add(self, task=None, approved=True):
        idx = self.bank.add(task or self.task, confirmed=True)
        if approved:
            self.bank.review(self.store, idx, "approved", confirmed=True)
        return idx

    def run_next(self, model=None, **kwargs):
        model = model or LocalModelDouble()
        case = start_next(
            self.store, confirmed=True,
            client_factory=lambda tag: model,
            route_fn=lambda store: "synthetic-installed-local",
            digest_fn=lambda tag: "a" * 64,
            chooser=lambda n: 0, **kwargs)
        return case, model

    def test_pending_task_not_used_until_owner_review(self):
        self.add(approved=False)
        with self.assertRaisesRegex(ValueError, "No current reviewed"):
            self.run_next()
        status = self.bank.summary(self.store)
        self.assertEqual(status["pending"], 1)
        self.assertEqual(status["approved_ready_unused"], 0)

    def test_independent_review_generates_single_blinded_pair(self):
        task_id = self.add()
        self.assertEqual(self.bank.next_approved(self.store)["id"], task_id)
        case, model = self.run_next()
        self.assertEqual(len(model.calls), 2)
        self.assertNotIn("sea otters", str(model.calls).lower())
        self.assertIn("Reviewed owner training", str(model.calls[1]))
        shown = self.bank.archive.show(case)
        self.assertEqual(shown["task"], self.task)
        self.assertEqual(shown["A"], "PERSONALIZED_SYNTHETIC")
        self.assertEqual(shown["B"], "NEUTRAL_SYNTHETIC")
        self.assertNotIn("twin_option", shown)
        self.assertEqual(self.bank.summary(self.store)["consumed"], 1)
        with self.assertRaisesRegex(ValueError, "No current reviewed"):
            self.run_next()

    def test_rating_counts_separate_reviewed_from_ad_hoc_examples(self):
        self.add()
        bank_case, _ = self.run_next()
        self.bank.archive.rate(self.store, bank_case, "A", confirmed=True)
        ad_hoc = create_comparison(
            self.store, "Write a warm note about feeding a lost kitten.",
            confirmed=True, client_factory=lambda tag: LocalModelDouble(),
            route_fn=lambda store: "synthetic-installed-local",
            digest_fn=lambda tag: "a" * 64, chooser=lambda n: 1)
        self.bank.archive.rate(self.store, ad_hoc, "B", confirmed=True)
        r = self.bank.archive.report(self.store)
        self.assertEqual(r["valid_owner_ratings"], 2)
        self.assertEqual(r["reviewed_task_bank_ratings"], 1)
        self.assertEqual(r["ad_hoc_exploratory_ratings"], 1)
        self.assertFalse(r["model_accuracy_or_identity_certified"])

    def test_approved_task_unused_after_review_evidence_revoked(self):
        task = self.add()
        train_id = self.store.db.execute(
            "SELECT id FROM writing_samples WHERE split='train' "
            "ORDER BY id LIMIT 1").fetchone()[0]
        self.store.set_review("writing_samples", train_id, "rejected")
        status = self.bank.summary(self.store)
        self.assertEqual(status["approved_stale_unused"], 1)
        with self.assertRaisesRegex(ValueError, "No current reviewed"):
            self.run_next()
        replacement = self.store.add_sample(
            "Another approved owner style example with a new provenance.",
            source="synthetic", split="train")
        self.store.set_review("writing_samples", replacement, "approved")
        self.bank.review(self.store, task, "approved", confirmed=True)
        self.assertEqual(self.bank.summary(self.store)["approved_ready_unused"], 1)

    def test_task_rejected_during_neutral_generation_drops_both_outputs(self):
        task = self.add()
        model = LocalModelDouble(callback=lambda n:
            self.bank.review(self.store, task, "rejected", confirmed=True)
            if n == 1 else None)
        with self.assertRaisesRegex(ValueError, "Approved writing task"):
            self.run_next(model=model)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(self.bank.archive.report(self.store)["total_cases"], 0)

    def test_task_rejected_during_twin_generation_drops_pair(self):
        task = self.add()
        model = LocalModelDouble(callback=lambda n:
            self.bank.review(self.store, task, "rejected", confirmed=True)
            if n == 2 else None)
        with self.assertRaisesRegex(ValueError, "Approved writing task"):
            self.run_next(model=model)
        self.assertEqual(len(model.calls), 2)
        self.assertEqual(self.bank.archive.report(self.store)["total_cases"], 0)

    def test_heldout_excerpt_cannot_be_reviewed_as_a_task(self):
        text = self.store.db.execute(
            "SELECT text FROM writing_samples WHERE split='test' LIMIT 1"
        ).fetchone()[0]
        task_id = self.bank.add("Please repeat this exact writing: " + text,
                                confirmed=True)
        with self.assertRaisesRegex(ValueError, "copies protected"):
            self.bank.review(self.store, task_id, "approved", confirmed=True)
        self.assertEqual(self.bank.summary(self.store)["pending"], 1)

    def test_consent_required_before_task_storage_and_review(self):
        with self.assertRaisesRegex(ValueError, "confirmation"):
            self.bank.add(self.task)
        self.assertEqual(self.bank.summary(self.store)["pending"], 0)
        task = self.bank.add(self.task, confirmed=True)
        with self.assertRaisesRegex(ValueError, "confirmed"):
            self.bank.review(self.store, task, "approved")
        with self.assertRaisesRegex(ValueError, "Owner confirmation"):
            self.bank.delete(task)
        with self.assertRaisesRegex(ValueError, "Owner confirmation"):
            start_next(self.store)
        self.assertEqual(self.bank.summary(self.store)["pending"], 1)

    def test_duplicate_normalized_task_rejected_even_before_review(self):
        self.add(approved=False)
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.bank.add("WRITE A brief thank-you note to a helpful neighbor!",
                          confirmed=True)
        self.assertEqual(self.bank.summary(self.store)["pending"], 1)

    def test_ad_hoc_task_used_before_owner_review_cannot_be_reused_as_new(self):
        self.add()
        create_comparison(
            self.store, self.task, confirmed=True,
            client_factory=lambda tag: LocalModelDouble(),
            route_fn=lambda store: "synthetic-installed-local",
            digest_fn=lambda tag: "a" * 64,
            chooser=lambda n: 0)
        with self.assertRaisesRegex(ValueError, "No current reviewed"):
            self.run_next()
        status = self.bank.summary(self.store)
        self.assertEqual(status["approved_ready_unused"], 0)
        self.assertEqual(status["already_compared_outside_bank"], 1)

    def test_delete_task_erases_derived_pair_and_owner_prose(self):
        task = self.add()
        comparison, _ = self.run_next()
        self.assertEqual(self.bank.archive.report(self.store)["total_cases"], 1)
        with self.assertRaisesRegex(ValueError, "Owner confirmation"):
            self.bank.delete(task)
        self.bank.delete(task, confirmed=True)
        self.assertEqual(self.bank.archive.report(self.store)["total_cases"], 0)
        self.assertEqual(self.bank.summary(self.store)["consumed"], 0)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            self.bank._get(task)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            self.bank.archive.show(comparison)

    def test_consumed_task_cannot_be_rereviewed(self):
        task = self.add()
        self.run_next()
        with self.assertRaisesRegex(ValueError, "Consumed"):
            self.bank.review(self.store, task, "rejected", confirmed=True)

    def test_summary_returns_counts_not_task_text_or_gold(self):
        self.add()
        result = self.bank.summary(self.store)
        self.assertEqual(result["approved_ready_unused"], 1)
        self.assertFalse(result["private_task_text_returned"])
        self.assertNotIn("neighbor", json.dumps(result))
        self.assertNotIn("otters", json.dumps(result))

    def test_unbacked_task_id_cannot_bypass_review_guard(self):
        self.add()
        with self.assertRaisesRegex(ValueError, "requires a private task guard"):
            create_comparison(
                self.store, self.task, confirmed=True, task_id=1,
                route_fn=lambda _: None)
        self.assertEqual(self.bank.archive.report(self.store)["total_cases"], 0)

    def test_cli_task_add_is_truly_opt_in_and_list_contains_no_prose(self):
        # CLI uses the same private location but must not create a bank on
        # unconfirmed writes, nor ever print a private task in aggregate.
        other = ExperienceStore(Path(self.store.home.parent) / "separate")
        self.addCleanup(other.close)
        with self.assertRaises(SystemExit):
            main(["--home", str(other.home), "task-add", self.task])
        self.assertFalse((other.home / "twin-style-comparisons.sqlite3").exists())
        with patch("builtins.print") as printer:
            main(["--home", str(self.store.home), "tasks"])
        self.assertNotIn("neighbor", json.dumps(printer.call_args.args))
        self.assertEqual(json.loads(printer.call_args.args[0])["pending"], 0)

    def test_missing_bank_fails_closed_without_creating_archive(self):
        other = ExperienceStore(Path(self.store.home.parent) / "blank")
        self.addCleanup(other.close)
        with self.assertRaises(ValueError):
            start_next(other, confirmed=True,
                       client_factory=lambda tag: LocalModelDouble())
        self.assertFalse((other.home / "twin-style-comparisons.sqlite3").exists())

    def test_duplicate_runs_do_not_create_second_comparison(self):
        self.add()
        case, _ = self.run_next()
        self.assertEqual(self.bank.archive.report(self.store)["total_cases"], 1)
        with self.assertRaises(ValueError):
            self.run_next()
        self.assertEqual(self.bank.archive.report(self.store)["total_cases"], 1)
        self.assertGreater(case, 0)


if __name__ == "__main__":
    unittest.main()
