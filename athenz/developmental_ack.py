"""Synthetic-only D2 authenticated delivery acknowledgments.

An ACK is HMAC-bound to a negotiated synthetic frame session and a prior
*durably journaled* learner envelope. Never grants permissions, model
promotion, private data access or production identity. No sockets/processes.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import struct
from typing import BinaryIO

from .developmental_bridge import (
    BridgeError, SyntheticBridgeJournal, _canonical, _validate,
)
from .developmental_exchange import SyntheticExchange
from .developmental_receiver import SyntheticDurableReceiver
from .developmental_frames import SyntheticFrameSession, _read_exact, _timestamp

ACK_SCHEMA = "athenz.d2.synthetic-delivery-ack/v1"
MAX_ACK_BYTES = 1024
MAX_ACK_COUNT = 10000
_FIELDS = frozenset((
    "schema", "session_id", "sequence", "receiver", "event_id",
    "envelope_sha256", "source_ref", "source_revision", "created_at",
    "signature",
))
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")


class SyntheticDeliveryAck:
    """Only ACK a nonexecuting learner event persisted in the D2 journal.

    Receiver 'athenz' HMAC proves possession of the established synthetic
    frame key, NOT a particular human or operating-system process.
    """

    def __init__(self, session: SyntheticFrameSession, *, enabled: bool = False):
        if not isinstance(session, SyntheticFrameSession):
            raise BridgeError("Delivery ACK requires a synthetic frame session")
        self.session = session
        self.enabled = enabled and session.enabled
        self._issued = 0
        self._accepted = 0
        self._send_failed = False

    def _ensure(self) -> None:
        if not self.enabled:
            raise BridgeError("Synthetic delivery ACK is disabled")

    def _event(self, event: dict) -> bytes:
        if type(event) is not dict:
            raise BridgeError("Signed synthetic learner event required")
        try:
            stamp = datetime.fromisoformat(event["created_at"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise BridgeError("Invalid delivery event timestamp") from exc
        raw = _validate(event, self.session.producer_keys, now=stamp)
        if (event["producer"] != "learner"
                or event["kind"] not in ("action_proposed", "evaluation_receipt")
                or event["namespace"] != "sandbox"
                or event["purpose"] != "adaptive_sandbox"
                or event["scope"] != "proposal_only"):
            raise BridgeError("Delivery receipt can only acknowledge learner proposals")
        self.session._approval(event)
        return raw

    def issue(self, event: dict, journal: SyntheticBridgeJournal) -> dict:
        """Sign only after exact signed event digest is in the durable journal."""
        self._ensure()
        if self._send_failed:
            raise BridgeError("Synthetic ACK sender failed; establish a new session")
        if self._issued >= MAX_ACK_COUNT:
            raise BridgeError("Synthetic ACK session sequence exhausted")
        if (not isinstance(journal, (SyntheticBridgeJournal, SyntheticDurableReceiver))
                or not journal.enabled
                or journal.keys != self.session.producer_keys):
            raise BridgeError("Authenticated durable source journal required")
        raw = self._event(event)
        digest = hashlib.sha256(raw).hexdigest()
        if isinstance(journal, SyntheticDurableReceiver):
            saved_digest = journal.recorded_fingerprint(event)
        else:
            saved = journal.db.execute(
                "SELECT fingerprint FROM bridge_events WHERE event_id=? "
                "AND producer='learner'", (event["event_id"],)).fetchone()
            saved_digest = saved[0] if saved is not None else None
        if saved_digest is None or not hmac.compare_digest(saved_digest, digest):
            raise BridgeError("Learner envelope is not durably journaled")
        message = {
            "schema": ACK_SCHEMA, "session_id": self.session.session_id,
            "sequence": self._issued + 1, "receiver": "athenz",
            "event_id": event["event_id"], "envelope_sha256": digest,
            "source_ref": event["source_ref"],
            "source_revision": event["source_revision"],
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        message["signature"] = hmac.new(
            self.session.frame_keys["athenz"], _canonical(message),
            hashlib.sha256).hexdigest()
        if len(_canonical(message)) > MAX_ACK_BYTES:
            raise BridgeError("Synthetic ACK exceeds length limit")
        self._issued += 1
        return message

    def accept(self, message: dict, exchange: SyntheticExchange, *,
               now: datetime | None = None) -> dict:
        """Verify HMAC, ordering, source and persisted delivery before ACK."""
        self._ensure()
        if (type(message) is not dict or set(message) != _FIELDS
                or len(_canonical(message)) > MAX_ACK_BYTES):
            raise BridgeError("Invalid synthetic ACK fields or size")
        if (message["schema"] != ACK_SCHEMA
                or message["session_id"] != self.session.session_id
                or message["receiver"] != "athenz"):
            raise BridgeError("Wrong synthetic ACK session or receiver")
        if (type(message["sequence"]) is not int
                or message["sequence"] != self._accepted + 1
                or message["sequence"] > MAX_ACK_COUNT):
            raise BridgeError("Replayed or missing delivery ACK sequence")
        for field, pattern in (("event_id", _ID),
                               ("envelope_sha256", _SHA),
                               ("signature", _SHA)):
            if type(message[field]) is not str or not pattern.fullmatch(message[field]):
                raise BridgeError("Malformed synthetic ACK identifier")
        if type(message["source_revision"]) is not int:
            raise BridgeError("Malformed ACK source revision")
        unsigned = {k: v for k, v in message.items() if k != "signature"}
        expected = hmac.new(
            self.session.frame_keys["athenz"], _canonical(unsigned),
            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, message["signature"]):
            raise BridgeError("Synthetic delivery ACK authentication failed")
        _timestamp(message["created_at"], now)
        if not isinstance(exchange, SyntheticExchange) or not exchange.enabled:
            raise BridgeError("Enabled synthetic outbox required")
        row = exchange.db.execute(
            "SELECT signed_json,digest,source_ref,source_revision "
            "FROM d2_outbox WHERE event_id=?", (message["event_id"],)).fetchone()
        if (row is None
                or row[1] != message["envelope_sha256"]
                or row[2] != message["source_ref"]
                or row[3] != message["source_revision"]):
            raise BridgeError("Delivery ACK does not match pending outbox record")
        try:
            event = json.loads(row[0])
        except (TypeError, ValueError) as exc:
            raise BridgeError("Invalid stored learner event") from exc
        if (self._event(event) != row[0].encode("utf-8")
                or hashlib.sha256(row[0].encode("utf-8")).hexdigest() != row[1]):
            raise BridgeError("Stored learner event is not authentic")
        outcome = exchange.acknowledge(
            message["event_id"], message["envelope_sha256"], confirmed=True)
        self._accepted += 1
        return outcome

    def send(self, writer: BinaryIO, event: dict,
             journal: SyntheticBridgeJournal) -> dict:
        """One signed ACK over caller-owned binary stream, flushed in full."""
        self._ensure()
        message = self.issue(event, journal)
        body = _canonical(message)
        packet = struct.pack("!H", len(body)) + body
        try:
            written = writer.write(packet)
        except (OSError, ValueError, AttributeError) as exc:
            self._send_failed = True
            raise BridgeError("Synthetic ACK stream write failed; restart session") from exc
        if written != len(packet):
            self._send_failed = True
            raise BridgeError("Short synthetic ACK stream write; restart session")
        try:
            writer.flush()
        except (OSError, ValueError, AttributeError) as exc:
            self._send_failed = True
            raise BridgeError("Synthetic ACK stream flush failed; restart session") from exc
        return message

    def receive(self, reader: BinaryIO, exchange: SyntheticExchange) -> dict:
        """Read at most one bounded ACK; never permit arbitrary commands."""
        self._ensure()
        size = struct.unpack("!H", _read_exact(reader, 2))[0]
        if size < 1 or size > MAX_ACK_BYTES:
            raise BridgeError("Synthetic ACK wire size is invalid")
        body = _read_exact(reader, size)
        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeError, ValueError) as exc:
            raise BridgeError("Malformed synthetic ACK JSON") from exc
        if _canonical(message) != body:
            raise BridgeError("Synthetic ACK must be canonical JSON")
        return self.accept(message, exchange)
