"""Binary OS pipe handshake and non-executing synthetic D2 roundtrip."""
from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest

from athenz.developmental_bridge import BridgeError, _canonical, synthetic_event
from athenz.developmental_consent import SyntheticSourceRegistry
from athenz.developmental_exchange import SyntheticExchange
from athenz.developmental_pipe import (
    _receive, _send, athenz_handshake, learner_handshake,
)


class PipeTests(unittest.TestCase):
    def setUp(self):
        self.keys = {"athenz": b"a" * 32, "learner": b"l" * 32}
        self.root_secret = b"s" * 32
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / "profile"
        self.registry = SyntheticSourceRegistry(self.home)
        self.addCleanup(self.registry.close)
        self.source = "synthetic:pipe"
        self.check = self.registry.is_current

    def approve(self):
        preview = self.registry.preview(self.source, "approve")
        self.registry.review(
            self.source, "approve", review_sha256=preview["review_sha256"],
            confirmed=True)

    def test_two_real_binary_pipes_and_durable_outbox_roundtrip(self):
        """Two independent thread participants exchange bytes via OS pipes."""
        self.approve()
        to_peer_read, to_peer_write = os.pipe()
        from_peer_read, from_peer_write = os.pipe()
        errors = []
        responses = []
        with (os.fdopen(to_peer_read, "rb", buffering=0) as peer_reader,
              os.fdopen(to_peer_write, "wb", buffering=0) as owner_writer,
              os.fdopen(from_peer_read, "rb", buffering=0) as owner_reader,
              os.fdopen(from_peer_write, "wb", buffering=0) as peer_writer):

            def peer():
                peer_grants = None
                try:
                    # SQLite connections are thread-affine. Hold this
                    # independent grant connection through the whole session.
                    peer_grants = SyntheticSourceRegistry(self.home)
                    session = learner_handshake(
                        peer_reader, peer_writer, root_secret=self.root_secret,
                        producer_keys=self.keys,
                        revision_check=peer_grants.is_current,
                        enabled=True)
                    inbound = session.receive(peer_reader, expected_producer="athenz")
                    self.assertEqual(inbound["kind"], "observation")
                    self.assertEqual(inbound["payload"]["signal"], "trace_sha256")
                    common = {"source_ref": inbound["source_ref"],
                              "source_revision": inbound["source_revision"],
                              "task_id": inbound["task_id"]}
                    p = synthetic_event(
                        **common, producer="learner", seq=1, kind="action_proposed",
                        payload={"summary": "synthetic proposal only; no system action"},
                        secret=self.keys["learner"])
                    r = synthetic_event(
                        **common, producer="learner", seq=2, kind="evaluation_receipt",
                        payload={"result": "independently replayed 4 simulator events"},
                        secret=self.keys["learner"])
                    session.send(peer_writer, p)
                    session.send(peer_writer, r)
                    responses.extend((p, r))
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    if peer_grants is not None:
                        peer_grants.close()
                    peer_writer.close()

            worker = threading.Thread(target=peer, daemon=True)
            worker.start()
            session = athenz_handshake(
                owner_reader, owner_writer, root_secret=self.root_secret,
                producer_keys=self.keys, revision_check=self.check,
                source_ref=self.source, source_revision=1, enabled=True)
            request = synthetic_event(
                producer="athenz", task_id="pipe", seq=1, kind="observation",
                source_ref=self.source, source_revision=1,
                payload={"signal": "trace_sha256", "value": "a" * 64},
                secret=self.keys["athenz"])
            session.send(owner_writer, request)
            received = [
                session.receive(owner_reader, expected_producer="learner"),
                session.receive(owner_reader, expected_producer="learner"),
            ]
            worker.join(timeout=4)
            self.assertFalse(worker.is_alive(), "Synthetic peer did not complete")
            self.assertEqual(errors, [])
            self.assertEqual(received, responses)

            with SyntheticExchange.from_registry(
                self.home / "outbox.sqlite3", keys=self.keys,
                registry=self.registry, enabled=True) as queue:
                self.assertEqual(
                    queue.stage_pair(request, *received)["status"], "staged")
                self.assertEqual(len(queue.pending()), 2)
                self.assertTrue(all(x["scope"] == "proposal_only" for x in received))
                self.assertTrue(all(x["origin"] == "simulation_episode" for x in received))
                rev = self.registry.preview(self.source, "revoke")
                self.registry.review(
                    self.source, "revoke",
                    review_sha256=rev["review_sha256"], confirmed=True)
                with self.assertRaisesRegex(BridgeError, "approved"):
                    queue.pending()

    def test_disabled_handshakes_do_not_write_any_bytes(self):
        writer = BytesIO()
        with self.assertRaisesRegex(BridgeError, "disabled"):
            athenz_handshake(
                BytesIO(), writer, root_secret=self.root_secret,
                producer_keys=self.keys, revision_check=self.check,
                source_ref=self.source, source_revision=1)
        self.assertEqual(writer.getvalue(), b"")
        with self.assertRaisesRegex(BridgeError, "disabled"):
            learner_handshake(
                BytesIO(), writer, root_secret=self.root_secret,
                producer_keys=self.keys, revision_check=self.check)
        self.assertEqual(writer.getvalue(), b"")

    def test_unapproved_source_never_receives_peer_reply(self):
        hello = {"schema": "athenz.d2.synthetic-hello/v1",
                 "sender": "athenz", "source_ref": self.source,
                 "source_revision": 1, "athenz_nonce": "1" * 32}
        source = BytesIO()
        _send(source, hello)
        target = BytesIO()
        with self.assertRaisesRegex(BridgeError, "not approved"):
            learner_handshake(
                BytesIO(source.getvalue()), target,
                root_secret=self.root_secret, producer_keys=self.keys,
                revision_check=self.check, enabled=True)
        self.assertEqual(target.getvalue(), b"")

    def test_truncated_or_oversized_handshake_rejected_before_read(self):
        for packet in (b"", b"\x01", b"\x00\x00",
                       struct.pack("!H", 513),
                       struct.pack("!H", 10) + b"{}",
                       struct.pack("!H", 2) + b"[]"):
            with self.subTest(packet=packet[:8]):
                with self.assertRaises(BridgeError):
                    _receive(BytesIO(packet))

    def test_noncanonical_and_nonutf8_rejected(self):
        value = json.dumps({"hello": "x"}, indent=1).encode()
        with self.assertRaisesRegex(BridgeError, "Noncanonical"):
            _receive(BytesIO(struct.pack("!H", len(value)) + value))
        with self.assertRaisesRegex(BridgeError, "Malformed"):
            _receive(BytesIO(b"\x00\x01\xff"))

    def test_partial_binary_read_supported(self):
        class Reader(BytesIO):
            def read(self, size=-1):
                return super().read(min(size, 2))
        src = BytesIO()
        _send(src, {"schema": "test", "value": 1})
        self.assertEqual(_receive(Reader(src.getvalue())),
                         {"schema": "test", "value": 1})

    def test_short_write_and_failing_flush_rejected(self):
        class ShortWrite:
            def write(self, packet):
                return len(packet) - 1
        with self.assertRaisesRegex(BridgeError, "short"):
            _send(ShortWrite(), {"schema": "test"})
        class FailingFlush:
            def write(self, packet):
                return len(packet)
            def flush(self):
                raise OSError("private error")
        with self.assertRaisesRegex(BridgeError, "write failed"):
            _send(FailingFlush(), {"schema": "test"})

    def test_oversized_json_record_rejected_before_writing(self):
        sink = BytesIO()
        with self.assertRaisesRegex(BridgeError, "too large"):
            _send(sink, {"payload": "a" * 800})
        self.assertEqual(sink.getvalue(), b"")

    def test_no_root_credential_exposed_in_hello_wire(self):
        self.approve()
        writer = BytesIO()
        with self.assertRaises(BridgeError):
            athenz_handshake(
                BytesIO(), writer, root_secret=self.root_secret,
                producer_keys=self.keys, revision_check=self.check,
                source_ref=self.source, source_revision=1, enabled=True)
        self.assertNotIn(self.root_secret, writer.getvalue())
        self.assertNotIn(b"execute-shell", writer.getvalue())


if __name__ == "__main__":
    unittest.main()
