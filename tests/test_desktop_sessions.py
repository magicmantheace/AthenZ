"""Synthetic private desktop session management and mode-safe deletion tests."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.desktop import DesktopError, DesktopService
from athenz.experience import ExperienceStore


class DesktopSessionsTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.home = Path(scratch.name) / "owner-private"
        self.service = DesktopService(self.home)
        self.store = ExperienceStore(self.home)
        self.addCleanup(self.store.close)

    def add(self, session: str, mode: str, role="user", content="Synthetic message"):
        return self.store.add_message(session, mode, role, content)

    def review(self, session="shared", mode="twin"):
        return self.service.session_review(session, mode)

    def delete(self, session="shared", mode="twin", **kw):
        digest = kw.pop("review_sha256", None)
        if digest is None:
            digest = self.review(session, mode)["review_sha256"]
        return self.service.delete_mode_history(
            session, mode, review_sha256=digest,
            confirmed=kw.pop("confirmed", True), **kw)

    def test_list_empty_and_no_content_exposure(self):
        self.assertEqual(self.service.sessions(), [])
        self.add("shared", "twin", content="PRIVATE SYNTHETIC EXCERPT")
        self.add("shared", "agent")
        self.add("older", "twin")
        rows = self.service.sessions()
        self.assertEqual(
            [(r["session"], r["mode"]) for r in rows],
            [("older", "twin"), ("shared", "agent"), ("shared", "twin")])
        self.assertTrue(all(r["messages"] == 1 for r in rows))
        self.assertNotIn("PRIVATE SYNTHETIC EXCERPT", json.dumps(rows))
        self.assertNotIn("content", json.dumps(rows))

    def test_review_includes_only_recent_excerpts_but_hashes_all_messages(self):
        for i in range(12):
            self.add("shared", "twin", content=f"Synthetic {i}")
        report = self.review()
        self.assertEqual(report["messages"], 12)
        self.assertEqual(len(report["recent_excerpts"]), 8)
        self.assertEqual(report["recent_excerpts"][0]["excerpt"], "Synthetic 4")
        self.assertNotIn("Synthetic 0", json.dumps(report))
        self.assertEqual(len(report["review_sha256"]), 64)
        last_id = report["latest_id"]
        with self.store.db:
            self.store.db.execute(
                "UPDATE messages SET content=? WHERE id=?",
                ("Edited synthetic first row", last_id - 11))
        self.assertNotEqual(report["review_sha256"], self.review()["review_sha256"])

    def test_delete_twin_only_keeps_same_name_agent(self):
        first = self.add("shared", "twin")
        self.add("shared", "twin", role="assistant", content="Twin reply")
        agent = self.add("shared", "agent", content="Agent question")
        self.add("other", "twin", content="Other question")
        deleted = self.delete()
        self.assertEqual(deleted["messages_deleted"], 2)
        self.assertTrue(deleted["other_mode_unchanged"])
        self.assertEqual(self.service.history("shared", "twin"), [])
        self.assertEqual(self.service.history("shared", "agent")[0]["id"], agent)
        self.assertEqual(len(self.service.history("other", "twin")), 1)
        self.assertFalse(any(x["mode"] == "twin" and x["session"] == "shared"
                             for x in self.service.sessions()))

    def test_delete_chat_cascades_approved_memories_and_revisions(self):
        user = self.add("shared", "twin", content="Synthetic I prefer code review")
        self.add("shared", "twin", role="assistant", content="Synthetic reply")
        approved = self.store.memory_source_preview(user)
        mid = self.store.propose_message_memory(
            user, "preference", "Synthetic code review before merge",
            review_sha256=approved["review_sha256"], confirmed=True)
        self.store.status(mid, "approved")
        self.store.revise(mid, "Synthetic reviewed second text", "Synthetic correction")
        self.store.status(mid, "approved")
        independent = self.store.propose(
            "value", "Synthetic independent approved value",
            source="owner:synthetic", approved=True)
        self.delete()
        self.assertIsNone(self.store.db.execute(
            "SELECT id FROM identity WHERE id=?", (mid,)).fetchone())
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM identity_revisions WHERE identity_id=?",
            (mid,)).fetchone()[0], 0)
        self.assertIsNotNone(self.store.db.execute(
            "SELECT id FROM identity WHERE id=?", (independent,)).fetchone())

    def test_source_memories_other_mode_remain_approved(self):
        first = self.add("shared", "twin", content="Synthetic twin history")
        second = self.add("shared", "agent", content="Synthetic agent history")
        ids = []
        for message in (first, second):
            preview = self.store.memory_source_preview(message)
            mid = self.store.propose_message_memory(
                message, "preference", f"Synthetic owner note {message}",
                review_sha256=preview["review_sha256"], confirmed=True)
            self.store.status(mid, "approved")
            ids.append(mid)
        self.delete()
        self.assertIsNone(self.store.db.execute(
            "SELECT id FROM identity WHERE id=?", (ids[0],)).fetchone())
        self.assertIsNotNone(self.store.db.execute(
            "SELECT id FROM identity WHERE id=?", (ids[1],)).fetchone())

    def test_feedback_and_training_example_cascade(self):
        self.add("shared", "twin", content="Synthetic question")
        assistant = self.add("shared", "twin", role="assistant",
                             content="Synthetic assistant reply")
        feedback_id = self.store.add_feedback(assistant, "up")
        self.assertTrue(self.store.db.execute(
            "SELECT 1 FROM train_pairs WHERE feedback_id=?",
            (feedback_id,)).fetchone())
        self.delete()
        self.assertFalse(self.store.db.execute(
            "SELECT 1 FROM feedback WHERE id=?", (feedback_id,)).fetchone())
        self.assertFalse(self.store.db.execute(
            "SELECT 1 FROM train_pairs WHERE feedback_id=?",
            (feedback_id,)).fetchone())

    def test_stale_snapshot_fails_on_new_message_or_changed_content(self):
        self.add("shared", "twin", content="Synthetic first")
        stale = self.review()["review_sha256"]
        self.add("shared", "twin", content="Synthetic later")
        with self.assertRaisesRegex(DesktopError, "changed since inspection"):
            self.delete(review_sha256=stale)
        self.assertEqual(len(self.service.history("shared", "twin")), 2)
        latest = self.review()["review_sha256"]
        with self.store.db:
            self.store.db.execute(
                "UPDATE messages SET content='Changed message' "
                "WHERE session='shared' AND mode='twin' AND id="
                "(SELECT MIN(id) FROM messages)")
        with self.assertRaisesRegex(DesktopError, "changed since inspection"):
            self.delete(review_sha256=latest)
        self.assertEqual(len(self.service.history("shared", "twin")), 2)

    def test_requires_confirmation_digest_and_valid_session(self):
        self.add("shared", "twin")
        signature = self.review()["review_sha256"]
        for val in (False, None, 1, "yes"):
            with self.subTest(confirmed=val), self.assertRaises(DesktopError):
                self.delete(review_sha256=signature, confirmed=val)
        for sha in ("invalid", "a" * 63, "z" * 64, 42):
            with self.subTest(sha=sha), self.assertRaises(DesktopError):
                self.delete(review_sha256=sha)
        for name, mode in (("../bad", "twin"), ("shared", "developer"),
                           ("", "agent")):
            with self.subTest(session=name, mode=mode), self.assertRaises(DesktopError):
                self.service.session_review(name, mode)
        for limit in (0, 201, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(DesktopError):
                self.service.sessions(limit=limit)
        self.assertEqual(len(self.service.history("shared", "twin")), 1)

    def test_review_limit_prevents_unbounded_desktop_deletion(self):
        with self.store.db:
            self.store.db.executemany(
                "INSERT INTO messages(session,mode,role,content,created_at) "
                "VALUES ('shared','twin','user','Synthetic test text','2026-01-01')",
                [()] * 5001)
        with self.assertRaisesRegex(DesktopError, "too large"):
            self.review()
        self.assertEqual(len(self.service.sessions()), 1)
        self.assertEqual(self.service.sessions()[0]["messages"], 5001)

    def test_rollback_deletion_if_sqlite_mutation_fails(self):
        self.add("shared", "twin", content="Synthetic first")
        reviewed = self.review()
        original = ExperienceStore.delete_mode_session

        def after_delete_then_fail(store, session, mode):
            original(store, session, mode)
            raise RuntimeError("Synthetic injected failure")

        with patch.object(ExperienceStore, "delete_mode_session",
                          autospec=True, side_effect=after_delete_then_fail):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                self.service.delete_mode_history(
                    "shared", "twin", review_sha256=reviewed["review_sha256"],
                    confirmed=True)
        self.assertEqual(len(self.service.history("shared", "twin")), 1)

    def test_no_model_or_network_is_used_for_session_management(self):
        self.add("shared", "twin")
        with patch("athenz.desktop.OllamaClient",
                   side_effect=AssertionError("Inference not authorized")):
            self.assertTrue(self.service.sessions())
            self.assertTrue(self.review()["recent_excerpts"])
            self.delete()
        self.assertEqual(self.service.sessions(), [])


if __name__ == "__main__":
    unittest.main()
