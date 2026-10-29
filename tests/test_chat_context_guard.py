"""Synthetic-only consent and context integrity on live Twin/Agent chats."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.chat import LocalModelError, answer, context_snapshot, main
from athenz.desktop import DesktopError, DesktopService
from athenz.experience import ExperienceStore


class _ChangingModel:
    model = "synthetic-local"

    def __init__(self, callback=None):
        self.callback = callback
        self.calls = 0

    def generate(self, messages, **kwargs):
        self.calls += 1
        if self.callback:
            self.callback()
        return "SYNTHETIC-NOT-SAFE-TO-PERSIST"


class ChatContextGuardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / "owner-only"
        self.store = ExperienceStore(self.home)
        self.addCleanup(self.store.close)
        self.memory_id = self.store.propose(
            "preference", "Synthetic owner prefers reviewing deployments",
            source="synthetic", approved=True)

    def mutate_other_connection(self, fn):
        other = ExperienceStore(self.home)
        try:
            return fn(other)
        finally:
            other.close()

    def test_answer_refuses_midflight_review_revocation(self):
        model = _ChangingModel(
            lambda: self.mutate_other_connection(
                lambda s: s.status(self.memory_id, "rejected")))
        with self.assertRaisesRegex(LocalModelError, "evidence changed"):
            answer(self.store, model, "deployment?", mode="twin")
        self.assertEqual(model.calls, 1)
        self.assertEqual(self.store.conversation("default", "twin"), [])

    def test_answer_refuses_midflight_reviewed_text_change(self):
        def change(store):
            with store.db:
                store.db.execute(
                    "UPDATE identity SET text=? WHERE id=?",
                    ("Synthetic changed private preference", self.memory_id))
        model = _ChangingModel(lambda: self.mutate_other_connection(change))
        with self.assertRaises(LocalModelError):
            answer(self.store, model, "deployment?", mode="twin")
        self.assertEqual(model.calls, 1)

    def test_unapproved_change_does_not_falsely_invalidate_reply(self):
        model = _ChangingModel(lambda: self.mutate_other_connection(
            lambda s: s.propose("preference", "Private pending-only text",
                                source="synthetic", approved=False)))
        result = answer(self.store, model, "deployment?", mode="twin")
        self.assertEqual(result, "SYNTHETIC-NOT-SAFE-TO-PERSIST")
        self.assertEqual(model.calls, 1)

    def test_approved_training_decision_change_is_detected(self):
        did = self.store.add_decision(
            "Do I prefer testing a synthetic patch?", "Yes",
            "Review first", source="synthetic", approved=True)
        model = _ChangingModel(
            lambda: self.mutate_other_connection(
                lambda s: s.decision_status(did, "rejected")))
        with self.assertRaises(LocalModelError):
            answer(self.store, model, "patch testing?", mode="twin")

    def test_desktop_discards_midflight_approved_memory_revocation(self):
        model = _ChangingModel(lambda: self.mutate_other_connection(
            lambda s: s.status(self.memory_id, "rejected")))
        with patch("athenz.desktop.OllamaClient", return_value=model):
            with self.assertRaises(LocalModelError):
                DesktopService(self.home).send("desk", "twin", "deployment?")
        self.assertEqual(DesktopService(self.home).history("desk", "twin"), [])
        self.assertEqual(model.calls, 1)

    def test_desktop_discards_competing_session_write(self):
        def add_session(store):
            store.add_message("desk", "agent", "user", "SYNTHETIC-RACING-MESSAGE")
        model = _ChangingModel(lambda: self.mutate_other_connection(add_session))
        with patch("athenz.desktop.OllamaClient", return_value=model):
            with self.assertRaisesRegex(DesktopError, "session changed"):
                DesktopService(self.home).send("desk", "agent", "next turn")
        history = DesktopService(self.home).history("desk", "agent")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["content"], "SYNTHETIC-RACING-MESSAGE")
        self.assertEqual(model.calls, 1)

    def test_desktop_unapproved_memory_during_reply_is_allowed(self):
        model = _ChangingModel(lambda: self.mutate_other_connection(
            lambda s: s.propose("identity", "Synthetic pending note",
                                source="synthetic", approved=False)))
        with patch("athenz.desktop.OllamaClient", return_value=model):
            result = DesktopService(self.home).send("desk", "twin", "deployment?")
        self.assertEqual(result["reply"], "SYNTHETIC-NOT-SAFE-TO-PERSIST")
        self.assertEqual(len(DesktopService(self.home).history("desk", "twin")), 2)

    def test_terminal_chat_discards_memory_revocation_and_leaks_no_reply(self):
        model = _ChangingModel(lambda: self.mutate_other_connection(
            lambda s: s.status(self.memory_id, "rejected")))
        output = io.StringIO()
        with patch("athenz.chat.OllamaClient", return_value=model), \
             patch("builtins.input", side_effect=["deployment?", "/exit"]), \
             redirect_stdout(output):
            main(["--home", str(self.home), "--mode", "twin",
                  "--model", "synthetic-local", "--session", "private"])
        self.assertEqual(model.calls, 1)
        self.assertNotIn("SYNTHETIC-NOT-SAFE-TO-PERSIST", output.getvalue())
        self.assertIn("reply discarded", output.getvalue())
        self.assertEqual(self.store.conversation("private", "twin"), [])

    def test_terminal_chat_discards_session_drift_without_model_rerun(self):
        def add_session(store):
            store.add_message("private", "agent", "user", "synthetic competing turn")
        model = _ChangingModel(lambda: self.mutate_other_connection(add_session))
        output = io.StringIO()
        with patch("athenz.chat.OllamaClient", return_value=model), \
             patch("builtins.input", side_effect=["hello", "/exit"]), \
             redirect_stdout(output):
            main(["--home", str(self.home), "--mode", "agent",
                  "--model", "synthetic-local", "--session", "private"])
        self.assertEqual(model.calls, 1)
        self.assertNotIn("SYNTHETIC-NOT-SAFE-TO-PERSIST", output.getvalue())
        self.assertIn("session changed", output.getvalue())
        history = self.store.conversation("private", "agent")
        self.assertEqual(len(history), 1)

    def test_context_snapshot_contains_no_raw_private_prompt_in_digest(self):
        digest, messages = context_snapshot(
            self.store, "What about deployments?", "twin")
        self.assertEqual(len(digest), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in digest))
        self.assertNotIn("Synthetic owner", digest)
        self.assertIn("Synthetic owner", str(messages))


if __name__ == "__main__":
    unittest.main()
