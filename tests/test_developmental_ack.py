"""Authenticated synthetic ACK requires prior durable receipt and current grant."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import hmac
import json
from pathlib import Path
import struct
import tempfile
import unittest

from athenz.developmental_ack import (
    ACK_SCHEMA, MAX_ACK_BYTES, SyntheticDeliveryAck,
)
from athenz.developmental_bridge import (
    BridgeError, SyntheticBridgeJournal, _canonical, synthetic_event,
)
from athenz.developmental_consent import SyntheticSourceRegistry
from athenz.developmental_exchange import SyntheticExchange
from athenz.developmental_frames import SyntheticFrameSession


class DeliveryReceiptTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name) / "profile"
        self.grants = SyntheticSourceRegistry(self.home)
        self.addCleanup(self.grants.close)
        p = self.grants.preview("synthetic:ack", "approve")
        self.grants.review("synthetic:ack", "approve",
                           review_sha256=p["review_sha256"], confirmed=True)
        self.keys = {"athenz": b"a" * 32, "learner": b"l" * 32}
        self.frame_keys = {"athenz": b"f" * 32, "learner": b"g" * 32}
        self.frame_session = SyntheticFrameSession(
            session_id="1" * 32, producer_keys=self.keys,
            frame_keys=self.frame_keys,
            revision_check=self.grants.is_current, enabled=True)
        self.issuer = SyntheticDeliveryAck(self.frame_session, enabled=True)
        self.verifier = SyntheticDeliveryAck(self.frame_session, enabled=True)
        self.journal = SyntheticBridgeJournal(
            self.home / "journal.sqlite3", keys=self.keys,
            consent_check=self.grants.is_current, enabled=True)
        self.addCleanup(self.journal.close)
        self.exchange = SyntheticExchange.from_registry(
            self.home / "outbox.sqlite3", keys=self.keys,
            registry=self.grants, enabled=True)
        self.addCleanup(self.exchange.close)
        common = {"task_id": "ack", "source_ref": "synthetic:ack",
                  "source_revision": 1}
        self.request = synthetic_event(
            **common, producer="athenz", seq=1, kind="observation",
            payload={"signal": "trace_sha256", "value": "a" * 64},
            secret=self.keys["athenz"])
        self.proposal = synthetic_event(
            **common, producer="learner", seq=1, kind="action_proposed",
            payload={"summary": "synthetic proposal only; no system action"},
            secret=self.keys["learner"])
        self.receipt = synthetic_event(
            **common, producer="learner", seq=2, kind="evaluation_receipt",
            payload={"result": "independently replayed 4 simulator events"},
            secret=self.keys["learner"])
        self.exchange.stage_pair(self.request, self.proposal, self.receipt)

    def record(self, *events):
        for event in events:
            self.assertEqual(self.journal.receive(event)["status"], "accepted")

    def sign(self, item):
        unsigned = {k: v for k, v in item.items() if k != "signature"}
        item["signature"] = hmac.new(
            self.frame_keys["athenz"], _canonical(unsigned),
            hashlib.sha256).hexdigest()
        return item

    def test_requires_metadata_durable_commit_before_ack(self):
        with self.assertRaisesRegex(BridgeError, "durably"):
            self.issuer.issue(self.proposal, self.journal)
        self.assertEqual(self.exchange.pending(), [self.proposal, self.receipt])

    def test_hmac_bound_receipt_changes_only_one_outbox_message(self):
        self.record(self.proposal)
        ack = self.issuer.issue(self.proposal, self.journal)
        self.assertEqual(ack["schema"], ACK_SCHEMA)
        self.assertEqual(ack["receiver"], "athenz")
        self.assertEqual(ack["envelope_sha256"],
                         hashlib.sha256(_canonical(self.proposal)).hexdigest())
        self.assertEqual(self.verifier.accept(ack, self.exchange)["status"], "acked")
        self.assertEqual(self.exchange.pending(), [self.receipt])
        with self.assertRaisesRegex(BridgeError, "Replayed"):
            self.verifier.accept(ack, self.exchange)

    def test_two_acknowledgments_in_order_and_bounded(self):
        self.record(self.proposal, self.receipt)
        a = self.issuer.issue(self.proposal, self.journal)
        b = self.issuer.issue(self.receipt, self.journal)
        with self.assertRaisesRegex(BridgeError, "Replayed"):
            self.verifier.accept(b, self.exchange)
        self.assertEqual(self.verifier.accept(a, self.exchange)["status"], "acked")
        self.assertEqual(self.verifier.accept(b, self.exchange)["status"], "acked")
        self.assertEqual(self.exchange.pending(), [])

    def test_receipt_does_not_ack_conflicting_or_uncommitted_payload(self):
        self.record(self.proposal)
        ack = self.issuer.issue(self.proposal, self.journal)
        for field, value in (("envelope_sha256", "f" * 64),
                             ("event_id", "f" * 32),
                             ("source_revision", 2),
                             ("source_ref", "synthetic:other")):
            changed = self.sign({**ack, field: value})
            with self.subTest(field=field):
                with self.assertRaises(BridgeError):
                    self.verifier.accept(changed, self.exchange)
        self.assertEqual(self.exchange.pending(), [self.proposal, self.receipt])

    def test_unknown_fields_and_tampering_rejected(self):
        self.record(self.proposal)
        ack = self.issuer.issue(self.proposal, self.journal)
        for changed in (
            {**ack, "execute": True},
            {**ack, "signature": "0" * 64},
            {**ack, "receiver": "learner"},
            {**ack, "sequence": True},
            {**ack, "session_id": "2" * 32},
            {**ack, "schema": "unsupported"},
        ):
            with self.assertRaises(BridgeError):
                self.verifier.accept(changed, self.exchange)

    def test_revocation_denies_signed_receipt_even_after_original_commit(self):
        self.record(self.proposal)
        ack = self.issuer.issue(self.proposal, self.journal)
        p = self.grants.preview("synthetic:ack", "revoke")
        self.grants.review("synthetic:ack", "revoke",
                           review_sha256=p["review_sha256"], confirmed=True)
        with self.assertRaisesRegex(BridgeError, "approval"):
            self.verifier.accept(ack, self.exchange)

    def test_wrong_frame_key_rejected(self):
        self.record(self.proposal)
        ack = self.issuer.issue(self.proposal, self.journal)
        other = SyntheticFrameSession(
            session_id="1" * 32, producer_keys=self.keys,
            frame_keys={"athenz": b"x" * 32, "learner": b"g" * 32},
            revision_check=self.grants.is_current, enabled=True)
        with self.assertRaisesRegex(BridgeError, "authentication"):
            SyntheticDeliveryAck(other, enabled=True).accept(ack, self.exchange)

    def test_binary_send_and_receive_authenticated_ack(self):
        self.record(self.proposal)
        stream = BytesIO()
        ack = self.issuer.send(stream, self.proposal, self.journal)
        self.assertLessEqual(len(stream.getvalue()), MAX_ACK_BYTES + 2)
        stream.seek(0)
        self.assertEqual(self.verifier.receive(stream, self.exchange)["status"], "acked")
        self.assertEqual(ack["sequence"], 1)

    def test_malformed_short_noncanonical_and_oversized_ack_frames(self):
        for raw in (b"", b"\\x00",
                    struct.pack("!H", MAX_ACK_BYTES + 1),
                    b"\\x00\\x0b{\\x22n\\x22: true}",
                    struct.pack("!H", 2) + b"[]"):
            with self.subTest(raw=raw[:8]):
                with self.assertRaises(BridgeError):
                    self.verifier.receive(BytesIO(raw), self.exchange)

    def test_stale_signed_receipt_rejected(self):
        self.record(self.proposal)
        ack = self.issuer.issue(self.proposal, self.journal)
        ack["created_at"] = (datetime.now(timezone.utc) -
                             timedelta(hours=1)).isoformat()
        with self.assertRaisesRegex(BridgeError, "timestamp"):
            self.verifier.accept(self.sign(ack), self.exchange)

    def test_short_wire_write_permanently_poison_ack_sender(self):
        self.record(self.proposal)
        class PartialStream:
            def write(self, payload):
                return len(payload) - 1
        with self.assertRaisesRegex(BridgeError, "Short"):
            self.issuer.send(PartialStream(), self.proposal, self.journal)
        with self.assertRaisesRegex(BridgeError, "new session"):
            self.issuer.issue(self.proposal, self.journal)
        self.assertEqual(self.exchange.pending(), [self.proposal, self.receipt])

    def test_flush_failure_poison_ack_sender(self):
        self.record(self.proposal)
        class BrokenFlush:
            def write(self, payload):
                return len(payload)
            def flush(self):
                raise OSError("private details omitted")
        with self.assertRaisesRegex(BridgeError, "flush failed") as raised:
            self.issuer.send(BrokenFlush(), self.proposal, self.journal)
        self.assertNotIn("private details", str(raised.exception))
        with self.assertRaisesRegex(BridgeError, "new session"):
            self.issuer.issue(self.proposal, self.journal)

    def test_disabled_or_wrong_producer_cannot_issue_receipt(self):
        with self.assertRaisesRegex(BridgeError, "disabled"):
            SyntheticDeliveryAck(self.frame_session).issue(self.proposal, self.journal)
        self.record(self.proposal)
        with self.assertRaisesRegex(BridgeError, "learner"):
            self.issuer.issue(self.request, self.journal)

    def test_no_shell_or_human_payload_recorded(self):
        self.record(self.proposal)
        ack = self.issuer.issue(self.proposal, self.journal)
        self.assertNotIn("payload", ack)
        self.assertNotIn("command", ack)
        self.assertNotIn(self.proposal["payload"]["summary"], str(ack))


if __name__ == "__main__":
    unittest.main()
