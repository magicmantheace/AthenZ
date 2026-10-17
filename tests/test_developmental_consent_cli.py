"""CLI regression: no implicit consent, preview binding and durable revocation."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from athenz.developmental_consent_cli import main
from athenz.developmental_consent import SyntheticSourceRegistry


class D2ReviewCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / "private"
        self.base = ["--home", str(self.home)]
        self.source = "synthetic:trial"

    def cmd(self, *args):
        buffer = StringIO()
        with redirect_stdout(buffer):
            result = main([*self.base, *args])
        self.assertEqual(result, 0)
        return json.loads(buffer.getvalue())

    def rejects(self, *args):
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main([*self.base, *args])
        self.assertEqual(raised.exception.code, 2)

    def test_status_is_absent_and_no_human_memory_db_is_created(self):
        item = self.cmd("status", self.source)
        self.assertEqual(item["state"], "absent")
        self.assertEqual(item["revision"], 0)
        self.assertFalse((self.home / "identity.sqlite3").exists())
        self.assertTrue((self.home / "d2_synthetic_grants.sqlite3").exists())

    def test_preview_never_autoapproves_even_when_repeated(self):
        first = self.cmd("preview", self.source, "approve")
        second = self.cmd("preview", self.source, "approve")
        self.assertEqual(first, second)
        self.assertEqual(self.cmd("status", self.source)["state"], "absent")

    def test_review_requires_digest_and_explicit_confirmation(self):
        item = self.cmd("preview", self.source, "approve")
        self.rejects("review", self.source, "approve",
                     "--review-sha256", item["review_sha256"])
        self.rejects("review", self.source, "approve",
                     "--review-sha256", "0" * 64, "--confirm")
        self.assertEqual(self.cmd("status", self.source)["state"], "absent")
        granted = self.cmd("review", self.source, "approve",
                           "--review-sha256", item["review_sha256"], "--confirm")
        self.assertEqual(granted["state"], "approved")
        self.assertEqual(granted["revision"], 1)
        self.assertFalse(granted["actions_executed"])

    def test_revocation_is_reviewed_and_persistent(self):
        p = self.cmd("preview", self.source, "approve")
        self.cmd("review", self.source, "approve",
                 "--review-sha256", p["review_sha256"], "--confirm")
        revoke = self.cmd("preview", self.source, "revoke")
        self.rejects("review", self.source, "revoke",
                     "--review-sha256", revoke["review_sha256"])
        self.assertEqual(self.cmd("status", self.source)["state"], "approved")
        self.cmd("review", self.source, "revoke",
                 "--review-sha256", revoke["review_sha256"], "--confirm")
        self.assertEqual(self.cmd("status", self.source)["revision"], 2)
        with SyntheticSourceRegistry(self.home) as registry:
            self.assertFalse(registry.is_current(self.source, 1))
            self.assertFalse(registry.is_current(self.source, 2))

    def test_reapproval_increments_revision_and_denies_old(self):
        p = self.cmd("preview", self.source, "approve")
        self.cmd("review", self.source, "approve",
                 "--review-sha256", p["review_sha256"], "--confirm")
        p = self.cmd("preview", self.source, "revoke")
        self.cmd("review", self.source, "revoke",
                 "--review-sha256", p["review_sha256"], "--confirm")
        p = self.cmd("preview", self.source, "approve")
        self.assertEqual(p["revision"], 3)
        self.cmd("review", self.source, "approve",
                 "--review-sha256", p["review_sha256"], "--confirm")
        with SyntheticSourceRegistry(self.home) as registry:
            self.assertTrue(registry.is_current(self.source, 3))
            self.assertFalse(registry.is_current(self.source, 1))

    def test_unknown_non_synthetic_source_rejected(self):
        self.rejects("status", "real:owner")
        self.rejects("preview", "../profile", "approve")
        self.rejects("preview", self.source, "execute")

    def test_source_status_and_review_do_not_touch_owner_data(self):
        self.cmd("preview", self.source, "approve")
        self.assertEqual(list(self.home.glob("*")), [
            self.home / "d2_synthetic_grants.sqlite3"
        ])
        self.assertEqual(self.cmd("status", self.source)["scope"], "proposal_only")


if __name__ == "__main__":
    unittest.main()
