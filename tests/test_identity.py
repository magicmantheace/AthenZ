import tempfile
import unittest
from pathlib import Path

from athenz.store import IdentityStore
from athenz.cli import main


class IdentityStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "private"
        self.store = IdentityStore(self.home)
        self.addCleanup(self.store.close)

    def test_approval_gates_context_and_revisions(self):
        mid = self.store.propose("preference", "Keep tests fast", source="owner:interview", source_ref="q1")
        self.assertEqual(self.store.context()["identity"], [])
        self.assertTrue(self.store.status(mid, "approved"))
        self.assertEqual(len(self.store.context()["identity"]), 1)
        self.assertTrue(self.store.revise(mid, "Keep tests thorough", "owner correction"))
        self.assertEqual(self.store.context()["identity"], [])
        self.assertEqual(self.store.list_items("identity_revisions")[0]["prior_text"], "Keep tests fast")
        self.assertTrue(self.store.status(mid, "approved"))
        self.assertEqual(self.store.context()["identity"][0]["text"], "Keep tests thorough")

    def test_provenance_deletion_and_purge(self):
        a = self.store.propose("identity", "From export", source="import", source_ref="file-1")
        b = self.store.propose("identity", "From other export", source="import", source_ref="file-2")
        self.store.revise(a, "Corrected export", "fix")
        self.store.add_decision("Which?", "A", "Because", source="import", source_ref="file-1")
        self.store.add_sample("My style", source="import", source_ref="file-1")
        self.assertEqual(self.store.purge_source("import", "file-1"), {"identity": 1, "decisions": 1, "writing_samples": 1, "episodes": 0})
        self.assertEqual(len(self.store.list_items("identity_revisions")), 0)
        self.assertEqual(self.store.list_items("identity")[0]["id"], b)
        self.assertNotIn("From export", str(self.store.export()))

    def test_decisions_pending_until_approved(self):
        did = self.store.add_decision("Ship or test?", "Test", "Quality", source="owner")
        self.assertEqual(self.store.context()["decisions"], [])
        self.assertTrue(self.store.decision_status(did, "approved"))
        self.assertEqual(len(self.store.context()["decisions"]), 1)

    def test_invalid_entries_and_sql_injection_guard(self):
        for kind in ("unknown", "identity; DROP TABLE identity"):
            with self.assertRaises(ValueError):
                self.store.propose(kind, "content", source="owner")
        with self.assertRaises(ValueError):
            self.store.list_items("identity; DROP TABLE identity")
        with self.assertRaises(ValueError):
            self.store.propose("style", "content", source="owner", confidence=2)
        with self.assertRaises(ValueError):
            self.store.revise(123, "", "reason")

    def test_survives_restart_and_schema_version(self):
        did = self.store.add_decision("Scenario", "Choice", "Reason", source="owner")
        self.store.decision_status(did, "approved")
        reopened = IdentityStore(self.home)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.context()["decisions"][0]["choice"], "Choice")
        self.assertEqual(reopened.db.execute("PRAGMA user_version").fetchone()[0], 6)

    def test_cli_smoke(self):
        main(["--home", str(self.home), "init"])
        main(["--home", str(self.home), "propose", "value", "I value evidence"])
        self.assertEqual(len(self.store.list_items("identity")), 1)


if __name__ == "__main__":
    unittest.main()
