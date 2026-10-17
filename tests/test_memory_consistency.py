"""Synthetic review-only memory consistency tests; no owner corpus."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.cli import main
from athenz.desktop import DesktopService
from athenz.experience import ExperienceStore
from athenz.memory_consistency import (
    MAX_APPROVED_SCAN, MemoryConsistencyError, audit_approved_memories
)
from athenz.prompting import build_messages


class MemoryConsistencyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "private"
        self.store = ExperienceStore(self.home)
        self.addCleanup(self.store.close)

    def propose(self, kind="preference", text="I prefer synthetic regression tests",
                approved=True):
        return self.store.propose(
            kind, text, source="synthetic:owner-consent", approved=approved)

    def audit(self, limit=80):
        return audit_approved_memories(self.store, limit=limit)

    def test_empty_and_single_memory_are_not_conflict_free_claims(self):
        report = self.audit()
        self.assertEqual(report["status"], "no-supported-pattern-matches")
        self.assertFalse(report["no_conflicts_proven"])
        self.assertFalse(report["confirmed_conflicts"])
        self.propose()
        report = self.audit()
        self.assertEqual(report["approved_records_scanned"], 1)
        self.assertEqual(report["candidates"], [])
        self.assertFalse(report["automatic_actions_taken"])

    def test_normalized_duplicate_with_punctuation_and_case(self):
        first = self.propose(text="I prefer detailed code reviews.")
        second = self.propose(text="  i PREFER detailed code reviews!!!  ")
        report = self.audit()
        self.assertEqual(report["candidate_counts"]["normalized-duplicate"], 1)
        self.assertEqual(report["candidates"], [{
            "kind": "normalized-duplicate",
            "first_id": first, "second_id": second
        }])
        self.assertNotIn("detailed code reviews", json.dumps(report))

    def test_simple_opposite_first_person_pref_is_only_a_possible_conflict(self):
        first = self.propose(text="I prefer fictional winter climbing")
        second = self.propose(text="I do not prefer fictional winter climbing")
        report = self.audit()
        self.assertEqual(report["status"], "review-candidates-found")
        self.assertEqual(report["candidate_counts"]["possible-polarity-conflict"], 1)
        self.assertIn({
            "kind": "possible-polarity-conflict",
            "first_id": first, "second_id": second
        }, report["candidates"])
        self.assertFalse(report["confirmed_conflicts"])
        for memory_id in (first, second):
            self.assertEqual(self.store.db.execute(
                "SELECT status FROM identity WHERE id=?", (memory_id,)
            ).fetchone()["status"], "approved")

    def test_contraction_and_no_longer_are_review_hints(self):
        first = self.propose(text="I like fictional oat biscuits")
        second = self.propose(text="I don't like fictional oat biscuits")
        third = self.propose(text="I no longer like fictional oat biscuits")
        report = self.audit()
        self.assertEqual(report["candidate_counts"]["possible-polarity-conflict"], 2)
        self.assertTrue(all(item["first_id"] == first
                            for item in report["candidates"]
                            if item["kind"] == "possible-polarity-conflict"))
        self.assertNotIn("fictional oat biscuits", json.dumps(report))
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)

    def test_different_kind_and_changed_objects_are_not_auto_classified(self):
        self.propose("value", "I prefer synthetic manuals")
        self.propose("preference", "I do not prefer synthetic manuals")
        self.propose("value", "I do not prefer synthetic handbooks")
        self.propose("value", "My favorite color is blue")
        self.propose("value", "My favorite color is red")
        self.assertEqual(self.audit()["candidates"], [])

    def test_pending_and_revoked_never_counted(self):
        valid = self.propose(text="I enjoy fictional pottery")
        not_reviewed = self.propose(text="I do not enjoy fictional pottery",
                                    approved=False)
        self.assertEqual(self.audit()["candidates"], [])
        self.store.status(not_reviewed, "approved")
        self.assertEqual(len(self.audit()["candidates"]), 1)
        self.store.status(not_reviewed, "rejected")
        self.assertEqual(self.audit()["candidates"], [])
        self.assertEqual(self.audit()["approved_records_scanned"], 1)
        self.assertIsNotNone(self.store.db.execute(
            "SELECT id FROM identity WHERE id=?", (valid,)).fetchone())

    def test_audit_never_edits_prompts_or_revisions_or_status(self):
        self.propose(text="I prefer red synthetic paper")
        self.propose(text="I do not prefer red synthetic paper")
        before = build_messages(self.store, "red synthetic paper", "twin")
        initial_events = self.store.db.execute(
            "SELECT COUNT(*) FROM events").fetchone()[0]
        for _ in range(3):
            self.audit()
        self.assertEqual(build_messages(self.store, "red synthetic paper", "twin"),
                         before)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM events").fetchone()[0], initial_events)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM identity_revisions").fetchone()[0], 0)
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM identity WHERE status='approved'"
        ).fetchone()[0], 2)

    def test_bounded_pair_count_and_aggregates_are_stable(self):
        first = self.propose(text="Duplicate synthetic clue")
        for i in range(11):
            self.propose(text="Duplicate synthetic clue")
        report = self.audit(limit=3)
        self.assertEqual(report["approved_records_scanned"], 12)
        self.assertEqual(report["candidate_counts"]["normalized-duplicate"], 11)
        self.assertEqual(report["shown"], 3)
        self.assertEqual(report["additional_candidates_not_shown"], 8)
        self.assertEqual([x["second_id"] for x in report["candidates"]],
                         [first + 1, first + 2, first + 3])
        self.assertEqual(self.audit(limit=3), report)

    def test_input_validation_refuses_ambiguous_values(self):
        for limit in (0, 81, "10", True, None, -1, 3.5):
            with self.subTest(limit=limit), self.assertRaises(MemoryConsistencyError):
                self.audit(limit=limit)
        self.assertFalse(self.store.db.in_transaction)

    def test_full_scan_cap_refuses_false_complete_clean_report(self):
        with self.store.db:
            self.store.db.executemany(
                "INSERT INTO identity "
                "(kind,text,source,confidence,status,created_at,updated_at) "
                "VALUES ('value',?,'synthetic',1,'approved','2026-01-01','2026-01-01')",
                [(f"Unique synthetic record {i}",)
                 for i in range(MAX_APPROVED_SCAN + 1)])
        with self.assertRaisesRegex(MemoryConsistencyError, "Too many approved"):
            self.audit()
        self.assertFalse(self.store.db.in_transaction)

    def test_cli_and_desktop_never_call_ollama_or_expose_text(self):
        first = self.propose(text="I want synthetic tea")
        second = self.propose(text="I do not want synthetic tea")
        out = io.StringIO()
        with patch("athenz.desktop.OllamaClient",
                   side_effect=AssertionError("No inference authorized")), \
             patch("athenz.chat.OllamaClient",
                   side_effect=AssertionError("No inference authorized")):
            report = DesktopService(self.home).memory_consistency_audit()
            with redirect_stdout(out):
                main(["--home", str(self.home), "memory-audit"])
        self.assertEqual(json.loads(out.getvalue()), report)
        self.assertEqual(report["candidates"][0]["first_id"], first)
        self.assertEqual(report["candidates"][0]["second_id"], second)
        self.assertNotIn("synthetic tea", out.getvalue())
        detail = DesktopService(self.home).approved_memory_detail(first)
        self.assertIn("synthetic tea", detail["text"])

    def test_audit_rejects_ambient_open_sqlite_transaction(self):
        self.store.db.execute("BEGIN")
        try:
            with self.assertRaisesRegex(MemoryConsistencyError, "idle database"):
                self.audit()
        finally:
            self.store.db.rollback()


if __name__ == "__main__":
    unittest.main()
