"""Read-only, owner-local Twin evidence preview regression tests.

No live model calls, external requests, training, or personal owner data.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from athenz.desktop import DesktopError, DesktopService
from athenz.experience import ExperienceStore


class TwinEvidencePreviewTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.home = Path(scratch.name) / "synthetic-private"
        self.service = DesktopService(self.home)
        self.store = ExperienceStore(self.home)
        self.addCleanup(self.store.close)

    def test_preview_shows_only_packed_approved_references_without_inference(self):
        self.store.propose(
            "preference", "I prefer synthetic tangerine soup",
            source="owner:synthetic", approved=True)
        self.store.propose(
            "identity", "PENDING_SYNTHETIC_SECRET tangerine",
            source="synthetic", approved=False)
        self.store.add_decision(
            "Would I pick tangerine soup or juice?", "soup",
            "HELDOUT_SYNTHETIC_SECRET", source="synthetic",
            split="test", options=["soup", "juice"], approved=True)
        self.store.add_message(
            "another-session", "twin", "user",
            "UNREVIEWED_CHAT_SECRET tangerine")
        with patch("athenz.desktop.OllamaClient",
                   side_effect=AssertionError("Local model should never be used")):
            report = self.service.twin_evidence_preview(
                "Do I prefer synthetic tangerine soup?")
        self.assertEqual(report["status"], "approved-topical-evidence-candidate")
        self.assertFalse(report["model_called"])
        self.assertFalse(report["unreviewed_chat_included"])
        self.assertFalse(report["heldout_evaluation_examples_included"])
        payload = json.dumps(report["references"])
        self.assertIn("I prefer synthetic tangerine soup", payload)
        for forbidden in (
            "PENDING_SYNTHETIC_SECRET", "HELDOUT_SYNTHETIC_SECRET",
            "UNREVIEWED_CHAT_SECRET"
        ):
            self.assertNotIn(forbidden, payload)
        self.assertEqual(len(self.store.conversation(
            "another-session", "twin")), 1)

    def test_correction_revocation_and_reopen_change_preview(self):
        memory = self.store.propose(
            "preference", "I prefer synthetic violet robots",
            source="synthetic", approved=True)
        query = "Do I prefer synthetic violet robots?"
        before = self.service.twin_evidence_preview(query)
        self.assertIn("synthetic violet robots",
                      json.dumps(before["references"]))
        detail = self.service.approved_memory_detail(memory)
        self.service.manage_approved_memory(
            memory, "revoke",
            review_sha256=detail["review_sha256"], confirmed=True)
        after = DesktopService(self.home).twin_evidence_preview(query)
        self.assertEqual(after["status"], "insufficient-topical-evidence")
        self.assertNotIn("synthetic violet robots",
                         json.dumps(after["references"]))

    def test_oversized_candidate_does_not_claim_evidence(self):
        self.store.propose(
            "identity", "SYNTHETIC_BIG quantumzebra " + ("x" * 8000),
            source="synthetic", approved=True)
        report = self.service.twin_evidence_preview(
            "What is my quantumzebra background?")
        self.assertEqual(report["status"], "insufficient-topical-evidence")
        self.assertNotIn("SYNTHETIC_BIG", json.dumps(report["references"]))

    def test_invalid_input_refused_before_any_open(self):
        for invalid in ("", "   ", "x" * 4001, None, True):
            with self.subTest(invalid=repr(invalid)[:24]):
                with patch("athenz.desktop.ExperienceStore",
                           side_effect=AssertionError("Opened private storage")):
                    with self.assertRaises(DesktopError):
                        self.service.twin_evidence_preview(invalid)


if __name__ == "__main__":
    unittest.main()
