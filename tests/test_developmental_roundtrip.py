"""Opt-in bounded AthenZ D2 one-shot process transport contract tests."""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from io import BytesIO

from athenz.developmental_bridge import BridgeError, synthetic_event
from athenz.developmental_consent import SyntheticSourceRegistry
from athenz.developmental_exchange import SyntheticExchange
from athenz.developmental_receiver import SyntheticDurableReceiver
from athenz.developmental_roundtrip import synthetic_trace_roundtrip

ROOT = Path(__file__).resolve().parents[1]
PEER = ROOT / "tests" / "fixtures" / "d2_roundtrip_peer.py"


class OneShotRoundtripTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / "private"
        self.registry = SyntheticSourceRegistry(self.home)
        self.addCleanup(self.registry.close)
        # Independent fresh bytes for each test. Never commit or log secrets.
        material = secrets.token_bytes(96)
        self.bootstrap = material
        self.root = material[:32]
        self.keys = {"athenz": material[32:64], "learner": material[64:96]}
        self.receiver = SyntheticDurableReceiver(
            self.home / "athenz_d2_received.sqlite3", keys=self.keys,
            revision_check=self.registry.is_current, enabled=True)
        self.addCleanup(self.receiver.close)
        self.exchange = SyntheticExchange.from_registry(
            self.home / "athenz_d2_local_outbox.sqlite3", keys=self.keys,
            registry=self.registry, enabled=True)
        self.addCleanup(self.exchange.close)

    def approve(self):
        p = self.registry.preview("synthetic:interop", "approve")
        self.registry.review(
            "synthetic:interop", "approve",
            review_sha256=p["review_sha256"], confirmed=True)

    def request(self, digest="a" * 64, *, source="synthetic:interop"):
        return synthetic_event(
            producer="athenz", task_id="trial", seq=1, kind="observation",
            source_ref=source, source_revision=1,
            payload={"signal": "trace_sha256", "value": digest},
            secret=self.keys["athenz"])

    def spawn(self):
        env = {k: os.environ[k] for k in (
            "PATH", "SYSTEMROOT", "SystemRoot", "WINDIR",
            "COMSPEC", "PATHEXT", "TMP", "TEMP", "TMPDIR", "HOME")
            if k in os.environ}
        env.update({"PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1",
                    "PYTHONDONTWRITEBYTECODE": "1"})
        child = subprocess.Popen(
            [sys.executable, str(PEER), "--synthetic-d2-test", str(self.home)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, cwd=ROOT, bufsize=-1)
        self.assertNotEqual(child.pid, os.getpid())
        expired = threading.Event()
        def limit():
            if child.poll() is None:
                expired.set()
                child.kill()
        timer = threading.Timer(12, limit)
        timer.daemon = True
        timer.start()
        def cleanup():
            timer.cancel()
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            for pipe in (child.stdin, child.stdout, child.stderr):
                if pipe is not None and not pipe.closed:
                    pipe.close()
        self.addCleanup(cleanup)
        child.stdin.write(self.bootstrap)
        child.stdin.flush()
        return child, timer, expired

    def run_client(self, reader, writer, request=None, **opts):
        return synthetic_trace_roundtrip(
            reader, writer, root_secret=self.root, producer_keys=self.keys,
            registry=self.registry, receiver=self.receiver,
            exchange=self.exchange, request=request or self.request(),
            enabled=opts.get("enabled", True))

    def test_real_process_handshake_pair_receipt_and_remote_durable_ack(self):
        self.approve()
        child, timer, expired = self.spawn()
        result = self.run_client(child.stdout, child.stdin)
        child.stdin.close()
        self.assertEqual(child.wait(timeout=6), 0)
        timer.cancel()
        self.assertFalse(expired.is_set())
        self.assertEqual(result, {
            "status": "staged", "received_events": 2,
            "acknowledgments_sent": 2, "actions_executed": False})
        self.assertEqual(self.exchange.db.execute(
            "SELECT count(*) FROM d2_outbox WHERE state='pending'").fetchone()[0], 2)
        self.assertEqual(self.receiver.db.execute(
            "SELECT count(*) FROM d2_framed_received").fetchone()[0], 2)
        # sqlite3.Connection.__exit__ commits but does not close. Windows
        # will not remove this temporary database while its handle is open.
        from contextlib import closing
        with closing(sqlite3.connect(self.home / "d2_fixture_peer_outbox.sqlite3")) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM d2_outbox WHERE state='acked'").fetchone()[0], 2)

    def test_default_disabled_without_writing(self):
        self.approve()
        stream = BytesIO()
        with self.assertRaisesRegex(BridgeError, "disabled"):
            self.run_client(BytesIO(), stream, enabled=False)
        self.assertEqual(stream.getvalue(), b"")

    def test_unapproved_source_denied_without_handshake(self):
        stream = BytesIO()
        with self.assertRaisesRegex(BridgeError, "approval"):
            self.run_client(BytesIO(), stream)
        self.assertEqual(stream.getvalue(), b"")

    def test_request_wrong_origin_and_digest_denied_early(self):
        self.approve()
        bad = self.request(source="synthetic:other")
        stream = BytesIO()
        with self.assertRaisesRegex(BridgeError, "fixed trace"):
            self.run_client(BytesIO(), stream, bad)
        self.assertEqual(stream.getvalue(), b"")
        from athenz.developmental_bridge import synthetic_event as sign
        changed = sign(
            producer="athenz", task_id="trial", seq=1, kind="outcome",
            source_ref="synthetic:interop", source_revision=1,
            payload={"accepted": True, "result": "simulated"},
            secret=self.keys["athenz"])
        with self.assertRaisesRegex(BridgeError, "fixed trace"):
            self.run_client(BytesIO(), stream, changed)
        self.assertEqual(stream.getvalue(), b"")

    def test_validly_signed_wrong_trace_digest_is_rejected_by_peer(self):
        self.approve()
        child, timer, expired = self.spawn()
        with self.assertRaises(BridgeError):
            self.run_client(child.stdout, child.stdin,
                            self.request(digest="b" * 64))
        child.stdin.close()
        self.assertNotEqual(child.wait(timeout=5), 0)
        timer.cancel()
        self.assertFalse(expired.is_set())
        self.assertEqual(self.receiver.db.execute(
            "SELECT count(*) FROM d2_framed_received").fetchone()[0], 0)

    def test_mismatched_keys_and_store_locations_rejected_early(self):
        self.approve()
        separate = SyntheticDurableReceiver(
            self.home / "mismatched.sqlite3",
            keys={"athenz": b"x" * 32, "learner": self.keys["learner"]},
            revision_check=self.registry.is_current, enabled=True)
        self.addCleanup(separate.close)
        with self.assertRaisesRegex(BridgeError, "keys"):
            synthetic_trace_roundtrip(
                BytesIO(), BytesIO(), root_secret=self.root,
                producer_keys=self.keys, registry=self.registry,
                receiver=separate, exchange=self.exchange,
                request=self.request(), enabled=True)

    def test_revoke_before_handshake_denies_delivery(self):
        self.approve()
        revoked = self.registry.preview("synthetic:interop", "revoke")
        self.registry.review("synthetic:interop", "revoke",
                             review_sha256=revoked["review_sha256"], confirmed=True)
        with self.assertRaisesRegex(BridgeError, "approval"):
            self.run_client(BytesIO(), BytesIO())


if __name__ == "__main__":
    unittest.main()
