"""Cross-repository frozen synthetic D2 event contract compatibility tests."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import unittest
from copy import deepcopy

from athenz.developmental_bridge import _validate, BridgeError

VECTOR = Path(__file__).parent / "fixtures" / "d2_synthetic_vector.json"
FIXED_NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class D2WireCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.vector = json.loads(VECTOR.read_text("utf-8"))
        self.event = self.vector["event"]
        self.keys = {"athenz": b"a" * 32, "learner": b"l" * 32}

    def test_golden_authenticated_wire_vector_is_stable(self):
        self.assertEqual(self.vector["schema"], "athenz.d2.synthetic-vector/v1")
        body = _validate(self.event, self.keys, now=FIXED_NOW)
        self.assertEqual(hashlib.sha256(body).hexdigest(), self.vector["wire_sha256"])
        self.assertEqual(self.event["signature"],
                         "5a6017ab3b8779f55fa39b678fe11e12fb51fc3fb8e1163ae57d7924763fb873")

    def test_opposite_learner_secret_or_different_canonical_payload_fails(self):
        wrong = {"athenz": b"x" * 32, "learner": b"l" * 32}
        with self.assertRaisesRegex(BridgeError, "authentication"):
            _validate(self.event, wrong, now=FIXED_NOW)
        for changes in (
            {"scope": "execute_any_command"},
            {"origin": "simulation_episode"},
            {"seq": 2},
        ):
            with self.subTest(changes=changes):
                event = deepcopy(self.event)
                event.update(changes)
                with self.assertRaises(BridgeError):
                    _validate(event, self.keys, now=FIXED_NOW)

    def test_vector_never_becomes_a_real_permission(self):
        self.assertEqual(self.event["namespace"], "sandbox")
        self.assertEqual(self.event["purpose"], "adaptive_sandbox")
        self.assertEqual(self.event["scope"], "proposal_only")
        self.assertTrue(self.event["source_ref"].startswith("synthetic:"))


if __name__ == "__main__":
    unittest.main()
