"""Synthetic regression checks for the non-executing D2 bridge contract."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import tempfile
import unittest

from athenz.developmental_bridge import (
    BridgeError, SyntheticBridgeJournal, synthetic_event, _validate,
)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "synthetic-bridge.sqlite3"
        self.keys = {"athenz": b"a" * 32, "learner": b"l" * 32}
        self.revision = {"synthetic:task": 1}
        self.open_journal()

    def open_journal(self, *, enabled=True):
        self.journal = SyntheticBridgeJournal(
            self.path, keys=self.keys,
            consent_check=lambda source, rev: self.revision.get(source) == rev,
            enabled=enabled)
        self.addCleanup(self.journal.close)

    def make(self, producer, seq, kind, payload, **updates):
        data = dict(producer=producer, task_id="task", seq=seq, kind=kind,
                    source_ref="synthetic:task", source_revision=1,
                    payload=payload, secret=self.keys[producer])
        data.update(updates)
        return synthetic_event(**data)

    def resign(self, obj):
        obj["signature"] = hmac.new(
            self.keys[obj["producer"]],
            json.dumps({k: v for k, v in obj.items() if k != "signature"},
                       sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False).encode(),
            hashlib.sha256).hexdigest()
        return obj

    def test_roundtrip_with_separate_timelines_and_no_execution(self):
        events = [
            self.make("athenz", 1, "observation", {"signal": "position", "value": "0"}),
            self.make("learner", 1, "action_proposed", {"summary": "move right"}),
            self.make("athenz", 2, "outcome", {"accepted": True, "result": "simulated"}),
            self.make("learner", 2, "evaluation_receipt", {"result": "candidate-only"}),
        ]
        for event in events:
            self.assertEqual(self.journal.receive(event),
                             {"status": "accepted", "actions_executed": False})
        rows = self.journal.db.execute(
            "SELECT producer,task_id,seq FROM bridge_events ORDER BY rowid").fetchall()
        self.assertEqual(rows, [
            ("athenz", "task", 1), ("learner", "task", 1),
            ("athenz", "task", 2), ("learner", "task", 2)])
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM bridge_events").fetchone()[0], 4)

    def test_duplicate_is_safe_after_reopening(self):
        first = self.make("athenz", 1, "observation", {"signal": "x", "value": "1"})
        self.journal.receive(first)
        self.journal.close()
        self.open_journal()
        self.assertEqual(self.journal.receive(first)["status"], "duplicate")
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM bridge_events").fetchone()[0], 1)

    def test_reordered_missing_and_same_seq_conflicting_are_rejected(self):
        late = self.make("athenz", 2, "observation", {"signal": "x", "value": "1"})
        with self.assertRaisesRegex(BridgeError, "sequence"):
            self.journal.receive(late)
        self.journal.receive(self.make(
            "athenz", 1, "observation", {"signal": "x", "value": "0"}))
        with self.assertRaisesRegex(BridgeError, "sequence"):
            self.journal.receive(self.make(
                "athenz", 1, "observation", {"signal": "x", "value": "different"}))
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM bridge_events").fetchone()[0], 1)

    def test_payload_tampering_rejected_before_journal_write(self):
        event = self.make("learner", 1, "goal_proposed", {"summary": "test"})
        event["payload"]["summary"] = "changed"
        with self.assertRaisesRegex(BridgeError, "authentication"):
            self.journal.receive(event)
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM bridge_events").fetchone()[0], 0)

    def test_forged_human_origin_from_learner_rejected_even_if_signed(self):
        event = self.make("learner", 1, "goal_proposed", {"summary": "test"})
        event["origin"] = "human_record"
        self.resign(event)
        with self.assertRaisesRegex(BridgeError, "origin"):
            self.journal.receive(event)
        event["kind"] = "outcome"
        event["payload"] = {"accepted": True, "result": "bad"}
        self.resign(event)
        with self.assertRaisesRegex(BridgeError, "origin"):
            self.journal.receive(event)

    def test_scope_cannot_be_escalated_by_authenticated_peer(self):
        event = self.make("learner", 1, "action_proposed", {"summary": "run program"})
        event["scope"] = "execute_any_command"
        self.resign(event)
        with self.assertRaisesRegex(BridgeError, "scope"):
            self.journal.receive(event)

    def test_unknown_authority_field_and_payload_field_rejected(self):
        event = self.make("learner", 1, "action_proposed", {"summary": "test"})
        event["system_access"] = True
        self.resign(event)
        with self.assertRaisesRegex(BridgeError, "envelope"):
            self.journal.receive(event)
        del event["system_access"]
        event["payload"]["command"] = "sh"
        self.resign(event)
        with self.assertRaisesRegex(BridgeError, "payload"):
            self.journal.receive(event)

    def test_unapproved_or_changed_source_fails_closed(self):
        self.revision["synthetic:task"] = 2
        with self.assertRaisesRegex(BridgeError, "approval"):
            self.journal.receive(self.make(
                "athenz", 1, "observation", {"signal": "x", "value": "0"}))
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM bridge_events").fetchone()[0], 0)

    def test_revocation_invalidates_stream_and_persists_after_reopen(self):
        accepted = self.make("athenz", 1, "observation", {"signal": "x", "value": "0"})
        self.journal.receive(accepted)
        self.journal.receive(self.make("athenz", 2, "revocation", {"reason": "withdrawn"}))
        with self.assertRaisesRegex(BridgeError, "revoked"):
            self.journal.receive(self.make(
                "learner", 1, "action_proposed", {"summary": "test"}))
        self.journal.close()
        self.open_journal()
        with self.assertRaisesRegex(BridgeError, "revoked"):
            self.journal.receive(accepted)
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM bridge_events").fetchone()[0], 2)

    def test_disabled_mode_does_not_record_messages(self):
        self.journal.enabled = False
        self.assertEqual(self.journal.receive({"untrusted": True})["status"], "disabled")
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM bridge_events").fetchone()[0], 0)

    def test_expired_and_future_messages_refused(self):
        for delta in (-301, 301):
            with self.subTest(delta=delta):
                event = self.make(
                    "athenz", 1, "observation", {"signal": "x", "value": "0"},
                    created_at=(datetime.now(timezone.utc) +
                                timedelta(seconds=delta)).isoformat(timespec="seconds"))
                with self.assertRaisesRegex(BridgeError, "timestamp"):
                    self.journal.receive(event)

    def test_bounded_payload_and_type_enforcement(self):
        for payload in (
            {"summary": "x" * 161},
            {"summary": "multi\nline"},
            {"summary": False},
            {"summary": ["not", "text"]},
        ):
            with self.subTest(payload=payload):
                event = self.make("learner", 1, "goal_proposed", payload)
                with self.assertRaises(BridgeError):
                    self.journal.receive(event)
        event = self.make("athenz", True, "observation", {"signal": "x", "value": "0"})
        with self.assertRaisesRegex(BridgeError, "sequence"):
            self.journal.receive(event)

    def test_missing_secrets_or_consent_callback_fail_closed(self):
        with self.assertRaisesRegex(BridgeError, "secrets"):
            SyntheticBridgeJournal(self.path, keys={"athenz": b"x" * 32},
                                   consent_check=lambda s, r: True)
        with self.assertRaisesRegex(BridgeError, "secrets"):
            SyntheticBridgeJournal(self.path, keys=self.keys, consent_check=None)

    def test_original_event_not_mutated_and_no_payload_persisted(self):
        event = self.make("learner", 1, "checkpoint", {"checkpoint_id": "step-one"})
        original = deepcopy(event)
        self.journal.receive(event)
        self.assertEqual(event, original)
        db = self.path.read_bytes()
        self.assertNotIn(b"step-one", db)
        self.assertNotIn(b"candidate-only", db)


if __name__ == "__main__":
    unittest.main()
