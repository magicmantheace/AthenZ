"""Synthetic-only, non-executing Developmental AI D2 bridge prototype.

This module is an AthenZ-side contract fixture, NOT a network transport, tool
controller, real consent service or production authentication implementation.
Never feed private user content into its synthetic:* source namespace.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable, Mapping
from uuid import uuid4


SCHEMA_VERSION = 1
MAX_ENVELOPE_BYTES = 2048
MAX_CLOCK_SKEW_SECONDS = 300
_PRODUCERS = {
    "athenz": {
        "observation": "human_record",
        "outcome": "agent_experience",
        "revocation": "system_telemetry",
        "pause": "system_telemetry",
        "resume": "system_telemetry",
    },
    "learner": {
        "goal_proposed": "simulation_episode",
        "action_proposed": "simulation_episode",
        "checkpoint": "simulation_episode",
        "learning_candidate": "simulation_episode",
        "evaluation_receipt": "simulation_episode",
    },
}
_PAYLOADS = {
    "observation": {"signal": str, "value": str},
    "outcome": {"accepted": bool, "result": str},
    "revocation": {"reason": str},
    "pause": {"reason": str},
    "resume": {"reason": str},
    "goal_proposed": {"summary": str},
    "action_proposed": {"summary": str},
    "checkpoint": {"checkpoint_id": str},
    "learning_candidate": {"candidate_id": str},
    "evaluation_receipt": {"result": str},
}
_FIELDS = frozenset({
    "schema_version", "event_id", "producer", "task_id", "seq", "origin",
    "namespace", "purpose", "scope", "source_ref", "source_revision",
    "kind", "payload", "created_at", "signature",
})
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_SOURCE = re.compile(r"synthetic:[A-Za-z0-9_-]{1,64}\Z")
_EVENT = re.compile(r"[0-9a-f]{32}\Z")
_SIGNATURE = re.compile(r"[0-9a-f]{64}\Z")


class BridgeError(ValueError):
    """Reject unsupported or untrusted event metadata without disclosing data."""


def _canonical(event: dict) -> bytes:
    try:
        return json.dumps(event, sort_keys=True, ensure_ascii=False,
                          allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise BridgeError("Invalid event encoding") from exc


def _key(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) < 32:
        raise BridgeError("A per-producer 32-byte secret is required")


def _validate(event: dict, keys: Mapping[str, bytes], *,
              now: datetime | None = None) -> bytes:
    if not isinstance(event, dict) or set(event) != _FIELDS:
        raise BridgeError("Unsupported bridge envelope fields")
    body = _canonical(event)
    if len(body) > MAX_ENVELOPE_BYTES:
        raise BridgeError("Bridge envelope exceeds size limit")
    if type(event["schema_version"]) is not int or event["schema_version"] != SCHEMA_VERSION:
        raise BridgeError("Unsupported bridge schema")
    for field, pattern in (("event_id", _EVENT), ("task_id", _TOKEN),
                           ("source_ref", _SOURCE), ("signature", _SIGNATURE)):
        value = event[field]
        if not isinstance(value, str) or not pattern.fullmatch(value):
            raise BridgeError("Invalid bridge identifier")
    if (type(event["seq"]) is not int or not 1 <= event["seq"] <= 10000
            or type(event["source_revision"]) is not int
            or not 1 <= event["source_revision"] <= 1000000):
        raise BridgeError("Invalid bridge sequence or source revision")
    if (event["namespace"] != "sandbox" or event["purpose"] != "adaptive_sandbox"
            or event["scope"] != "proposal_only"):
        raise BridgeError("Bridge scope is not permitted")
    producer, kind, origin = event["producer"], event["kind"], event["origin"]
    if (not isinstance(producer, str) or producer not in _PRODUCERS
            or not isinstance(kind, str)
            or _PRODUCERS[producer].get(kind) != origin):
        raise BridgeError("Producer cannot assert this origin or event kind")
    expected = _PAYLOADS[kind]
    payload = event["payload"]
    if not isinstance(payload, dict) or set(payload) != set(expected):
        raise BridgeError("Unsupported bridge payload")
    for name, typ in expected.items():
        value = payload[name]
        if type(value) is not typ:
            raise BridgeError("Invalid bridge payload type")
        if typ is str and (not 1 <= len(value) <= 160
                           or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise BridgeError("Invalid bridge payload text")
    try:
        stamp = datetime.fromisoformat(event["created_at"])
        if stamp.tzinfo is None or stamp.utcoffset() != timezone.utc.utcoffset(stamp):
            raise ValueError("not UTC")
        current = now or datetime.now(timezone.utc)
        if abs((current - stamp).total_seconds()) > MAX_CLOCK_SKEW_SECONDS:
            raise BridgeError("Bridge event timestamp is stale or in the future")
    except (TypeError, ValueError, OverflowError) as exc:
        raise BridgeError("Invalid bridge timestamp") from exc
    key = keys.get(producer)
    _key(key)
    unsigned = {field: event[field] for field in _FIELDS if field != "signature"}
    valid = hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(valid, event["signature"]):
        raise BridgeError("Bridge producer authentication failed")
    return body


def synthetic_event(*, producer: str, task_id: str, seq: int, kind: str,
                    source_ref: str, source_revision: int, payload: dict,
                    secret: bytes, created_at: str | None = None) -> dict:
    """Sign one synthetic fixture, never a production permission or consent."""
    _key(secret)
    if producer not in _PRODUCERS or kind not in _PRODUCERS[producer]:
        raise BridgeError("Unsupported producer event kind")
    event = {
        "schema_version": SCHEMA_VERSION, "event_id": uuid4().hex,
        "producer": producer, "task_id": task_id, "seq": seq, "kind": kind,
        "origin": _PRODUCERS[producer][kind], "namespace": "sandbox",
        "purpose": "adaptive_sandbox", "scope": "proposal_only",
        "source_ref": source_ref, "source_revision": source_revision,
        "payload": payload,
        "created_at": created_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    event["signature"] = hmac.new(secret, _canonical(event), hashlib.sha256).hexdigest()
    return event


class SyntheticBridgeJournal:
    """Persist metadata-only replay fences; never save payloads or issue actions."""

    def __init__(self, db_path: Path, *, keys: Mapping[str, bytes],
                 consent_check: Callable[[str, int], bool], enabled: bool = False):
        if set(keys) != set(_PRODUCERS) or not callable(consent_check):
            raise BridgeError("Explicit producer secrets and consent checker required")
        for key in keys.values():
            _key(key)
        path = Path(db_path)
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise BridgeError("Bridge journal path must be a regular private file")
        if not path.parent.is_dir():
            raise BridgeError("Create the private bridge directory before use")
        self.keys = dict(keys)
        self.consent_check = consent_check
        self.enabled = enabled
        self.db = sqlite3.connect(path, timeout=3, isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=3000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS bridge_events (
            event_id TEXT PRIMARY KEY, producer TEXT NOT NULL, task_id TEXT NOT NULL,
            seq INTEGER NOT NULL, fingerprint TEXT NOT NULL,
            UNIQUE(producer, task_id, seq))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS bridge_revisions (
            producer TEXT NOT NULL, task_id TEXT NOT NULL, last_seq INTEGER NOT NULL,
            PRIMARY KEY(producer, task_id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS bridge_revoked (
            source_ref TEXT PRIMARY KEY, source_revision INTEGER NOT NULL)""")

    def close(self) -> None:
        self.db.close()

    def receive(self, event: dict) -> dict:
        """Return accepted/duplicate/disabled. Everything else fails closed."""
        if not self.enabled:
            return {"status": "disabled", "actions_executed": False}
        body = _validate(event, self.keys)
        fingerprint = hashlib.sha256(body).hexdigest()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            source = event["source_ref"]
            revoked = self.db.execute(
                "SELECT source_revision FROM bridge_revoked WHERE source_ref=?",
                (source,)).fetchone()
            if revoked and event["kind"] != "revocation":
                raise BridgeError("Bridge source was revoked")
            existing = self.db.execute(
                "SELECT fingerprint FROM bridge_events WHERE event_id=?",
                (event["event_id"],)).fetchone()
            if existing:
                if existing[0] != fingerprint:
                    raise BridgeError("Conflicting event replay")
                self.db.execute("COMMIT")
                return {"status": "duplicate", "actions_executed": False}
            last = self.db.execute(
                "SELECT last_seq FROM bridge_revisions WHERE producer=? AND task_id=?",
                (event["producer"], event["task_id"])).fetchone()
            if event["seq"] != (last[0] + 1 if last else 1):
                raise BridgeError("Bridge event sequence is missing or replayed")
            # This callback is a fixture boundary, not an authority. Actual
            # production consent must be sourced and rechecked from AthenZ.
            if event["kind"] != "revocation":
                try:
                    valid = self.consent_check(source, event["source_revision"]) is True
                except Exception as exc:
                    raise BridgeError("Bridge consent check failed") from exc
                if not valid:
                    raise BridgeError("Bridge source lacks current approval")
            self.db.execute(
                "INSERT INTO bridge_events VALUES (?,?,?,?,?)",
                (event["event_id"], event["producer"], event["task_id"],
                 event["seq"], fingerprint))
            self.db.execute(
                "INSERT INTO bridge_revisions VALUES (?,?,?) "
                "ON CONFLICT(producer,task_id) DO UPDATE SET last_seq=excluded.last_seq",
                (event["producer"], event["task_id"], event["seq"]))
            if event["kind"] == "revocation":
                if revoked and event["source_revision"] < revoked[0]:
                    raise BridgeError("Revocation revision must not regress")
                self.db.execute(
                    "INSERT INTO bridge_revoked VALUES (?,?) "
                    "ON CONFLICT(source_ref) DO UPDATE SET source_revision=excluded.source_revision",
                    (source, event["source_revision"]))
            self.db.execute("COMMIT")
            return {"status": "accepted", "actions_executed": False}
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
