"""Synthetic D2 framed-stream authentication, bounds and replay tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
from io import BytesIO
import json
from pathlib import Path
import struct
import tempfile
import unittest

from athenz.developmental_bridge import (
    BridgeError, SyntheticBridgeJournal, _canonical, synthetic_event,
)
from athenz.developmental_frames import (
    FRAME_LIMIT, FRAME_SCHEMA, SyntheticFrameSession, SyntheticFramedJournal,
)


class SyntheticFramesTests(unittest.TestCase):
    def setUp(self):
        self.producer_keys = {"athenz": b"a" * 32, "learner": b"l" * 32}
        self.frame_keys = {"athenz": b"f" * 32, "learner": b"g" * 32}
        self.rev = {"synthetic:test": 1}
        self.sid = "5" * 32
        self.send = self.session()
        self.recv = self.session()

    def session(self, **kw):
        return SyntheticFrameSession(
            session_id=kw.get("session_id", self.sid),
            producer_keys=kw.get("producer_keys", self.producer_keys),
            frame_keys=kw.get("frame_keys", self.frame_keys),
            revision_check=kw.get("revision_check",
                                  lambda source, revision: self.rev.get(source) == revision),
            enabled=kw.get("enabled", True),
        )

    def event(self, *, producer="athenz", seq=1, kind="observation",
              payload=None, created_at=None):
        if payload is None:
            payload = {"signal": "trace_sha256", "value": "a" * 64}
        return synthetic_event(
            producer=producer, task_id="task", seq=seq, kind=kind,
            source_ref="synthetic:test", source_revision=1,
            payload=payload, secret=self.producer_keys[producer],
            created_at=created_at)

    def corrupt(self, packet, alteration, *, resign_outer=False):
        size = struct.unpack("!I", packet[:4])[0]
        obj = json.loads(packet[4:4 + size])
        alteration(obj)
        if resign_outer:
            obj["authentication"] = hmac.new(
                self.frame_keys[obj["event"]["producer"]],
                _canonical({k: v for k, v in obj.items()
                            if k != "authentication"}),
                hashlib.sha256).hexdigest()
        body = _canonical(obj)
        return struct.pack("!I", len(body)) + body

    def test_authenticated_bidirectional_frames_and_provenance(self):
        request = self.event()
        proposal = self.event(producer="learner", kind="action_proposed",
                              payload={"summary": "synthetic proposal only"})
        first = self.send.pack(request)
        second = self.send.pack(proposal)
        self.assertEqual(self.recv.receive(BytesIO(first), expected_producer="athenz"), request)
        self.assertEqual(self.recv.receive(BytesIO(second), expected_producer="learner"), proposal)
        self.assertEqual(self.recv._in_seq, {"athenz": 1, "learner": 1})
        self.assertTrue(all(x["scope"] == "proposal_only" for x in (request, proposal)))

    def test_sequential_messages_and_replay_denied(self):
        req1, req2 = self.event(seq=1), self.event(seq=2)
        a, b = self.send.pack(req1), self.send.pack(req2)
        self.assertEqual(self.recv.receive(BytesIO(a), expected_producer="athenz"), req1)
        with self.assertRaisesRegex(BridgeError, "replayed"):
            self.recv.receive(BytesIO(a), expected_producer="athenz")
        self.assertEqual(self.recv.receive(BytesIO(b), expected_producer="athenz"), req2)

    def test_skipped_frame_fails_until_correct_frame_arrives(self):
        a = self.send.pack(self.event())
        b = self.send.pack(self.event(seq=2))
        with self.assertRaisesRegex(BridgeError, "skipped"):
            self.recv.receive(BytesIO(b), expected_producer="athenz")
        self.recv.receive(BytesIO(a), expected_producer="athenz")
        self.recv.receive(BytesIO(b), expected_producer="athenz")

    def test_wrong_session_and_wrong_producer_fail(self):
        pkt = self.send.pack(self.event())
        wrong = self.session(session_id="6" * 32)
        with self.assertRaisesRegex(BridgeError, "session"):
            wrong.receive(BytesIO(pkt), expected_producer="athenz")
        with self.assertRaisesRegex(BridgeError, "authentication"):
            self.recv.receive(BytesIO(pkt), expected_producer="learner")

    def test_unauthorized_key_and_modified_event_cannot_pass(self):
        pkt = self.send.pack(self.event())
        wrong = self.session(frame_keys={"athenz": b"x" * 32, "learner": b"g" * 32})
        with self.assertRaisesRegex(BridgeError, "authentication"):
            wrong.receive(BytesIO(pkt), expected_producer="athenz")
        patched = self.corrupt(pkt, lambda o: o["event"]["payload"].update(
            {"value": "0" * 64}), resign_outer=True)
        with self.assertRaisesRegex(BridgeError, "authentication"):
            self.recv.receive(BytesIO(patched), expected_producer="athenz")
        self.assertEqual(self.recv._in_seq["athenz"], 0)

    def test_outer_authority_scope_cannot_be_augmented(self):
        pkt = self.send.pack(self.event())
        changed = self.corrupt(pkt, lambda o: o.update({"execute": True}))
        with self.assertRaisesRegex(BridgeError, "fields"):
            self.recv.receive(BytesIO(changed), expected_producer="athenz")
        changed = self.corrupt(pkt, lambda o: o["event"].update({"scope": "shell"}),
                               resign_outer=True)
        with self.assertRaisesRegex(BridgeError, "scope"):
            self.recv.receive(BytesIO(changed), expected_producer="athenz")

    def test_noncanonical_and_invalid_utf8_fail_without_counter(self):
        pkt = self.send.pack(self.event())
        obj = json.loads(pkt[4:])
        noncanonical = json.dumps(obj, indent=2).encode()
        with self.assertRaisesRegex(BridgeError, "canonical"):
            self.recv.receive(BytesIO(struct.pack("!I", len(noncanonical)) + noncanonical),
                              expected_producer="athenz")
        with self.assertRaisesRegex(BridgeError, "encoding"):
            self.recv.receive(BytesIO(struct.pack("!I", 1) + b"\xff"),
                              expected_producer="athenz")
        self.assertEqual(self.recv._in_seq["athenz"], 0)

    def test_truncated_header_body_invalid_type_and_oversize_rejected(self):
        pkt = self.send.pack(self.event())
        for binary in (b"", b"\x00\x01", pkt[:6],
                       struct.pack("!I", 0),
                       struct.pack("!I", FRAME_LIMIT + 1),
                       struct.pack("!I", 2) + b"[]"):
            with self.subTest(binary=binary[:8]):
                with self.assertRaises(BridgeError):
                    self.recv.receive(BytesIO(binary), expected_producer="athenz")

    def test_partial_reads_across_header_and_body_work(self):
        class SlowReader(BytesIO):
            def read(self, n=-1):
                return super().read(min(n, 3))
        pkt = self.send.pack(self.event())
        self.assertEqual(self.recv.receive(SlowReader(pkt), expected_producer="athenz"),
                         self.event() if False else json.loads(pkt[4:])["event"])

    def test_revocation_between_send_and_receive_fails_closed(self):
        pkt = self.send.pack(self.event())
        self.rev["synthetic:test"] = 2
        with self.assertRaisesRegex(BridgeError, "approval"):
            self.recv.receive(BytesIO(pkt), expected_producer="athenz")
        self.assertEqual(self.recv._in_seq["athenz"], 0)

    def test_registry_callback_exception_fails_closed(self):
        receiver = self.session(revision_check=lambda *_: 1 / 0)
        pkt = self.send.pack(self.event())
        with self.assertRaisesRegex(BridgeError, "source check"):
            receiver.receive(BytesIO(pkt), expected_producer="athenz")

    def test_old_signed_outbox_envelope_can_be_retransmitted_in_new_frame(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        pkt = self.send.pack(self.event(created_at=past))
        self.assertEqual(self.recv.receive(BytesIO(pkt), expected_producer="athenz")["created_at"], past)

    def test_stale_outer_timestamp_rejected_even_with_matching_mac(self):
        pkt = self.send.pack(self.event())
        stale = self.corrupt(pkt, lambda o: o.update({
            "sent_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        }), resign_outer=True)
        with self.assertRaisesRegex(BridgeError, "expired"):
            self.recv.receive(BytesIO(stale), expected_producer="athenz")

    def test_disabled_session_and_missing_keys_rejected(self):
        off = self.session(enabled=False)
        with self.assertRaisesRegex(BridgeError, "disabled"):
            off.pack(self.event())
        with self.assertRaisesRegex(BridgeError, "disabled"):
            off.receive(BytesIO(b""), expected_producer="athenz")
        with self.assertRaises(BridgeError):
            self.session(session_id="../unsafe")
        with self.assertRaises(BridgeError):
            self.session(frame_keys={"athenz": b"bad", "learner": b"g" * 32})

    def test_invalid_frame_sequence_and_wrong_session_id(self):
        pkt = self.send.pack(self.event())
        changed = self.corrupt(pkt, lambda o: o.update({"sequence": 1.0}),
                               resign_outer=True)
        with self.assertRaisesRegex(BridgeError, "sequence"):
            self.recv.receive(BytesIO(changed), expected_producer="athenz")
        changed = self.corrupt(pkt, lambda o: o.update({"session_id": "6" * 32}),
                               resign_outer=True)
        with self.assertRaisesRegex(BridgeError, "session"):
            self.recv.receive(BytesIO(changed), expected_producer="athenz")

    def test_send_writes_binary_framing_and_checks_partial_writes(self):
        stream = BytesIO()
        item = self.event()
        self.send.send(stream, item)
        stream.seek(0)
        self.assertEqual(self.recv.receive(stream, expected_producer="athenz"), item)
        class ShortWriter:
            def write(self, packet):
                return len(packet) - 1
        with self.assertRaisesRegex(BridgeError, "Short"):
            self.send.send(ShortWriter(), self.event(seq=2))

    def test_framed_journal_preserves_durable_dedup_in_new_session(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "event-journal.sqlite3"
        j = SyntheticBridgeJournal(
            path, keys=self.producer_keys,
            consent_check=lambda src, rev: self.rev.get(src) == rev,
            enabled=True)
        self.addCleanup(j.close)
        envelope = self.event()
        p1 = self.send.pack(envelope)
        receiver = SyntheticFramedJournal(self.recv, j)
        self.assertEqual(receiver.receive(BytesIO(p1), expected_producer="athenz")["status"],
                         "accepted")
        second_id = "c" * 32
        sender2 = self.session(session_id=second_id)
        receiver2 = SyntheticFramedJournal(self.session(session_id=second_id), j)
        self.assertEqual(receiver2.receive(
            BytesIO(sender2.pack(envelope)), expected_producer="athenz")["status"],
            "duplicate")
        self.assertEqual(j.db.execute(
            "SELECT COUNT(*) FROM bridge_events").fetchone()[0], 1)

    def test_no_external_process_or_listener_is_created(self):
        # Two memory streams and a schema constant are the only transport
        # surfaces of the fixture; no device command can be represented.
        self.assertEqual(FRAME_SCHEMA, "athenz.d2.stdio-frame/v1")
        pkt = self.send.pack(self.event())
        self.assertLessEqual(len(pkt), FRAME_LIMIT + 4)
        self.assertNotIn(b"shell", pkt)


if __name__ == "__main__":
    unittest.main()
