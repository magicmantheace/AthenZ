"""Synthetic end-to-end standalone Twin lifecycle with desktop persistence.

Uses a capturing fake model, not an Ollama performance or personality test.
Private disposable profile only; no owner data or external requests.
"""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.desktop import DesktopService
from athenz.experience import ExperienceStore


class CaptureLocalModel:
    model = "synthetic-local"

    def __init__(self):
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        return "A synthetic reply; no personal facts are asserted."


class TwinFirstLifecycleTests(unittest.TestCase):
    def test_reopen_correct_reapprove_revoke_and_reopen(self):
        with tempfile.TemporaryDirectory() as scratch:
            home = Path(scratch) / "private-profile"
            with_store = ExperienceStore(home)
            try:
                memory_id = with_store.propose(
                    "preference", "I prefer synthetic lavender tea",
                    source="owner:synthetic", approved=True)
            finally:
                with_store.close()

            client = CaptureLocalModel()
            with patch("athenz.desktop.OllamaClient", return_value=client):
                first = DesktopService(home).send(
                    "owner-session", "twin", "Do I prefer lavender tea?",
                    model="synthetic-local")
                self.assertIn("synthetic lavender tea",
                              client.calls[-1][1]["content"])
                self.assertEqual(first["mode"], "twin")

                # New DesktopService instances also read the persisted session.
                restarted = DesktopService(home)
                self.assertEqual(len(restarted.history("owner-session", "twin")), 2)
                self.assertEqual(len(restarted.sessions()), 1)

                old = restarted.approved_memory_detail(memory_id)
                restarted.manage_approved_memory(
                    memory_id, "revise",
                    review_sha256=old["review_sha256"],
                    new_text="I prefer synthetic mint tea",
                    reason="Synthetic owner correction", confirmed=True)
                restarted.send("owner-session", "twin", "Which tea do I prefer?",
                               model="synthetic-local")
                # A pending correction must not become approved prompt context.
                profile_pending = client.calls[-1][1]["content"]
                self.assertNotIn("synthetic lavender tea", profile_pending)
                self.assertNotIn("synthetic mint tea", profile_pending)
                self.assertIn("RECENT SAME-SESSION CHAT",
                              str(client.calls[-1]))

                pending = restarted.review_detail("identity", memory_id)
                self.assertTrue(restarted.review(
                    "identity", memory_id, "approved",
                    review_sha256=pending["review_sha256"]))
                DesktopService(home).send(
                    "owner-session", "twin", "Which tea do I prefer?",
                    model="synthetic-local")
                self.assertIn("synthetic mint tea",
                              client.calls[-1][1]["content"])

                approved = restarted.approved_memory_detail(memory_id)
                restarted.manage_approved_memory(
                    memory_id, "revoke",
                    review_sha256=approved["review_sha256"], confirmed=True)
                DesktopService(home).send(
                    "owner-session", "twin", "Which tea do I prefer?",
                    model="synthetic-local")
                self.assertNotIn("synthetic mint tea",
                                 client.calls[-1][1]["content"])
                self.assertIn("No topically matching approved owner fact",
                              client.calls[-1][0]["content"])

            # All four completed turns survive closing/reopening; no Agent leak.
            final = DesktopService(home)
            self.assertEqual(len(final.history("owner-session", "twin")), 8)
            self.assertEqual(final.history("owner-session", "agent"), [])


if __name__ == "__main__":
    unittest.main()
