"""Reviewed synthetic source grants and their strict D2 exchange binding."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from athenz.developmental_bridge import BridgeError, synthetic_event
from athenz.developmental_consent import SyntheticSourceRegistry
from athenz.developmental_exchange import SyntheticExchange


class SyntheticApprovalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "profile"
        self.registry = SyntheticSourceRegistry(self.home)
        self.addCleanup(self.registry.close)
        self.keys = {"athenz": b"a" * 32, "learner": b"l" * 32}

    def approve(self, source="synthetic:simulation"):
        preview = self.registry.preview(source, "approve")
        return self.registry.review(source, "approve",
            review_sha256=preview["review_sha256"], confirmed=True)

    def revoke(self, source="synthetic:simulation"):
        preview = self.registry.preview(source, "revoke")
        return self.registry.review(source, "revoke",
            review_sha256=preview["review_sha256"], confirmed=True)

    def make_pair(self, revision=1):
        common = {"task_id": "task", "source_ref": "synthetic:simulation",
                  "source_revision": revision}
        request = synthetic_event(
            **common, producer="athenz", seq=1, kind="observation",
            payload={"signal": "trace_sha256", "value": "a" * 64},
            secret=self.keys["athenz"])
        proposal = synthetic_event(
            **common, producer="learner", seq=1, kind="action_proposed",
            payload={"summary": "synthetic proposal only; no system action"},
            secret=self.keys["learner"])
        receipt = synthetic_event(
            **common, producer="learner", seq=2, kind="evaluation_receipt",
            payload={"result": "independently replayed 4 simulator events"},
            secret=self.keys["learner"])
        return request, proposal, receipt

    def outbox(self, filename="outbox.sqlite3", enabled=True):
        outbox = SyntheticExchange.from_registry(
            self.home / filename, keys=self.keys,
            registry=self.registry, enabled=enabled)
        self.addCleanup(outbox.close)
        return outbox

    def test_denies_by_default_and_never_guesses_user_intent(self):
        self.assertFalse(self.registry.is_current("synthetic:simulation", 1))
        self.assertEqual(self.registry.status("synthetic:simulation")["state"], "absent")
        with self.assertRaisesRegex(BridgeError, "approved"):
            self.outbox().stage_pair(*self.make_pair())

    def test_review_previews_one_exact_source_and_scope(self):
        p = self.registry.preview("synthetic:simulation", "approve")
        self.assertEqual(p["revision"], 1)
        self.assertEqual(p["purpose"], "adaptive_sandbox")
        self.assertEqual(p["scope"], "proposal_only")
        self.assertEqual(len(p["review_sha256"]), 64)
        with self.assertRaisesRegex(BridgeError, "confirmation"):
            self.registry.review("synthetic:simulation", "approve",
                                 review_sha256=p["review_sha256"])
        self.assertFalse(self.registry.is_current("synthetic:simulation", 1))
        info = self.registry.review("synthetic:simulation", "approve",
                                    review_sha256=p["review_sha256"], confirmed=True)
        self.assertEqual(info["state"], "approved")
        self.assertEqual(info["revision"], 1)
        self.assertFalse(info["actions_executed"])
        self.assertTrue(self.registry.is_current("synthetic:simulation", 1))

    def test_cross_source_digest_and_forged_digest_rejected(self):
        p = self.registry.preview("synthetic:simulation", "approve")
        for source, digest in (("synthetic:other", p["review_sha256"]),
                               ("synthetic:simulation", "f" * 64)):
            with self.subTest(source=source):
                with self.assertRaisesRegex(BridgeError, "changed"):
                    self.registry.review(source, "approve",
                                         review_sha256=digest, confirmed=True)
        self.assertFalse(self.registry.is_current("synthetic:simulation", 1))

    def test_no_double_approval_without_explicit_revocation(self):
        self.approve()
        with self.assertRaisesRegex(BridgeError, "Revoke"):
            self.registry.preview("synthetic:simulation", "approve")
        self.assertFalse(self.registry.is_current("synthetic:simulation", 2))

    def test_source_revocation_advances_revision_and_fences_outbox(self):
        self.approve()
        outbox = self.outbox()
        self.assertEqual(outbox.stage_pair(*self.make_pair())["status"], "staged")
        self.assertEqual(len(outbox.pending()), 2)
        revoked = self.revoke()
        self.assertEqual(revoked["revision"], 2)
        self.assertEqual(revoked["state"], "revoked")
        self.assertFalse(self.registry.is_current("synthetic:simulation", 1))
        self.assertFalse(self.registry.is_current("synthetic:simulation", 2))
        with self.assertRaisesRegex(BridgeError, "approved"):
            outbox.pending()
        with self.assertRaisesRegex(BridgeError, "approved"):
            outbox.stage_pair(*self.make_pair())
        self.assertEqual(outbox.db.execute(
            "SELECT COUNT(*) FROM d2_outbox").fetchone()[0], 2)

    def test_reapproval_never_resurrects_old_signed_replies(self):
        self.approve()
        outbox = self.outbox()
        outbox.stage_pair(*self.make_pair())
        self.revoke()
        p = self.registry.preview("synthetic:simulation", "approve")
        self.assertEqual(p["revision"], 3)
        self.registry.review("synthetic:simulation", "approve",
                             review_sha256=p["review_sha256"], confirmed=True)
        self.assertTrue(self.registry.is_current("synthetic:simulation", 3))
        self.assertFalse(self.registry.is_current("synthetic:simulation", 1))
        with self.assertRaisesRegex(BridgeError, "approved"):
            outbox.pending()

    def test_stale_preview_fails_after_revision_changed_elsewhere(self):
        p = self.registry.preview("synthetic:simulation", "approve")
        with SyntheticSourceRegistry(self.home) as second:
            applied = second.review("synthetic:simulation", "approve",
                                    review_sha256=p["review_sha256"], confirmed=True)
            self.assertEqual(applied["revision"], 1)
        with self.assertRaises(BridgeError):
            self.registry.review("synthetic:simulation", "approve",
                                 review_sha256=p["review_sha256"], confirmed=True)

    def test_registry_is_persistent_after_close_and_reopen(self):
        self.approve()
        self.revoke()
        with SyntheticSourceRegistry(self.home) as second:
            self.assertEqual(second.status("synthetic:simulation")["revision"], 2)
            self.assertEqual(second.status("synthetic:simulation")["state"], "revoked")
            self.assertFalse(second.is_current("synthetic:simulation", 1))

    def test_exclusive_synthetic_source_namespace(self):
        for source in ("", "owner:name", "person", "../private", "synthetic:../../bad",
                       "synthetic:UPPER SPACE", "synthetic:" + "x" * 65):
            with self.subTest(source=source):
                with self.assertRaises(BridgeError):
                    self.registry.preview(source, "approve")
                self.assertFalse(self.registry.is_current(source, 1))
        self.assertFalse(self.registry.is_current("synthetic:simulation", True))
        self.assertFalse(self.registry.is_current("synthetic:simulation", 0))

    def test_wrong_state_operation_rejected(self):
        with self.assertRaisesRegex(BridgeError, "approved"):
            self.registry.preview("synthetic:simulation", "revoke")
        with self.assertRaises(BridgeError):
            self.registry.preview("synthetic:simulation", "execute")
        with self.assertRaises(BridgeError):
            self.registry.review("synthetic:simulation", "approve",
                                 review_sha256="a" * 64, confirmed=1)

    def test_wrong_home_for_outbox_rejected(self):
        other = self.home.parent / "another"
        other.mkdir()
        with self.assertRaisesRegex(BridgeError, "same private home"):
            SyntheticExchange.from_registry(other / "outbox.sqlite3",
                                            keys=self.keys, registry=self.registry,
                                            enabled=True)
        with self.assertRaisesRegex(BridgeError, "registry"):
            SyntheticExchange.from_registry(self.home / "outbox.sqlite3",
                                            keys=self.keys, registry=object(),
                                            enabled=True)

    def test_readable_owner_local_file_permissions_posix(self):
        if os.name == "nt":
            self.skipTest("POSIX mode bits are not Windows ACLs")
        self.assertEqual(self.home.stat().st_mode & 0o077, 0)
        self.assertEqual(self.registry.path.stat().st_mode & 0o077, 0)

    def test_no_synthetic_database_inside_git_checkout(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t) / "repo"
            root.mkdir()
            (root / ".git").mkdir()
            with self.assertRaisesRegex(BridgeError, "outside-Git"):
                SyntheticSourceRegistry(root / "profile")
            with self.assertRaisesRegex(BridgeError, "outside-Git"):
                SyntheticExchange(root / "queue.sqlite3", keys=self.keys,
                                  revision_check=lambda *args: True, enabled=True)

    def test_cross_database_missing_or_closed_registry_denies(self):
        self.approve()
        outbox = self.outbox()
        self.registry.close()
        with self.assertRaisesRegex(BridgeError, "no longer approved"):
            outbox.stage_pair(*self.make_pair())

    def test_disabled_registry_bound_exchange_does_not_stage(self):
        self.approve()
        outbox = self.outbox(enabled=False)
        self.assertEqual(outbox.stage_pair(*self.make_pair())["status"], "disabled")
        self.assertEqual(outbox.pending(), [])
        self.assertEqual(outbox.db.execute(
            "SELECT COUNT(*) FROM d2_ingress").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
