"""Strict synthetic D2 binary framing for caller-owned stdin/stdout streams.

No network listeners, subprocess launch, device actions, identity data, or
handshake/key provisioning. A caller must establish an independent, fresh
session identifier and protect two directional HMAC keys before use.

Outer frame timestamps authenticate *delivery*, while the already-signed
inner event may be old when retransmitted from the transactional outbox.
Every event remains sandbox-only and proposal-only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import struct
from typing import BinaryIO, Callable, Mapping

from .developmental_bridge import BridgeError, _canonical, _key, _validate

FRAME_SCHEMA = "athenz.d2.stdio-frame/v1"
FRAME_LIMIT = 4096
FRAME_COUNT_LIMIT = 10000
_SESSION_ID = re.compile(r"[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_OUTER_KEYS = frozenset(("schema", "session_id", "sequence", "sent_at",
                         "event", "authentication"))
_INNER_KEYS = _OUTER_KEYS - {"authentication"}


def _timestamp(stamp: str, now: datetime | None = None) -> None:
    try:
        parsed = datetime.fromisoformat(stamp)
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            raise ValueError("not UTC")
        instant = now if now is not None else datetime.now(timezone.utc)
        if abs((instant - parsed).total_seconds()) > 300:
            raise ValueError("outside 5 minute frame window")
    except (ValueError, TypeError, OverflowError) as exc:
        raise BridgeError("Invalid or expired synthetic frame timestamp") from exc


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    """Read a bounded number of bytes; never read until untrusted EOF."""
    output = bytearray()
    while len(output) < size:
        try:
            chunk = stream.read(size - len(output))
        except (OSError, ValueError) as exc:
            raise BridgeError("Synthetic frame stream read failed") from exc
        if type(chunk) is not bytes or not chunk:
            raise BridgeError("Synthetic frame truncated or not binary")
        output.extend(chunk)
    return bytes(output)


class SyntheticFrameSession:
    """Signed, ordered frames on already-open binary streams.

    The caller must negotiate a fresh random session ID and provide keys
    through an independent protected channel. This class does NOT perform
    handshake, authenticate the human, persist counters, or launch a learner.

    Frame sequence fences apply per producer within a session. Restart
    requires a different session ID; durable event dedup is owned by the
    downstream SQLite journal.
    """

    def __init__(self, *, session_id: str,
                 producer_keys: Mapping[str, bytes],
                 frame_keys: Mapping[str, bytes],
                 revision_check: Callable[[str, int], bool],
                 enabled: bool = False):
        if type(session_id) is not str or not _SESSION_ID.fullmatch(session_id):
            raise BridgeError("Synthetic frame requires a 128-bit session identifier")
        if (set(producer_keys) != {"athenz", "learner"}
                or set(frame_keys) != {"athenz", "learner"}
                or not callable(revision_check)):
            raise BridgeError("Separate producer/frame keys and revision checker required")
        for secret in (*producer_keys.values(), *frame_keys.values()):
            _key(secret)
        self.session_id = session_id
        self.producer_keys = dict(producer_keys)
        self.frame_keys = dict(frame_keys)
        self.revision_check = revision_check
        self.enabled = enabled
        self._out_seq = {"athenz": 0, "learner": 0}
        self._in_seq = {"athenz": 0, "learner": 0}
        self._send_broken = False

    def _approval(self, event: dict) -> None:
        try:
            allowed = self.revision_check(
                event["source_ref"], event["source_revision"]) is True
        except Exception as exc:
            raise BridgeError("Synthetic source check failed") from exc
        if not allowed:
            raise BridgeError("Synthetic source approval unavailable")

    def _inner(self, event: dict) -> None:
        # Validate the full original producer signature and D2 allowlist,
        # including an outbox event with a legitimately old creation time.
        try:
            signed_at = datetime.fromisoformat(event["created_at"])
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            raise BridgeError("Invalid signed synthetic event timestamp") from exc
        _validate(event, self.producer_keys, now=signed_at)

    def pack(self, event: dict) -> bytes:
        """Authenticate a fresh delivery frame containing a signed event."""
        if not self.enabled:
            raise BridgeError("Synthetic frame session is disabled")
        if self._send_broken:
            raise BridgeError("Synthetic send session failed; negotiate a new session")
        self._inner(event)
        producer = event["producer"]
        if self._out_seq[producer] >= FRAME_COUNT_LIMIT:
            raise BridgeError("Synthetic send sequence exhausted; rotate session")
        self._approval(event)
        record = {
            "schema": FRAME_SCHEMA, "session_id": self.session_id,
            "sequence": self._out_seq[producer] + 1,
            "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
        }
        record["authentication"] = hmac.new(
            self.frame_keys[producer], _canonical(record),
            hashlib.sha256).hexdigest()
        payload = _canonical(record)
        if len(payload) > FRAME_LIMIT:
            raise BridgeError("Synthetic frame is too large")
        self._out_seq[producer] += 1
        return struct.pack("!I", len(payload)) + payload

    def send(self, stream: BinaryIO, event: dict) -> None:
        """Write exactly one framed event to a caller-owned binary stream.

        A short/broken write invalidates this in-memory session: the caller
        must establish a fresh session and rely on durable event replay.
        """
        packet = self.pack(event)
        try:
            written = stream.write(packet)
        except (OSError, ValueError, AttributeError) as exc:
            self._send_broken = True
            raise BridgeError("Synthetic frame stream write failed; restart session") from exc
        if written != len(packet):
            self._send_broken = True
            raise BridgeError("Short synthetic frame write; restart session")
        try:
            stream.flush()
        except (OSError, ValueError, AttributeError) as exc:
            self._send_broken = True
            raise BridgeError("Synthetic frame stream flush failed; restart session") from exc

    def receive(self, stream: BinaryIO, *, expected_producer: str,
                now: datetime | None = None) -> dict:
        """Verify a single bounded frame; no tool/executable dispatch."""
        if not self.enabled:
            raise BridgeError("Synthetic frame session is disabled")
        if expected_producer not in ("athenz", "learner"):
            raise BridgeError("Expected producer is required")
        size = struct.unpack("!I", _read_exact(stream, 4))[0]
        if size < 1 or size > FRAME_LIMIT:
            raise BridgeError("Synthetic frame size outside allowed range")
        data = _read_exact(stream, size)
        try:
            record = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise BridgeError("Invalid synthetic frame encoding") from exc
        if type(record) is not dict or set(record) != _OUTER_KEYS:
            raise BridgeError("Unsupported synthetic frame fields")
        if _canonical(record) != data:
            raise BridgeError("Synthetic frame is not canonical JSON")
        if (record["schema"] != FRAME_SCHEMA
                or record["session_id"] != self.session_id):
            raise BridgeError("Unsupported or wrong synthetic session")
        if (type(record["sequence"]) is not int
                or record["sequence"] != self._in_seq[expected_producer] + 1
                or record["sequence"] > FRAME_COUNT_LIMIT):
            raise BridgeError("Synthetic frame sequence was replayed or skipped")
        authentication = record["authentication"]
        if (type(authentication) is not str
                or not _SHA256.fullmatch(authentication)):
            raise BridgeError("Invalid synthetic frame authentication")
        unsigned = {k: record[k] for k in _INNER_KEYS}
        expected = hmac.new(
            self.frame_keys[expected_producer], _canonical(unsigned),
            hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, authentication):
            raise BridgeError("Synthetic frame authentication failed")
        _timestamp(record["sent_at"], now)
        event = record["event"]
        self._inner(event)
        if event["producer"] != expected_producer:
            raise BridgeError("Unexpected producer in synthetic frame")
        self._approval(event)
        self._in_seq[expected_producer] += 1
        return event


class SyntheticFramedJournal:
    """Receive into an existing durable, metadata-only D2 journal."""

    def __init__(self, session: SyntheticFrameSession, journal):
        from .developmental_bridge import SyntheticBridgeJournal
        if not isinstance(session, SyntheticFrameSession) or not isinstance(
                journal, SyntheticBridgeJournal):
            raise BridgeError("Expected a synthetic frame session and journal")
        self.session = session
        self.journal = journal

    def receive(self, stream: BinaryIO, *, expected_producer: str) -> dict:
        event = self.session.receive(stream, expected_producer=expected_producer)
        # The journal enforces durable event dedup/revision. It is deliberately
        # independent of the ephemeral frame sequence and session ID.
        return self.journal.receive(event)
