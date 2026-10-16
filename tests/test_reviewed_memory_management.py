"""Synthetic tests of owner-reviewed corrections, revocation and live forgetting."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from athenz.desktop import DesktopError, DesktopService
from athenz.experience import ExperienceStore
from athenz.prompting import build_messages


class ReviewedMemoryManagementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / "private"
        self.store = ExperienceStore(self.home)
        self.addCleanup(self.store.close)
        self.service = DesktopService(self.home)
        self.memory_id = self.store.propose(
            "preference", "Synthetic preference: review code changes",
            source="owner:synthetic", approved=True)

    def detail(self, memory_id=None):
        return self.service.approved_memory_detail(
            self.memory_id if memory_id is None else memory_id)

    def act(self, action, record=None, *, new_text="", reason="", confirmed=True):
        record = self.detail() if record is None else record
        return self.service.manage_approved_memory(
            self.memory_id, action, review_sha256=record["review_sha256"],
            confirmed=confirmed, new_text=new_text, reason=reason)

    def test_list_and_full_record_review_are_owner_local(self):
        self.store.propose("identity", "UNAPPROVED SYNTHETIC CLAIM",
                           source="synthetic")
        rows = self.service.approved_memories()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], self.memory_id)
        self.assertEqual(rows[0]["kind"], "preference")
        self.assertNotIn("UNAPPROVED SYNTHETIC CLAIM", json.dumps(rows))
        record = self.detail()
        self.assertEqual(record["text"], "Synthetic preference: review code changes")
        self.assertEqual(record["source"], "owner:synthetic")
        self.assertEqual(len(record["review_sha256"]), 64)
        self.assertEqual(record["status"], "approved")
        self.assertEqual(record["review_sha256"], self.detail()["review_sha256"])

    def test_correction_immediately_deactivates_old_memory(self):
        before = build_messages(self.store, "review code changes", "twin")
        self.assertIn("Synthetic preference: review code changes",
                      json.dumps(before))
        result = self.act(
            "revise", new_text="Synthetic updated preference: ask for tests",
            reason="Owner corrected their preference")
        self.assertEqual(result["result"], "pending-review")
        row = self.store.db.execute(
            "SELECT text,status FROM identity WHERE id=?", (self.memory_id,)
        ).fetchone()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["text"], "Synthetic updated preference: ask for tests")
        self.assertNotIn(
            "Synthetic updated preference: ask for tests",
            json.dumps(build_messages(self.store, "review code changes", "twin")))
        self.assertNotIn(
            "Synthetic preference: review code changes",
            json.dumps(build_messages(self.store, "review code changes", "twin")))
        revisions = self.store.db.execute(
            "SELECT prior_text,new_text,reason FROM identity_revisions "
            "WHERE identity_id=?", (self.memory_id,)).fetchall()
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0]["prior_text"],
                         "Synthetic preference: review code changes")
        self.assertTrue(self.store.status(self.memory_id, "approved"))
        self.assertIn(
            "Synthetic updated preference: ask for tests",
            json.dumps(build_messages(self.store, "ask for tests", "twin")))

    def test_revocation_stops_twin_retrieval_without_deleting_record(self):
        result = self.act("revoke")
        self.assertEqual(result["result"], "revoked")
        row = self.store.db.execute(
            "SELECT text,status FROM identity WHERE id=?", (self.memory_id,)
        ).fetchone()
        self.assertEqual(row["status"], "rejected")
        self.assertEqual(row["text"], "Synthetic preference: review code changes")
        self.assertEqual(self.service.approved_memories(), [])
        self.assertNotIn(
            "Synthetic preference: review code changes",
            json.dumps(build_messages(self.store, "review code changes", "twin")))
        with self.assertRaisesRegex(DesktopError, "no longer exists"):
            self.detail()

    def test_forget_erases_memory_and_revision_history_only(self):
        self.store.revise(self.memory_id, "Synthetic corrected text",
                          "Synthetic correction")
        self.store.status(self.memory_id, "approved")
        independent = self.store.propose(
            "value", "Synthetic independent value", source="owner:synthetic",
            approved=True)
        result = self.act("forget")
        self.assertEqual(result["result"], "forgotten-from-live-database")
        self.assertIsNone(self.store.db.execute(
            "SELECT id FROM identity WHERE id=?", (self.memory_id,)
        ).fetchone())
        self.assertEqual(self.store.db.execute(
            "SELECT count(*) FROM identity_revisions WHERE identity_id=?",
            (self.memory_id,)
        ).fetchone()[0], 0)
        self.assertIsNotNone(self.store.db.execute(
            "SELECT id FROM identity WHERE id=?", (independent,)
        ).fetchone())
        self.assertNotIn(
            "Synthetic corrected text",
            json.dumps(build_messages(self.store, "corrected text", "twin")))

    def test_stale_digest_or_provenance_change_refuses_all_actions(self):
        stale = self.detail()
        with self.store.db:
            self.store.db.execute(
                "UPDATE identity SET source_ref=? WHERE id=?",
                ("synthetic_changed_ref", self.memory_id))
        for action in ("revise", "revoke", "forget"):
            with self.subTest(action=action), self.assertRaisesRegex(
                    DesktopError, "changed after inspection"):
                self.act(action, stale, new_text="Completely different text",
                         reason="Owner explanation")
        self.assertEqual(self.detail()["status"], "approved")
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM identity_revisions WHERE identity_id=?",
            (self.memory_id,)).fetchone()[0], 0)

    def test_revoked_elsewhere_between_inspection_and_action(self):
        stale = self.detail()
        other = ExperienceStore(self.home)
        try:
            other.status(self.memory_id, "rejected")
        finally:
            other.close()
        with self.assertRaisesRegex(DesktopError, "changed after inspection"):
            self.act("forget", stale)
        self.assertIsNotNone(self.store.db.execute(
            "SELECT id FROM identity WHERE id=?", (self.memory_id,)
        ).fetchone())

    def test_revision_requires_reason_and_distinct_bounded_text(self):
        for change, reason in (
            ("", "because"),
            ("   ", "because"),
            ("new summary", ""),
            ("new summary", "  "),
            ("a" * 1201, "because"),
            ("new summary", "x" * 501),
            ("Synthetic preference: review code changes", "because"),
        ):
            with self.subTest(change=change[:10], why=reason[:10]), \
                 self.assertRaises(DesktopError):
                self.act("revise", new_text=change, reason=reason)
        self.assertEqual(self.detail()["status"], "approved")

    def test_actions_require_explicit_confirmation_and_exact_digest(self):
        good = self.detail()
        for action in ("revise", "revoke", "forget"):
            with self.subTest(action=action), self.assertRaises(DesktopError):
                self.act(action, good, new_text="Changed synthetic preference",
                         reason="Because", confirmed=False)
        with self.assertRaises(DesktopError):
            self.service.manage_approved_memory(
                self.memory_id, "forget", review_sha256="bad", confirmed=True)
        with self.assertRaises(DesktopError):
            self.service.manage_approved_memory(
                self.memory_id, "ignore", review_sha256=good["review_sha256"],
                confirmed=True)
        self.assertEqual(self.detail()["status"], "approved")

    def test_approved_source_from_chat_can_be_forgotten_without_erasing_chat(self):
        source_id = self.store.add_message("desk", "twin", "user",
                                           "Synthetic source: verify releases")
        source = self.store.memory_source_preview(source_id)
        memory_id = self.store.propose_message_memory(
            source_id, "preference", "Synthetic verify releases",
            review_sha256=source["review_sha256"], confirmed=True)
        self.store.status(memory_id, "approved")
        detail = self.detail(memory_id)
        result = self.service.manage_approved_memory(
            memory_id, "forget", review_sha256=detail["review_sha256"],
            confirmed=True)
        self.assertEqual(result["result"], "forgotten-from-live-database")
        self.assertEqual(len(self.store.conversation("desk", "twin")), 1)
        self.assertIsNone(self.store.db.execute(
            "SELECT id FROM identity WHERE id=?", (memory_id,)).fetchone())

    def test_limits_and_pending_records_refused_by_management(self):
        for count in (0, 201, True, "10"):
            with self.subTest(count=count), self.assertRaises(DesktopError):
                self.service.approved_memories(limit=count)
        for item_id in (0, -1, True, "1"):
            with self.subTest(item_id=item_id), self.assertRaises(DesktopError):
                self.service.approved_memory_detail(item_id)
        new = self.store.propose("preference", "Unreviewed pending memory",
                                 source="synthetic")
        with self.assertRaises(DesktopError):
            self.detail(new)


if __name__ == "__main__":
    unittest.main()
