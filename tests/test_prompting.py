import tempfile
import unittest
from pathlib import Path
from athenz.store import IdentityStore
from athenz.prompting import build_messages


class PromptTests(unittest.TestCase):
    def test_modes_keep_approval_boundary(self):
        with tempfile.TemporaryDirectory() as dirname:
            store = IdentityStore(Path(dirname))
            try:
                store.propose("identity", "UNAPPROVED PRIVATE INFERENCE", source="model")
                store.propose("preference", "Make reviewable patches", source="owner", approved=True)
                did = store.add_decision("Fast or tested?", "Tested", "Reliability", source="owner")
                twin = build_messages(store, "How would I approach it?", "twin")
                agent = build_messages(store, "Fix code", "agent")
                self.assertIn("NOT the owner", twin[0]["content"])
                self.assertIn("working FOR", agent[0]["content"])
                self.assertIn("Make reviewable patches", agent[1]["content"])
                self.assertNotIn("UNAPPROVED PRIVATE", str(twin))
                self.assertNotIn("Fast or tested?", str(agent))
                store.decision_status(did, "approved")
                approved = build_messages(store, "Would I favor something fast or tested?")
                self.assertIn("Fast or tested?", approved[1]["content"])
            finally:
                store.close()

    def test_rejects_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as dirname:
            store = IdentityStore(Path(dirname))
            try:
                with self.assertRaises(ValueError):
                    build_messages(store, "question", "admin")
                with self.assertRaises(ValueError):
                    build_messages(store, "   ")
            finally:
                store.close()
