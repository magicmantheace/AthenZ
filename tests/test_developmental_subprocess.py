"""D2 synthetic stdio handshake with two independent Python processes.

Uses public fixed test keys, an isolated private synthetic source registry,
and no real Developmental AI code, personal data or process permissions.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from athenz.developmental_bridge import BridgeError, synthetic_event
from athenz.developmental_consent import SyntheticSourceRegistry
from athenz.developmental_exchange import SyntheticExchange
from athenz.developmental_pipe import athenz_handshake


ROOT_SECRET = b"s" * 32  # public test-only bytes
KEYS = {"athenz": b"a" * 32, "learner": b"l" * 32}
SOURCE = "synthetic:process"
PEER = Path(__file__).resolve().parent / "fixtures" / "d2_process_fixture.py"
REPO = Path(__file__).resolve().parents[1]


class TwoProcessD2Tests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.home = Path(root.name) / "synthetic-home"
        self.grants = SyntheticSourceRegistry(self.home)
        self.addCleanup(self.grants.close)

    def approve(self):
        p = self.grants.preview(SOURCE, "approve")
        self.grants.review(SOURCE, "approve",
                           review_sha256=p["review_sha256"], confirmed=True)

    def spawn(self):
        # Suppress inherited app secrets or credentials.
        permitted = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR",
                     "COMSPEC", "PATHEXT", "TMP", "TEMP", "TMPDIR", "HOME")
        env = {k: os.environ[k] for k in permitted if k in os.environ}
        env["PYTHONPATH"] = str(REPO)
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        process = subprocess.Popen(
            [sys.executable, str(PEER), "--synthetic-fixture", str(self.home)],
            cwd=REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=-1)
        self.assertNotEqual(process.pid, os.getpid())
        expired = threading.Event()
        def deadline():
            if process.poll() is None:
                expired.set()
                process.kill()
        timer = threading.Timer(12, deadline)
        timer.daemon = True
        timer.start()
        def cleanup():
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
        self.addCleanup(cleanup)
        return process, timer, expired

    def handshake(self, process, *, root=ROOT_SECRET):
        return athenz_handshake(
            process.stdout, process.stdin,
            root_secret=root, producer_keys=KEYS, revision_check=self.grants.is_current,
            source_ref=SOURCE, source_revision=1, enabled=True)

    def test_separate_process_roundtrip_stage_and_revoke(self):
        self.approve()
        process, timer, expired = self.spawn()
        session = self.handshake(process)
        request = synthetic_event(
            producer="athenz", task_id="process", seq=1, kind="observation",
            source_ref=SOURCE, source_revision=1,
            payload={"signal": "trace_sha256", "value": "a" * 64},
            secret=KEYS["athenz"])
        session.send(process.stdin, request)
        replies = [session.receive(process.stdout, expected_producer="learner")
                   for _ in range(2)]
        process.stdin.close()
        self.assertEqual(process.wait(timeout=5), 0)
        timer.cancel()
        self.assertFalse(expired.is_set())
        self.assertEqual([e["kind"] for e in replies],
                         ["action_proposed", "evaluation_receipt"])
        self.assertTrue(all(e["origin"] == "simulation_episode"
                            and e["scope"] == "proposal_only" for e in replies))
        with SyntheticExchange.from_registry(
            self.home / "outbox.sqlite3", keys=KEYS,
            registry=self.grants, enabled=True) as queue:
            self.assertEqual(queue.stage_pair(request, *replies)["status"], "staged")
            self.assertEqual(queue.pending(), replies)
            preview = self.grants.preview(SOURCE, "revoke")
            self.grants.review(SOURCE, "revoke",
                               review_sha256=preview["review_sha256"], confirmed=True)
            with self.assertRaisesRegex(BridgeError, "approved"):
                queue.pending()

    def test_unapproved_source_denies_process_handshake(self):
        process, timer, expired = self.spawn()
        with self.assertRaises(BridgeError):
            self.handshake(process)
        process.stdin.close()
        self.assertNotEqual(process.wait(timeout=5), 0)
        timer.cancel()
        self.assertFalse(expired.is_set())

    def test_wrong_root_secret_denies_process_handshake(self):
        self.approve()
        process, timer, expired = self.spawn()
        with self.assertRaisesRegex(BridgeError, "authentication"):
            self.handshake(process, root=b"x" * 32)
        process.stdin.close()
        self.assertNotEqual(process.wait(timeout=5), 0)
        timer.cancel()
        self.assertFalse(expired.is_set())


if __name__ == "__main__":
    unittest.main()
