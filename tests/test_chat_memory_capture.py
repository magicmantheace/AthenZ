"""Synthetic local owner-reviewed chat-to-memory consent and erasure tests."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.cli import main
from athenz.desktop import DesktopError, DesktopService
from athenz.experience import ExperienceStore
from athenz.prompting import build_messages


class ChatMemoryTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home = Path(t.name) / "private"
        self.store = ExperienceStore(self.home)
        self.addCleanup(self.store.close)
        self.user = self.store.add_message(
            "alpha", "twin", "user",
            "Synthetic owner says I prefer an independent review before release.")
        self.assistant = self.store.add_message(
            "alpha", "twin", "assistant",
            "Synthetic model guessed the owner prefers unreviewed release.")
        self.other = self.store.add_message(
            "beta", "agent", "user",
            "Synthetic other owner's independent note is not this source.")

    def preview(self, message_id=None):
        return self.store.memory_source_preview(message_id or self.user)

    def propose(self, *, kind="preference", text="Prefer peer review before release",
                message_id=None, **options):
        source = self.preview(message_id)
        return self.store.propose_message_memory(
            source["id"], kind, text, review_sha256=source["review_sha256"],
            confirmed=True, **options)

    def identity(self, memory_id):
        return self.store.db.execute(
            "SELECT * FROM identity WHERE id=?", (memory_id,)).fetchone()

    def test_pinned_preview_is_owner_message_only(self):
        data = self.preview()
        self.assertEqual(data["id"], self.user)
        self.assertEqual(data["session"], "alpha")
        self.assertEqual(data["mode"], "twin")
        self.assertEqual(len(data["review_sha256"]), 64)
        self.assertIn("independent review", data["content"])
        for value in (self.assistant, -1, 999999, True, "1"):
            with self.subTest(message=value), self.assertRaises(ValueError):
                self.store.memory_source_preview(value)

    def test_pending_until_separate_explicit_approval(self):
        mid = self.propose()
        row = self.identity(mid)
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["source"], "owner:chat-message")
        self.assertEqual(row["source_ref"], str(self.user))
        before = build_messages(self.store, "How do I review a release?", "twin")
        self.assertNotIn("Prefer peer review before release", json.dumps(before))
        self.assertTrue(self.store.status(mid, "approved"))
        after = build_messages(self.store, "How do I review a release?", "twin")
        self.assertIn("Prefer peer review before release", json.dumps(after))
        self.assertEqual(self.store.conversation("alpha", "twin")[0]["content"],
                         self.preview()["content"])

    def test_refuse_assistant_as_autobiographical_memory(self):
        digest = self.preview()["review_sha256"]
        with self.assertRaisesRegex(ValueError, "Source message changed"):
            self.store.propose_message_memory(
                self.assistant, "identity", "I experienced an unreviewed release",
                review_sha256=digest, confirmed=True)
        self.assertEqual(self.store.list_items("identity"), [])

    def test_missing_consent_digest_and_bad_summaries(self):
        good = self.preview()["review_sha256"]
        for kw in (
            {"confirmed": False, "review_sha256": good, "text": "Accepted"},
            {"confirmed": 1, "review_sha256": good, "text": "Accepted"},
            {"confirmed": True, "review_sha256": "not-a-digest", "text": "Accepted"},
            {"confirmed": True, "review_sha256": good, "text": ""},
            {"confirmed": True, "review_sha256": good, "text": "x" * 1201},
            {"confirmed": True, "review_sha256": good, "text": "Valid", "kind": "unknown"},
        ):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.store.propose_message_memory(
                    self.user, kw.get("kind", "preference"), kw["text"],
                    review_sha256=kw["review_sha256"], confirmed=kw["confirmed"])
        self.assertEqual(self.store.list_items("identity"), [])

    def test_message_content_change_invalidates_review_digest(self):
        reviewed = self.preview()
        with self.store.db:
            self.store.db.execute(
                "UPDATE messages SET content=? WHERE id=?",
                ("Source edited after owner inspection", self.user))
        with self.assertRaisesRegex(ValueError, "changed after owner review"):
            self.store.propose_message_memory(
                self.user, "preference", "Stale memory",
                review_sha256=reviewed["review_sha256"], confirmed=True)
        self.assertEqual(self.store.list_items("identity"), [])

    def test_duplicate_source_message_fails_closed(self):
        self.propose()
        with self.assertRaisesRegex(ValueError, "already has a memory"):
            self.propose(text="A conflicting second preference")
        self.assertEqual(len(self.store.list_items("identity")), 1)

    def test_delete_one_source_message_cascades_approved_memory(self):
        mid = self.propose()
        self.store.status(mid, "approved")
        self.assertTrue(self.store.forget_runtime("messages", self.user))
        self.assertIsNone(self.identity(mid))
        self.assertNotIn("Prefer peer review before release",
                         json.dumps(build_messages(self.store, "review release?", "twin")))
        self.assertEqual(len(self.store.conversation("alpha", "twin")), 1)
        self.assertEqual(self.store.conversation("alpha", "twin")[0]["role"], "assistant")

    def test_delete_session_erases_linked_memory_but_not_other_session(self):
        mid = self.propose()
        different = self.propose(message_id=self.other,
                                 text="Plan independently of the other topic")
        self.store.status(mid, "approved")
        self.store.status(different, "approved")
        self.assertEqual(self.store.delete_session("alpha"), 2)
        self.assertIsNone(self.identity(mid))
        self.assertIsNotNone(self.identity(different))
        self.assertEqual(len(self.store.conversation("beta", "agent")), 1)

    def test_delete_linked_memory_erases_revision_history(self):
        mid = self.propose()
        self.store.status(mid, "approved")
        self.store.revise(mid, "Owner corrected summary", "Synthetic correction")
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM identity_revisions WHERE identity_id=?",
            (mid,)).fetchone()[0], 1)
        self.store.forget_runtime("messages", self.user)
        self.assertIsNone(self.identity(mid))
        self.assertEqual(self.store.db.execute(
            "SELECT COUNT(*) FROM identity_revisions WHERE identity_id=?",
            (mid,)).fetchone()[0], 0)

    def test_delete_session_does_not_delete_unrelated_manual_memory(self):
        unrelated = self.store.propose(
            "value", "Synthetic independently approved value",
            source="owner:cli", approved=True)
        self.propose()
        self.store.delete_session("alpha")
        self.assertIsNotNone(self.identity(unrelated))

    def test_desktop_scopes_review_to_exact_session_mode(self):
        desktop = DesktopService(self.home)
        preview = desktop.memory_source_preview("alpha", "twin", self.user)
        for sess, mode in (("alpha", "agent"), ("beta", "twin")):
            with self.subTest(sess=sess, mode=mode), self.assertRaises(DesktopError):
                desktop.memory_source_preview(sess, mode, self.user)
            with self.subTest(sess=sess, mode=mode), self.assertRaises(DesktopError):
                desktop.propose_message_memory(
                    sess, mode, self.user, "preference", "Unapproved summary",
                    review_sha256=preview["review_sha256"], confirmed=True)
        mid = desktop.propose_message_memory(
            "alpha", "twin", self.user, "preference",
            "Prefer safe synthetic peer review",
            review_sha256=preview["review_sha256"], confirmed=True)
        self.assertEqual(self.identity(mid)["status"], "pending")
        detail = desktop.review_detail("identity", mid)
        self.assertEqual(detail["source_ref"], str(self.user))
        desktop.review("identity", mid, "approved",
                       review_sha256=detail["review_sha256"])
        self.assertEqual(self.identity(mid)["status"], "approved")

    def test_cli_preview_confirm_and_no_model_generation(self):
        out = io.StringIO()
        with patch("athenz.chat.OllamaClient") as llm:
            with redirect_stdout(out):
                main(["--home", str(self.home), "memory-preview", str(self.user)])
            llm.assert_not_called()
        preview = json.loads(out.getvalue())
        self.assertEqual(preview["review_sha256"], self.preview()["review_sha256"])
        with self.assertRaisesRegex(ValueError, "Explicit --confirm"):
            main(["--home", str(self.home), "memory-from-message",
                  str(self.user), "preference", "Proposed summary",
                  "--review-sha256", preview["review_sha256"]])
        with redirect_stdout(io.StringIO()):
            main(["--home", str(self.home), "memory-from-message",
                  str(self.user), "preference", "Proposed summary",
                  "--review-sha256", preview["review_sha256"], "--confirm"])
        self.assertEqual(self.store.list_items("identity", "approved"), [])
        self.assertEqual(len(self.store.list_items("identity", "pending")), 1)


if __name__ == "__main__":
    unittest.main()
