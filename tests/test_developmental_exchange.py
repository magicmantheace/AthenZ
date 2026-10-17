"""Synthetic-only transactional D2 outbox, source fencing and replay tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from athenz.developmental_bridge import BridgeError, synthetic_event
from athenz.developmental_exchange import SyntheticExchange


class SyntheticExchangeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "synthetic-exchange.sqlite3"
        self.keys = {"athenz": b"a" * 32, "learner": b"l" * 32}
        self.current = {"synthetic:trace": 1}
        self.exchange = self._open()

    def _open(self, enabled=True, check=None):
        exchange = SyntheticExchange(
            self.path, keys=self.keys,
            revision_check=check or (lambda src, rev: self.current.get(src) == rev),
            enabled=enabled)
        self.addCleanup(exchange.close)
        return exchange

    def _event(self, producer, seq, kind, payload, **kw):
        return synthetic_event(
            producer=producer, task_id=kw.get("task_id", "demo"), seq=seq,
            kind=kind, source_ref=kw.get("source_ref", "synthetic:trace"),
            source_revision=kw.get("source_revision", 1),
            payload=payload, secret=self.keys[producer],
            created_at=kw.get("created_at"))

    def pair(self, *, req_seq=1, reply_seq=1, **kw):
        common = {k: v for k, v in kw.items() if k in {
            "task_id", "source_ref", "source_revision"}}
        request = self._event(
            "athenz", req_seq, "observation",
            {"signal": "trace_sha256", "value": "a" * 64}, **common)
        proposal = self._event(
            "learner", reply_seq, "action_proposed",
            {"summary": "synthetic proposal only; no system action"}, **common)
        receipt = self._event(
            "learner", reply_seq + 1, "evaluation_receipt",
            {"result": "independently replayed 4 simulator events"}, **common)
        return request, proposal, receipt

    def test_stage_and_look_up_two_nonexecuting_signed_replies(self):
        trio = self.pair()
        self.assertEqual(self.exchange.stage_pair(*trio),
                         {"status": "staged", "actions_executed": False})
        items = self.exchange.pending()
        self.assertEqual(items, list(trio[1:]))
        self.assertEqual([e["origin"] for e in items],
                         ["simulation_episode", "simulation_episode"])
        self.assertTrue(all(e["scope"] == "proposal_only" for e in items))
        self.assertEqual(self.exchange.db.execute(
            "SELECT count(*) FROM d2_ingress").fetchone()[0], 1)

    def test_exact_request_replay_is_idempotent_after_restart(self):
        trio = self.pair()
        self.exchange.stage_pair(*trio)
        self.exchange.close()
        self.exchange = self._open()
        self.assertEqual(self.exchange.stage_pair(*trio)["status"], "duplicate")
        self.assertEqual(self.exchange.pending(), list(trio[1:]))
        self.assertEqual(self.exchange.db.execute(
            "SELECT count(*) FROM d2_outbox").fetchone()[0], 2)

    def test_original_signed_outbox_survives_regenerated_reply_retry(self):
        req, first, second = self.pair()
        self.exchange.stage_pair(req, first, second)
        updated = self.pair()
        self.assertEqual(self.exchange.stage_pair(req, updated[1], updated[2])["status"],
                         "duplicate")
        self.assertEqual(self.exchange.pending(), [first, second])

    def test_ack_is_digest_and_confirmation_fenced(self):
        req, proposal, receipt = self.pair()
        self.exchange.stage_pair(req, proposal, receipt)
        digest = self.exchange.db.execute(
            "SELECT digest FROM d2_outbox WHERE event_id=?",
            (proposal["event_id"],)).fetchone()[0]
        with self.assertRaisesRegex(BridgeError, "confirmation"):
            self.exchange.acknowledge(proposal["event_id"], digest)
        with self.assertRaisesRegex(BridgeError, "fingerprint"):
            self.exchange.acknowledge(proposal["event_id"], "b" * 64, confirmed=True)
        self.assertEqual(self.exchange.acknowledge(
            proposal["event_id"], digest, confirmed=True)["status"], "acked")
        self.assertEqual(self.exchange.acknowledge(
            proposal["event_id"], digest, confirmed=True)["status"], "duplicate")
        self.assertEqual(self.exchange.pending(), [receipt])

    def test_reordered_reply_rolls_back_whole_request(self):
        req, p, r = self.pair(reply_seq=2)
        with self.assertRaisesRegex(BridgeError, "sequence"):
            self.exchange.stage_pair(req, p, r)
        self.assertEqual(self.exchange.pending(), [])
        self.assertEqual(self.exchange.db.execute(
            "SELECT count(*) FROM d2_ingress").fetchone()[0], 0)

    def test_nonconsecutive_reply_cannot_stage_partially(self):
        req, p, r = self.pair()
        r["seq"] = 4
        with self.assertRaises(BridgeError):
            self.exchange.stage_pair(req, p, r)
        self.assertEqual(self.exchange.db.execute(
            "SELECT count(*) FROM d2_ingress").fetchone()[0], 0)

    def test_malformed_signatures_and_reply_scope_rejected(self):
        req, p, r = self.pair()
        p["payload"]["summary"] = "run a shell command"
        with self.assertRaises(BridgeError):
            self.exchange.stage_pair(req, p, r)
        req, p, r = self.pair()
        p["scope"] = "execute_any_command"
        with self.assertRaises(BridgeError):
            self.exchange.stage_pair(req, p, r)
        self.assertEqual(self.exchange.pending(), [])

    def test_signed_but_unsupported_reply_contents_rejected(self):
        from athenz.developmental_bridge import _canonical
        import hmac
        req, p, r = self.pair()
        p["payload"]["summary"] = "unexpected user content"
        p["signature"] = hmac.new(
            self.keys["learner"], _canonical({k: v for k, v in p.items()
                                                if k != "signature"}),
            hashlib.sha256).hexdigest()
        with self.assertRaisesRegex(BridgeError, "generic"):
            self.exchange.stage_pair(req, p, r)

    def test_wrong_source_or_revision_rejected(self):
        req, p, r = self.pair()
        from athenz.developmental_bridge import _canonical
        import hmac
        p["source_ref"] = "synthetic:other"
        p["signature"] = hmac.new(
            self.keys["learner"], _canonical({k: v for k, v in p.items()
                                                if k != "signature"}),
            hashlib.sha256).hexdigest()
        with self.assertRaisesRegex(BridgeError, "bound"):
            self.exchange.stage_pair(req, p, r)
        self.current.clear()
        with self.assertRaisesRegex(BridgeError, "approved"):
            self.exchange.stage_pair(*self.pair())

    def test_consent_revoked_mid_stage_rolls_back(self):
        checks = [0]
        def changing(ref, revision):
            checks[0] += 1
            return checks[0] < 3
        self.exchange.close()
        self.exchange = self._open(check=changing)
        with self.assertRaisesRegex(BridgeError, "approved"):
            self.exchange.stage_pair(*self.pair())
        self.assertEqual(self.exchange.db.execute(
            "SELECT count(*) FROM d2_ingress").fetchone()[0], 0)
        self.assertEqual(self.exchange.db.execute(
            "SELECT count(*) FROM d2_outbox").fetchone()[0], 0)

    def test_revocation_cancels_pending_and_prevents_retry(self):
        req, p, r = self.pair()
        self.exchange.stage_pair(req, p, r)
        revocation = self._event(
            "athenz", 2, "revocation", {"reason": "synthetic test withdrawn"})
        self.assertEqual(self.exchange.receive_revocation(revocation)["status"], "revoked")
        self.assertEqual(self.exchange.receive_revocation(revocation)["status"], "duplicate")
        self.assertEqual(self.exchange.pending(), [])
        self.assertEqual(self.exchange.db.execute(
            "SELECT count(*) FROM d2_outbox WHERE state='revoked'").fetchone()[0], 2)
        with self.assertRaisesRegex(BridgeError, "revoked"):
            self.exchange.stage_pair(*self.pair(req_seq=3, reply_seq=3))
        digest = self.exchange.db.execute(
            "SELECT digest FROM d2_outbox WHERE event_id=?",
            (p["event_id"],)).fetchone()[0]
        with self.assertRaisesRegex(BridgeError, "Revoked"):
            self.exchange.acknowledge(p["event_id"], digest, confirmed=True)
        self.exchange.close()
        self.exchange = self._open()
        self.assertEqual(self.exchange.pending(), [])

    def test_revocation_cannot_come_from_learner(self):
        event = self._event(
            "learner", 1, "action_proposed", {"summary": "test"})
        with self.assertRaisesRegex(BridgeError, "Only AthenZ"):
            self.exchange.receive_revocation(event)

    def test_source_revision_change_fences_existing_outbox(self):
        self.exchange.stage_pair(*self.pair())
        self.current["synthetic:trace"] = 2
        with self.assertRaisesRegex(BridgeError, "approved"):
            self.exchange.pending()
        self.assertEqual(self.exchange.db.execute(
            "SELECT count(*) FROM d2_outbox WHERE state='pending'").fetchone()[0], 2)

    def test_tampered_disk_payload_rejected_even_with_correct_id(self):
        req, p, _ = self.pair()
        self.exchange.stage_pair(*self.pair())
        self.exchange.db.execute(
            "UPDATE d2_outbox SET signed_json=? WHERE event_id=("
            "SELECT event_id FROM d2_outbox LIMIT 1)", ('{"forged":true}',))
        with self.assertRaisesRegex(BridgeError, "modified"):
            self.exchange.pending()

    def test_synthetic_backlog_cap_is_fail_closed(self):
        with mock.patch("athenz.developmental_exchange.MAX_PENDING", 2):
            self.exchange.stage_pair(*self.pair())
            with self.assertRaisesRegex(BridgeError, "backlog"):
                self.exchange.stage_pair(*self.pair(req_seq=2, reply_seq=3))
        self.assertEqual(len(self.exchange.pending()), 2)
        self.assertEqual(self.exchange.db.execute(
            "SELECT count(*) FROM d2_ingress").fetchone()[0], 1)

    def test_disabling_exchange_never_mutates_existing_queue(self):
        trio = self.pair()
        self.exchange.enabled = False
        self.assertEqual(self.exchange.stage_pair(*trio)["status"], "disabled")
        self.assertEqual(self.exchange.pending(), [])
        self.assertEqual(self.exchange.db.execute(
            "SELECT count(*) FROM d2_ingress").fetchone()[0], 0)

    def test_delivery_long_after_timestamp_is_allowed_only_for_saved_message(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat(timespec="seconds")
        req = self._event("athenz", 1, "observation",
                          {"signal": "trace_sha256", "value": "a" * 64}, created_at=old)
        p = self._event("learner", 1, "action_proposed",
                        {"summary": "synthetic proposal only; no system action"},
                        created_at=old)
        r = self._event("learner", 2, "evaluation_receipt",
                        {"result": "independently replayed 4 simulator events"},
                        created_at=old)
        self.exchange.stage_pair(req, p, r)
        # The persisted signature/size is checked against the original event
        # time at read, not discarded after the original 5-minute send window.
        self.exchange.close()
        self.exchange = self._open()
        self.assertEqual(self.exchange.pending(), [p, r])

    def test_bound_validation_and_status_are_private_and_small(self):
        self.exchange.stage_pair(*self.pair())
        for limit in (False, 0, 21, "5"):
            with self.assertRaisesRegex(BridgeError, "limit"):
                self.exchange.pending(limit=limit)
        self.assertEqual(len(self.exchange.pending(limit=1)), 1)
        values = self.exchange.db.execute(
            "SELECT signed_json FROM d2_outbox").fetchall()
        self.assertEqual(len(values), 2)
        self.assertNotIn("private user", json.dumps(values).lower())


if __name__ == "__main__":
    unittest.main()
