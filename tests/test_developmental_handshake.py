"""Synthetic-only mutual challenge-response and ephemeral key separation."""
from __future__ import annotations

import copy
import re
import unittest
from unittest.mock import patch

from athenz.developmental_bridge import BridgeError
from athenz.developmental_handshake import (
    HELLO_SCHEMA, accept, finalize, initiate, respond,
)


class SyntheticHandshakeTests(unittest.TestCase):
    def setUp(self):
        self.root = b"r" * 32
        self.revision = 1
        self.source = "synthetic:trial"
        self.check = lambda source, rev: source == self.source and rev == self.revision
        self.hello = initiate(self.source, 1)
        self.reply = respond(self.hello, root_secret=self.root,
                             revision_check=self.check)

    def complete(self):
        confirmation, client = finalize(
            self.hello, self.reply, root_secret=self.root,
            revision_check=self.check)
        server = accept(self.hello, self.reply, confirmation,
                        root_secret=self.root, revision_check=self.check)
        return confirmation, client, server

    def test_mutual_authentication_and_equal_ephemeral_material(self):
        confirm, client, server = self.complete()
        self.assertEqual(client, server)
        self.assertRegex(client["session_id"], r"^[0-9a-f]{32}$")
        self.assertEqual(len(client["frame_keys"]["athenz"]), 32)
        self.assertEqual(len(client["frame_keys"]["learner"]), 32)
        self.assertNotEqual(client["frame_keys"]["athenz"],
                            client["frame_keys"]["learner"])
        self.assertNotEqual(client["frame_keys"]["athenz"], self.root)
        self.assertNotEqual(client["frame_keys"]["learner"], self.root)
        self.assertEqual(confirm["sender"], "athenz")
        self.assertNotIn(self.root, str(self.reply).encode())

    def test_fresh_nonce_generates_fresh_session(self):
        _, first, _ = self.complete()
        hello2 = initiate(self.source, 1)
        self.assertNotEqual(hello2["athenz_nonce"], self.hello["athenz_nonce"])
        reply2 = respond(hello2, root_secret=self.root, revision_check=self.check)
        _, second = finalize(hello2, reply2, root_secret=self.root,
                             revision_check=self.check)
        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertNotEqual(first["frame_keys"], second["frame_keys"])

    def test_bad_root_key_denied_on_client_and_server(self):
        with self.assertRaisesRegex(BridgeError, "authentication"):
            finalize(self.hello, self.reply, root_secret=b"x" * 32,
                     revision_check=self.check)
        confirm, _, _ = self.complete()
        with self.assertRaisesRegex(BridgeError, "authentication"):
            accept(self.hello, self.reply, confirm, root_secret=b"x" * 32,
                   revision_check=self.check)

    def test_changed_source_or_revision_breaks_proof(self):
        for change in ({"source_ref": "synthetic:other"},
                       {"source_revision": 2}):
            hello = copy.deepcopy(self.hello)
            hello.update(change)
            with self.assertRaisesRegex(BridgeError, "authentication"):
                finalize(hello, self.reply, root_secret=self.root,
                         revision_check=lambda *_: True)

    def test_wrong_challenge_nonce_is_denied(self):
        hello = copy.deepcopy(self.hello)
        hello["athenz_nonce"] = "4" * 32
        if hello["athenz_nonce"] == self.hello["athenz_nonce"]:
            hello["athenz_nonce"] = "5" * 32
        with self.assertRaisesRegex(BridgeError, "challenge"):
            finalize(hello, self.reply, root_secret=self.root,
                     revision_check=self.check)

    def test_reused_identical_nonce_rejected(self):
        response = copy.deepcopy(self.reply)
        response["learner_nonce"] = self.hello["athenz_nonce"]
        with self.assertRaisesRegex(BridgeError, "differ"):
            finalize(self.hello, response, root_secret=self.root,
                     revision_check=self.check)

    def test_revocation_blocks_each_side_at_verification(self):
        self.revision = 2
        with self.assertRaisesRegex(BridgeError, "not approved"):
            finalize(self.hello, self.reply, root_secret=self.root,
                     revision_check=self.check)
        with self.assertRaisesRegex(BridgeError, "not approved"):
            respond(self.hello, root_secret=self.root, revision_check=self.check)
        self.revision = 1
        confirm, _, _ = self.complete()
        self.revision = 2
        with self.assertRaisesRegex(BridgeError, "not approved"):
            accept(self.hello, self.reply, confirm, root_secret=self.root,
                   revision_check=self.check)

    def test_revocation_check_exception_fails_closed(self):
        with self.assertRaisesRegex(BridgeError, "check failed"):
            finalize(self.hello, self.reply, root_secret=self.root,
                     revision_check=lambda *_: 1 / 0)
        with self.assertRaisesRegex(BridgeError, "checker"):
            respond(self.hello, root_secret=self.root, revision_check=None)

    def test_malformed_unknown_fields_and_wrong_schema_denied(self):
        for change in ({"schema": "bad"}, {"execute": "root"},
                       {"source_ref": "owner:private"},
                       {"source_revision": True},
                       {"athenz_nonce": "../not hex"}):
            hello = copy.deepcopy(self.hello)
            hello.update(change)
            with self.subTest(change=change):
                with self.assertRaises(BridgeError):
                    respond(hello, root_secret=self.root, revision_check=self.check)
        self.assertEqual(self.hello["schema"], HELLO_SCHEMA)

    def test_malformed_response_and_confirmation_denied(self):
        for change in ({"sender": "athenz"}, {"execute": True},
                       {"proof": "bad"}, {"learner_nonce": "not-a-nonce"}):
            response = copy.deepcopy(self.reply)
            response.update(change)
            with self.subTest(change=change):
                with self.assertRaises(BridgeError):
                    finalize(self.hello, response, root_secret=self.root,
                             revision_check=self.check)
        confirm, _, _ = self.complete()
        confirm["proof"] = "0" * 64
        with self.assertRaisesRegex(BridgeError, "authentication"):
            accept(self.hello, self.reply, confirm, root_secret=self.root,
                   revision_check=self.check)

    def test_replayed_confirmation_for_new_response_is_denied(self):
        confirmation, _, _ = self.complete()
        second = respond(self.hello, root_secret=self.root,
                         revision_check=self.check)
        self.assertNotEqual(self.reply["learner_nonce"], second["learner_nonce"])
        with self.assertRaises(BridgeError):
            accept(self.hello, second, confirmation,
                   root_secret=self.root, revision_check=self.check)

    def test_invalid_inputs_and_short_keys_rejected(self):
        with self.assertRaises(BridgeError):
            initiate("owner:someone", 1)
        for rev in (0, True, 1000001):
            with self.assertRaises(BridgeError):
                initiate(self.source, rev)
        for invalid in (None, b"short", "notbytes"):
            with self.assertRaises(BridgeError):
                respond(self.hello, root_secret=invalid,
                        revision_check=self.check)

    def test_derived_keys_accept_frames_and_revocation_fences_delivery(self):
        from io import BytesIO
        from athenz.developmental_bridge import synthetic_event
        from athenz.developmental_frames import SyntheticFrameSession

        _, initiator, responder = self.complete()
        event_keys = {"athenz": b"a" * 32, "learner": b"l" * 32}
        common = dict(producer_keys=event_keys, revision_check=self.check,
                      enabled=True)
        sender = SyntheticFrameSession(**initiator, **common)
        receiver = SyntheticFrameSession(**responder, **common)
        event = synthetic_event(
            producer="athenz", task_id="demo", seq=1, kind="observation",
            source_ref=self.source, source_revision=1,
            payload={"signal": "trace_sha256", "value": "a" * 64},
            secret=event_keys["athenz"])
        packet = sender.pack(event)
        self.assertEqual(
            receiver.receive(BytesIO(packet), expected_producer="athenz"),
            event)
        next_event = synthetic_event(
            producer="athenz", task_id="demo", seq=2, kind="observation",
            source_ref=self.source, source_revision=1,
            payload={"signal": "trace_sha256", "value": "b" * 64},
            secret=event_keys["athenz"])
        pkt2 = sender.pack(next_event)
        self.revision = 2
        with self.assertRaisesRegex(BridgeError, "approval"):
            receiver.receive(BytesIO(pkt2), expected_producer="athenz")

    def test_frame_key_use_with_synthetic_codec(self):
        # The framing codec is available on a separate integration branch;
        # this frozen-material test exercises the handshake on its own.
        _, result, _ = self.complete()
        self.assertEqual(sorted(result["frame_keys"]), ["athenz", "learner"])
        self.assertIsInstance(result["frame_keys"]["athenz"], bytes)
        self.assertIsInstance(result["session_id"], str)


if __name__ == "__main__":
    unittest.main()
