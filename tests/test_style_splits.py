"""Private writing style split and evaluation-readiness regression tests."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from athenz.cli import main
from athenz.evaluation import _reference_fingerprint, _fingerprint
from athenz.migrations import migrate_v6
from athenz.prompting import build_messages
from athenz.experience import ExperienceStore
from athenz.style_readiness import style_readiness


class StyleSplitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = ExperienceStore(Path(self.tmp.name) / "private")
        self.addCleanup(self.store.close)

    def sample(self, text, split="train", status="approved"):
        item = self.store.add_sample(text, source="synthetic:owner", split=split)
        self.store.db.execute(
            "UPDATE writing_samples SET status=? WHERE id=?", (status, item))
        self.store.db.commit()
        return item

    def test_train_only_twin_context_excludes_approved_heldout_samples(self):
        self.sample("REVIEWED_TRAIN_OWNER_STYLE", "train")
        self.sample("PRIVATE_HELDOUT_WRITING_TEST", "test")
        self.sample("PRIVATE_HELDOUT_WRITING_CALIBRATION", "calibration")
        twin = str(build_messages(self.store, "How would I write a letter?", "twin"))
        agent = str(build_messages(self.store, "How would I write a letter?", "agent"))
        self.assertIn("REVIEWED_TRAIN_OWNER_STYLE", twin)
        self.assertNotIn("PRIVATE_HELDOUT_WRITING_TEST", twin)
        self.assertNotIn("PRIVATE_HELDOUT_WRITING_CALIBRATION", twin)
        self.assertNotIn("PRIVATE_HELDOUT_WRITING_TEST", agent)
        self.assertNotIn("REVIEWED_TRAIN_OWNER_STYLE", agent)

    def test_heldout_approvals_do_not_change_training_reference_fingerprint(self):
        first = _reference_fingerprint(self.store)
        candidate = self.store.add_sample(
            "SECRET_LOCAL_STYLE_CALIBRATION", source="synthetic:owner",
            split="calibration")
        self.assertEqual(_reference_fingerprint(self.store), first)
        self.store.db.execute(
            "UPDATE writing_samples SET status='approved' WHERE id=?", (candidate,))
        self.store.db.commit()
        self.assertEqual(_reference_fingerprint(self.store), first)
        training = self.sample("Approved style used in prompts", "train")
        self.assertNotEqual(_reference_fingerprint(self.store), first)
        self.store.delete("writing_samples", training)
        self.assertEqual(_reference_fingerprint(self.store), first)

    def test_reference_training_fingerprint_compatible_with_pre_v6_writing_rows(self):
        self.sample("A synthetic owner's reviewed older writing", "train")
        core = []
        for table, predicate, fields in (
            ("identity", "status='approved'", "*"),
            ("decisions", "status='approved' AND split='train'", "*"),
            ("episodes", "status='approved'", "*"),
            ("writing_samples", "status='approved'",
             "id,text,source,source_ref,created_at,status"),
        ):
            rows = [list(x) for x in self.store.db.execute(
                f"SELECT {fields} FROM {table} WHERE {predicate} ORDER BY id")]
            if rows or table != "writing_samples":
                core.append([table, rows])
        self.assertEqual(_reference_fingerprint(self.store), _fingerprint(core))

    def test_validation_counts_are_aggregate_and_never_infer_accuracy(self):
        for i in range(3):
            self.sample(f"Reviewed training owner writing {i}", "train")
            self.sample(f"Independent heldout owner writing {i}", "test")
        result = style_readiness(self.store)
        self.assertEqual(result["approved_counts"], {
            "train": 3, "calibration": 0, "test": 3})
        self.assertTrue(result["pilot_evaluation_sufficient"])
        self.assertFalse(result["owner_style_accuracy_evaluated"])
        self.assertFalse(result["model_called"])
        self.assertNotIn("owner writing", json.dumps(result).lower())
        self.assertFalse(result["private_text_returned"])

    def test_normalized_cross_split_duplication_blocks_pilot(self):
        for i in range(3):
            self.sample(f"Owner writes about autumn leaf {i}", "train")
            self.sample(f"Independent story fragment {i}", "test")
        self.sample("Owner, WRITES about Autumn Leaf 0!", "test")
        result = style_readiness(self.store)
        self.assertEqual(result["cross_split_normalized_duplicates"], 1)
        self.assertFalse(result["pilot_evaluation_sufficient"])
        self.assertNotIn("autumn", json.dumps(result).lower())

    def test_owner_review_rejects_normalized_duplicate_across_splits(self):
        train = self.store.add_sample(
            "My personal Synthetic Autumn Story!", source="synthetic",
            split="train")
        heldout = self.store.add_sample(
            "MY personal synthetic autumn story", source="synthetic",
            split="test")
        self.store.set_review("writing_samples", train, "approved")
        with self.assertRaisesRegex(ValueError, "Duplicate writing sample"):
            self.store.set_review("writing_samples", heldout, "approved")
        row = self.store.db.execute(
            "SELECT status FROM writing_samples WHERE id=?", (heldout,)).fetchone()
        self.assertEqual(row["status"], "pending")
        self.store.set_review("writing_samples", train, "rejected")
        self.assertTrue(self.store.set_review(
            "writing_samples", heldout, "approved"))
        self.assertEqual(style_readiness(self.store)["cross_split_normalized_duplicates"], 0)

    def test_unapproved_sources_never_count_as_ready(self):
        self.sample("Pending heldout sample", "test", "pending")
        self.sample("Rejected training sample", "train", "rejected")
        state = style_readiness(self.store)
        self.assertEqual(state["pending_counts"]["test"], 1)
        self.assertEqual(state["rejected_counts"]["train"], 1)
        self.assertEqual(state["approved_counts"]["test"], 0)
        self.assertFalse(state["pilot_evaluation_sufficient"])

    def test_split_validation_rejects_unsupported_values(self):
        for split in ("public", "", "Test", None, True, 1):
            with self.subTest(split=split):
                with self.assertRaises(ValueError):
                    self.store.add_sample("Synthetic sample", source="synthetic", split=split)

    def test_cli_can_add_heldout_sample_without_sending_it_to_prompt(self):
        with patch("builtins.print") as output:
            main(["--home", str(self.store.home), "sample",
                  "PRIVATE_STYLE_TEST_ONLY", "--split", "test"])
            main(["--home", str(self.store.home), "style-readiness"])
        status = json.loads(output.call_args.args[0])
        self.assertEqual(status["pending_counts"]["test"], 1)
        self.assertNotIn("PRIVATE_STYLE_TEST_ONLY", json.dumps(status))
        sample = self.store.db.execute(
            "SELECT id FROM writing_samples WHERE split='test'").fetchone()[0]
        self.store.db.execute(
            "UPDATE writing_samples SET status='approved' WHERE id=?", (sample,))
        self.store.db.commit()
        self.assertNotIn("PRIVATE_STYLE_TEST_ONLY",
                         str(build_messages(self.store, "Write a letter", "twin")))

    def test_reopening_v6_profile_is_idempotent(self):
        from athenz.experience import ExperienceStore
        original = self.store.add_sample(
            "Synthetic held-out text never becomes training", source="synthetic",
            split="test")
        self.store.set_review("writing_samples", original, "approved")
        reopened = ExperienceStore(self.store.home)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.db.execute(
            "PRAGMA user_version").fetchone()[0], 6)
        row = reopened.db.execute(
            "SELECT split,status,text FROM writing_samples WHERE id=?",
            (original,)).fetchone()
        self.assertEqual(tuple(row), (
            "test", "approved", "Synthetic held-out text never becomes training"))
        self.assertNotIn("Synthetic held-out text",
                         str(build_messages(reopened, "What is my style?", "twin")))

    def test_migration_retains_legacy_approved_sample_as_training_only(self):
        legacy = sqlite3.connect(":memory:")
        self.addCleanup(legacy.close)
        legacy.executescript("""
            CREATE TABLE writing_samples(
                id INTEGER PRIMARY KEY, text TEXT NOT NULL,
                source TEXT NOT NULL, source_ref TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
            INSERT INTO writing_samples
                (text,source,source_ref,created_at,status)
                VALUES ('SYNTHETIC LEGACY','owner','old','2026-01-01','approved');
            PRAGMA user_version=5;
        """)
        migrate_v6(legacy)
        self.assertEqual(legacy.execute("PRAGMA user_version").fetchone()[0], 6)
        row = legacy.execute(
            "SELECT text,status,split FROM writing_samples").fetchone()
        self.assertEqual(row, ("SYNTHETIC LEGACY", "approved", "train"))
        migrate_v6(legacy)
        self.assertEqual(legacy.execute(
            "SELECT COUNT(*) FROM writing_samples").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
