"""Durable synthetic D2 receiver across reconnects and signed ACK integration."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import os
from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest import mock

from athenz.developmental_ack import SyntheticDeliveryAck
from athenz.developmental_bridge import BridgeError, synthetic_event
from athenz.developmental_consent import SyntheticSourceRegistry
from athenz.developmental_exchange import SyntheticExchange
from athenz.developmental_frames import SyntheticFrameSession
from athenz.developmental_receiver import SyntheticDurableReceiver
import athenz.developmental_receiver as receiver_module


class DurableFrameTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.home = Path(folder.name) / "private"
        self.grants = SyntheticSourceRegistry(self.home)
        self.addCleanup(self.grants.close)
        self.keys = {"athenz": b"a" * 32, "learner": b"l" * 32}
        self.frame_keys = {"athenz": b"f" * 32, "learner": b"g" * 32}
        self.source = "synthetic:durable"
        self._approve()
        self.path = self.home / "received.sqlite3"
        self.journal = self.open_journal()

    def _approve(self):
        preview = self.grants.preview(self.source, "approve")
        self.grants.review(self.source, "approve",
                           review_sha256=preview["review_sha256"], confirmed=True)

    def open_journal(self, enabled=True):
        receiver = SyntheticDurableReceiver(
            self.path, keys=self.keys, revision_check=self.grants.is_current,
            enabled=enabled)
        self.addCleanup(receiver.close)
        return receiver

    def sessions(self, sid="3" * 32):
        opts = dict(session_id=sid, producer_keys=self.keys,
                    frame_keys=self.frame_keys,
                    revision_check=self.grants.is_current, enabled=True)
        return SyntheticFrameSession(**opts), SyntheticFrameSession(**opts)

    def event(self, seq=1, kind="action_proposed", *, created_at=None,
              payload=None, producer="learner", task_id="durable"):
        if payload is None:
            payload = (
                {"summary": "synthetic proposal only; no system action"}
                if kind == "action_proposed"
                else {"result": "independently replayed 4 simulator events"}
                if kind == "evaluation_receipt"
                else {"signal": "trace_sha256", "value": "a" * 64})
        return synthetic_event(
            producer=producer, task_id=task_id, seq=seq,
            kind=kind, source_ref=self.source, source_revision=1,
            payload=payload, secret=self.keys[producer],
            created_at=created_at)

    def deliver(self, event, *, sid="3" * 32, journal=None, expected="learner"):
        sender, receiver = self.sessions(sid)
        packet = sender.pack(event)
        return (journal or self.journal).receive_frame(
            receiver, BytesIO(packet), expected_producer=expected)

    def test_expired_inner_envelope_delivered_inside_fresh_frame(self):
        old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        message = self.event(created_at=old)
        self.assertEqual(self.deliver(message)["status"], "accepted")
        self.assertEqual(self.journal.recorded_fingerprint(message),
                         hashlib.sha256(self.keys_to_canonical(message)).hexdigest())
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM d2_framed_received").fetchone()[0], 1)

    @staticmethod
    def keys_to_canonical(event):
        from athenz.developmental_bridge import _canonical
        return _canonical(event)

    def test_duplicate_after_restart_and_new_session_is_idempotent(self):
        event = self.event()
        self.deliver(event)
        self.journal.close()
        self.journal = self.open_journal()
        self.assertEqual(self.deliver(event, sid="4" * 32)["status"], "duplicate")
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM d2_framed_received").fetchone()[0], 1)

    def test_skipped_and_conflicting_producer_sequences_fail_closed(self):
        later = self.event(seq=2)
        with self.assertRaisesRegex(BridgeError, "sequence"):
            self.deliver(later)
        self.deliver(self.event())
        different = self.event(kind="evaluation_receipt", seq=1)
        with self.assertRaisesRegex(BridgeError, "sequence"):
            self.deliver(different, sid="5" * 32)
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM d2_framed_received").fetchone()[0], 1)

    def test_two_messages_replayed_in_new_session_without_count_growth(self):
        p = self.event(seq=1)
        r = self.event(seq=2, kind="evaluation_receipt")
        self.deliver(p)
        self.deliver(r, sid="4" * 32)
        self.assertEqual(self.deliver(p, sid="5" * 32)["status"], "duplicate")
        self.assertEqual(self.deliver(r, sid="6" * 32)["status"], "duplicate")
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM d2_framed_received").fetchone()[0], 2)

    def test_revocation_invalidates_pending_old_envelopes(self):
        event = self.event()
        self.deliver(event)
        p = self.grants.preview(self.source, "revoke")
        self.grants.review(self.source, "revoke",
                           review_sha256=p["review_sha256"], confirmed=True)
        with self.assertRaises(BridgeError):
            self.deliver(event, sid="7" * 32)
        with self.assertRaisesRegex(BridgeError, "approved"):
            self.journal.recorded_fingerprint(event)

    def test_durable_frame_receipt_enables_signed_ack_after_old_timestamp(self):
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        proposal = self.event(created_at=old, task_id="previous")
        self.deliver(proposal)
        request = self.event(producer="athenz",kind="observation",task_id="durable")
        receipt = self.event(seq=2,kind="evaluation_receipt")
        with SyntheticExchange.from_registry(
            self.home / "outbox.sqlite3", keys=self.keys,
            registry=self.grants, enabled=True) as exchange:
            # Outbox requires currently fresh signatures at *staging*. The
            # old signed message is a persisted retransmission only.
            fresh = self.event()
            self.assertEqual(exchange.stage_pair(request, fresh, receipt)["status"], "staged")
            self.assertNotEqual(proposal["event_id"], fresh["event_id"])
            with self.assertRaisesRegex(BridgeError, "durably"):
                SyntheticDeliveryAck(self.sessions()[1], enabled=True).issue(
                    fresh, self.journal)
            self.assertEqual(self.deliver(fresh, sid="8" * 32)["status"], "accepted")
            issuer = SyntheticDeliveryAck(self.sessions()[1], enabled=True)
            verifier = SyntheticDeliveryAck(self.sessions()[0], enabled=True)
            signed_ack = issuer.issue(fresh, self.journal)
            self.assertEqual(verifier.accept(signed_ack, exchange)["status"], "acked")
            self.assertEqual(exchange.pending(), [receipt])

    def test_strict_only_fixed_simulator_reply_payloads(self):
        action = self.event(payload={"summary": "run shell"})
        with self.assertRaisesRegex(BridgeError, "non-executable"):
            self.deliver(action)
        action = self.event(kind="evaluation_receipt",
                            payload={"result": "arbitrary generated text"})
        with self.assertRaisesRegex(BridgeError, "fixed simulator"):
            self.deliver(action, sid="6" * 32)

    def test_tampering_replayed_event_id_fingerprint_is_rejected(self):
        event = self.event()
        self.deliver(event)
        self.journal.db.execute(
            "UPDATE d2_framed_received SET digest=? WHERE event_id=?",
            ("0" * 64, event["event_id"]))
        with self.assertRaisesRegex(BridgeError, "Conflicting"):
            self.deliver(event, sid="7" * 32)
        self.assertIsNone(self.journal.recorded_fingerprint(event))

    def test_rejects_wrong_producer_key_and_forged_frame(self):
        event = self.event()
        sender, receiver = self.sessions()
        other_keys = {"athenz": b"a" * 32, "learner": b"x" * 32}
        other = SyntheticFrameSession(
            session_id="3" * 32, producer_keys=other_keys,
            frame_keys=self.frame_keys,
            revision_check=self.grants.is_current, enabled=True)
        with self.assertRaisesRegex(BridgeError, "differ"):
            self.journal.receive_frame(other, BytesIO(sender.pack(event)))
        bad = bytearray(sender.pack(event))
        bad[-10] ^= 1
        with self.assertRaises(BridgeError):
            self.journal.receive_frame(receiver, BytesIO(bad))
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM d2_framed_received").fetchone()[0], 0)

    def test_cannot_skip_outer_frame_authentication_or_replay_sequence(self):
        self.assertFalse(hasattr(self.journal, "receive"))
        event = self.event()
        sender, receiver = self.sessions()
        packet = sender.pack(event)
        self.journal.receive_frame(receiver, BytesIO(packet))
        with self.assertRaisesRegex(BridgeError, "replayed"):
            self.journal.receive_frame(receiver, BytesIO(packet))

    def test_disabled_and_bad_private_path_denied(self):
        receiver = self.open_journal(enabled=False)
        sender, recv = self.sessions()
        self.assertEqual(receiver.receive_frame(
            recv, BytesIO(sender.pack(self.event())))["status"], "disabled")
        with tempfile.TemporaryDirectory() as t:
            git = Path(t) / "repo"
            git.mkdir()
            (git / ".git").mkdir()
            with self.assertRaisesRegex(BridgeError, "outside Git"):
                SyntheticDurableReceiver(
                    git / "bad.sqlite3", keys=self.keys,
                    revision_check=self.grants.is_current, enabled=True)

    def test_bounded_capacity_and_transaction_rollback(self):
        with mock.patch.object(receiver_module, "MAX_RECEIVED", 1):
            self.deliver(self.event())
            with self.assertRaisesRegex(BridgeError, "capacity"):
                self.deliver(self.event(seq=2,kind="evaluation_receipt"),sid="4"*32)
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM d2_framed_received").fetchone()[0], 1)
        self.assertEqual(self.journal.db.execute(
            "SELECT last_seq FROM d2_framed_stream WHERE producer='learner' "
            "AND task_id='durable'").fetchone()[0], 1)

    def test_rejects_nonprivate_posix_directory(self):
        if os.name == "nt":
            self.skipTest("Windows folder privacy is enforced by ACL, not POSIX bits")
        with tempfile.TemporaryDirectory() as t:
            public_dir = Path(t) / "shared"
            public_dir.mkdir(mode=0o755)
            public_dir.chmod(0o755)
            with self.assertRaisesRegex(BridgeError, "owner-only"):
                SyntheticDurableReceiver(
                    public_dir / "events.sqlite3", keys=self.keys,
                    revision_check=self.grants.is_current, enabled=True)
            self.assertFalse((public_dir / "events.sqlite3").exists())

    def test_receiver_database_is_owner_only_on_posix(self):
        if os.name == "nt":
            self.skipTest("Windows ACL validation is not available")
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)

    def test_request_mismatch_rejected_before_durable_journal_write(self):
        for bad in (self.event(kind="evaluation_receipt"),
                    self.event(task_id="different")):
            with self.subTest(kind=bad["kind"], task=bad["task_id"]):
                sender, receiver = self.sessions("8" * 32)
                packet = sender.pack(bad)
                with self.assertRaisesRegex(BridgeError, "expected request"):
                    self.journal.receive_frame(
                        receiver, BytesIO(packet), expected_producer="learner",
                        expected_task_id="durable",
                        expected_kind="action_proposed",
                        expected_source_ref=self.source,
                        expected_source_revision=1)
                self.assertEqual(self.journal.db.execute(
                    "SELECT count(*) FROM d2_framed_received").fetchone()[0], 0)
        self.assertEqual(self.deliver(self.event(), sid="9" * 32)["status"],
                         "accepted")

    def test_expected_revision_rejected_before_durable_journal_write(self):
        sender, receiver = self.sessions("8" * 32)
        stream = BytesIO(sender.pack(self.event()))
        with self.assertRaisesRegex(BridgeError, "expected request"):
            self.journal.receive_frame(
                receiver, stream, expected_producer="learner",
                expected_source_revision=2)
        self.assertEqual(self.journal.db.execute(
            "SELECT count(*) FROM d2_framed_received").fetchone()[0], 0)

    def test_invalid_expectation_fails_without_consuming_stream(self):
        sender, receiver = self.sessions("8" * 32)
        stream = BytesIO(sender.pack(self.event()))
        for value in (True, 0, "x" * 100):
            with self.subTest(value=value):
                with self.assertRaisesRegex(BridgeError, "expected"):
                    self.journal.receive_frame(
                        receiver, stream, expected_producer="learner",
                        expected_task_id=value)
                self.assertEqual(stream.tell(), 0)
        with self.assertRaisesRegex(BridgeError, "source revision"):
            self.journal.receive_frame(
                receiver, stream, expected_source_revision=True)
        self.assertEqual(stream.tell(), 0)

    def test_private_db_persists_no_signed_payload_or_person_content(self):
        event = self.event()
        self.deliver(event)
        row_text = str(self.journal.db.execute(
            "SELECT * FROM d2_framed_received").fetchall())
        self.assertNotIn(event["payload"]["summary"], row_text)
        self.assertNotIn(event["signature"], row_text)


if __name__ == "__main__":
    unittest.main()
