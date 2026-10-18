"""Durable, synthetic-only AthenZ D2 request/reply staging.

No socket, learner process, filesystem command, production consent or runtime
actuation. Two signed, deliberately generic learner replies are committed with
one synthetic request in *one SQLite transaction*. Replay is at-least-once;
a receiver must independently de-duplicate and authenticate each envelope.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Callable, Mapping

from .developmental_bridge import BridgeError, _validate, _key
from .store import private_home_path

MAX_PENDING = 256
MAX_FETCH = 20
MAX_STORED_EVENTS = 5000
_RECEIPT = re.compile(r"independently replayed (?:[1-9][0-9]{0,3}) simulator events\Z")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class SyntheticExchange:
    """Opt-in transactional synthetic request/outbox journal.

    The revision-check callback is intentionally an injectable test boundary,
    NOT an authenticated owner-consent service. Envelopes must contain only
    synthetic identifiers and the fixed generic learner response wording.
    """

    def __init__(self, file: Path, *, keys: Mapping[str, bytes],
                 revision_check: Callable[[str, int], bool],
                 enabled: bool = False):
        if set(keys) != {"athenz", "learner"} or not callable(revision_check):
            raise BridgeError("Exchange requires two test keys and a revision checker")
        for key in keys.values():
            _key(key)
        path = Path(file).absolute()
        try:
            private_home_path(path.parent)  # Reject Git trees and pointer ancestors.
        except ValueError as exc:
            raise BridgeError("Exchange requires an outside-Git private home") from exc
        if not path.parent.is_dir() or path.is_symlink() or (
                path.exists() and not path.is_file()):
            raise BridgeError("Exchange requires an existing private parent directory")
        self.db_file_home = path.parent
        self.keys = dict(keys)
        self.revision_check = revision_check
        self.enabled = enabled
        self.db = sqlite3.connect(path, timeout=3, isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=3000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS d2_ingress (
            event_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
            producer TEXT NOT NULL, task_id TEXT NOT NULL, seq INTEGER NOT NULL,
            UNIQUE(producer, task_id, seq))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS d2_outbox (
            event_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
            request_id TEXT NOT NULL, source_ref TEXT NOT NULL,
            source_revision INTEGER NOT NULL, signed_json TEXT NOT NULL,
            state TEXT NOT NULL CHECK(state IN ('pending','acked','revoked')),
            FOREIGN KEY(request_id) REFERENCES d2_ingress(event_id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS d2_stream (
            producer TEXT NOT NULL, task_id TEXT NOT NULL, seq INTEGER NOT NULL,
            PRIMARY KEY(producer, task_id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS d2_revoked (
            source_ref TEXT PRIMARY KEY, revision INTEGER NOT NULL)""")
        self.db.execute("PRAGMA foreign_keys=ON")

    @classmethod
    def from_registry(cls, file: Path, *, keys: Mapping[str, bytes],
                      registry: "SyntheticSourceRegistry",
                      enabled: bool = False) -> "SyntheticExchange":
        """Use the private reviewed synthetic source registry, never a lax stub.

        The test HMAC keys still do not authenticate the owner. Callers are
        responsible for keeping the registry open for the exchange's lifetime.
        """
        from .developmental_consent import SyntheticSourceRegistry
        if not isinstance(registry, SyntheticSourceRegistry):
            raise BridgeError("A private synthetic source registry is required")
        path = Path(file).absolute()
        if path.parent != registry.home:
            raise BridgeError("Keep the synthetic outbox in the same private home")
        return cls(path, keys=keys,
                   revision_check=registry.is_current, enabled=enabled)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "SyntheticExchange":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _consent(self, source: str, revision: int) -> None:
        try:
            approved = self.revision_check(source, revision) is True
        except Exception as exc:
            raise BridgeError("Synthetic source revision check failed") from exc
        if not approved:
            raise BridgeError("Synthetic source is no longer approved")

    def _not_revoked(self, source: str) -> None:
        if self.db.execute(
                "SELECT 1 FROM d2_revoked WHERE source_ref=?", (source,)
        ).fetchone():
            raise BridgeError("Synthetic source is revoked")

    def _insert(self, event: dict, raw: bytes) -> None:
        previous = self.db.execute(
            "SELECT seq FROM d2_stream WHERE producer=? AND task_id=?",
            (event["producer"], event["task_id"])).fetchone()
        required = previous[0] + 1 if previous else 1
        if event["seq"] != required:
            raise BridgeError("Synthetic event sequence is missing or replayed")
        if self.db.execute(
                "SELECT 1 FROM d2_ingress WHERE event_id=? "
                "UNION SELECT 1 FROM d2_outbox WHERE event_id=?",
                (event["event_id"], event["event_id"])).fetchone():
            raise BridgeError("Duplicate cross-stream event identifier")
        self.db.execute(
            "INSERT INTO d2_ingress VALUES (?,?,?,?,?)",
            (event["event_id"], _digest(raw), event["producer"],
             event["task_id"], event["seq"]))
        self.db.execute(
            "INSERT INTO d2_stream VALUES (?,?,?) "
            "ON CONFLICT(producer,task_id) DO UPDATE SET seq=excluded.seq",
            (event["producer"], event["task_id"], event["seq"]))

    def _stage_reply(self, event: dict, raw: bytes, request_id: str) -> None:
        previous = self.db.execute(
            "SELECT seq FROM d2_stream WHERE producer=? AND task_id=?",
            (event["producer"], event["task_id"])).fetchone()
        required = previous[0] + 1 if previous else 1
        if event["seq"] != required:
            raise BridgeError("Synthetic reply sequence is missing or replayed")
        if self.db.execute(
                "SELECT 1 FROM d2_ingress WHERE event_id=? "
                "UNION SELECT 1 FROM d2_outbox WHERE event_id=?",
                (event["event_id"], event["event_id"])).fetchone():
            raise BridgeError("Duplicate cross-stream event identifier")
        self.db.execute(
            "INSERT INTO d2_outbox VALUES (?,?,?,?,?,?,?)",
            (event["event_id"], _digest(raw), request_id,
             event["source_ref"], event["source_revision"],
             raw.decode("utf-8"), "pending"))
        self.db.execute(
            "INSERT INTO d2_stream VALUES (?,?,?) "
            "ON CONFLICT(producer,task_id) DO UPDATE SET seq=excluded.seq",
            (event["producer"], event["task_id"], event["seq"]))

    def stage_pair(self, request: dict, proposal: dict, receipt: dict) -> dict:
        """Atomically commit one trace reference and two signed generic replies."""
        if not self.enabled:
            return {"status": "disabled", "actions_executed": False}
        input_raw = _validate(request, self.keys)
        proposal_raw = _validate(proposal, self.keys)
        receipt_raw = _validate(receipt, self.keys)
        if (request["producer"] != "athenz" or request["kind"] != "observation"
                or request["payload"].get("signal") != "trace_sha256"
                or not re.fullmatch(r"[a-f0-9]{64}", request["payload"]["value"])):
            raise BridgeError("Only synthetic trace reference requests are supported")
        if (proposal["producer"] != "learner"
                or proposal["kind"] != "action_proposed"
                or proposal["payload"] != {
                    "summary": "synthetic proposal only; no system action"}
                or receipt["producer"] != "learner"
                or receipt["kind"] != "evaluation_receipt"
                or not _RECEIPT.fullmatch(receipt["payload"]["result"])):
            raise BridgeError("Only generic non-executable simulator replies are supported")
        for reply in (proposal, receipt):
            if (reply["task_id"], reply["source_ref"],
                    reply["source_revision"]) != (
                    request["task_id"], request["source_ref"],
                    request["source_revision"]):
                raise BridgeError("Synthetic reply is not bound to its request")
        if receipt["seq"] != proposal["seq"] + 1:
            raise BridgeError("Synthetic reply sequence is not consecutive")
        source, revision = request["source_ref"], request["source_revision"]
        self._consent(source, revision)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._not_revoked(source)
            self._consent(source, revision)
            old = self.db.execute(
                "SELECT digest FROM d2_ingress WHERE event_id=?",
                (request["event_id"],)).fetchone()
            if old:
                if old[0] != _digest(input_raw):
                    raise BridgeError("Conflicting synthetic request replay")
                queued = self.db.execute(
                    "SELECT count(*) FROM d2_outbox WHERE request_id=?",
                    (request["event_id"],)).fetchone()[0]
                if queued != 2:
                    raise BridgeError("Previously staged reply pair is incomplete")
                self.db.execute("COMMIT")
                return {"status": "duplicate", "actions_executed": False}
            if self.db.execute("SELECT count(*) FROM d2_ingress").fetchone()[0] >= MAX_STORED_EVENTS:
                raise BridgeError("Synthetic exchange has reached its event limit")
            if self.db.execute(
                    "SELECT count(*) FROM d2_outbox WHERE state='pending'"
            ).fetchone()[0] > MAX_PENDING - 2:
                raise BridgeError("Synthetic reply backlog is full")
            self._insert(request, input_raw)
            self._stage_reply(proposal, proposal_raw, request["event_id"])
            self._stage_reply(receipt, receipt_raw, request["event_id"])
            self._consent(source, revision)
            self._not_revoked(source)
            self.db.execute("COMMIT")
            return {"status": "staged", "actions_executed": False}
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def receive_revocation(self, event: dict) -> dict:
        """Fence all pending deliveries after an authenticated synthetic revoke."""
        if not self.enabled:
            return {"status": "disabled", "actions_executed": False}
        raw = _validate(event, self.keys)
        if event["producer"] != "athenz" or event["kind"] != "revocation":
            raise BridgeError("Only AthenZ may revoke a synthetic source")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute(
                "SELECT digest FROM d2_ingress WHERE event_id=?",
                (event["event_id"],)).fetchone()
            if prior:
                if prior[0] != _digest(raw):
                    raise BridgeError("Conflicting synthetic revocation replay")
                self.db.execute("COMMIT")
                return {"status": "duplicate", "actions_executed": False}
            old = self.db.execute(
                "SELECT revision FROM d2_revoked WHERE source_ref=?",
                (event["source_ref"],)).fetchone()
            if old and event["source_revision"] < old[0]:
                raise BridgeError("Synthetic revocation revision cannot regress")
            self._insert(event, raw)
            self.db.execute(
                "INSERT INTO d2_revoked VALUES (?,?) ON CONFLICT(source_ref) "
                "DO UPDATE SET revision=excluded.revision",
                (event["source_ref"], event["source_revision"]))
            self.db.execute(
                "UPDATE d2_outbox SET state='revoked' WHERE source_ref=? "
                "AND state='pending'", (event["source_ref"],))
            self.db.execute("COMMIT")
            return {"status": "revoked", "actions_executed": False}
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def pending(self, *, limit: int = MAX_FETCH) -> list[dict]:
        """Re-authenticate stored synthetic envelopes, checking consent at read."""
        if not self.enabled:
            return []
        if type(limit) is not int or not 1 <= limit <= MAX_FETCH:
            raise BridgeError("Invalid synthetic pending limit")
        self.db.execute("BEGIN")
        try:
            rows = self.db.execute(
                "SELECT signed_json,digest,source_ref,source_revision FROM d2_outbox "
                "WHERE state='pending' ORDER BY rowid LIMIT ?", (limit,)).fetchall()
            events = []
            for raw, digest, source, revision in rows:
                if _digest(raw.encode("utf-8")) != digest:
                    raise BridgeError("Stored synthetic reply was modified")
                try:
                    event = json.loads(raw)
                    stamp = datetime.fromisoformat(event["created_at"])
                except (ValueError, TypeError, KeyError) as exc:
                    raise BridgeError("Invalid stored synthetic reply") from exc
                # Signed at staging; an old timestamp is permitted on durable
                # redelivery after restart, but its original UTC fields/signature
                # must remain cryptographically intact.
                _validate(event, self.keys, now=stamp)
                self._not_revoked(source)
                self._consent(source, revision)
                events.append(event)
            self.db.execute("COMMIT")
            return events
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def acknowledge(self, event_id: str, fingerprint: str, *,
                    confirmed: bool = False) -> dict:
        """Caller-attested delivery acknowledgment, not remote authenticated ACK."""
        if not self.enabled:
            return {"status": "disabled", "actions_executed": False}
        if (confirmed is not True or not isinstance(event_id, str)
                or not re.fullmatch(r"[a-f0-9]{32}", event_id)
                or not isinstance(fingerprint, str)
                or not re.fullmatch(r"[a-f0-9]{64}", fingerprint)):
            raise BridgeError("Explicit synthetic delivery confirmation and digest required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute(
                "SELECT digest,state,source_ref,source_revision FROM d2_outbox "
                "WHERE event_id=?", (event_id,)).fetchone()
            if row is None or row[0] != fingerprint:
                raise BridgeError("Synthetic delivery fingerprint does not match")
            if row[1] == "acked":
                self.db.execute("COMMIT")
                return {"status": "duplicate", "actions_executed": False}
            if row[1] != "pending":
                raise BridgeError("Revoked synthetic message cannot be acknowledged")
            self._not_revoked(row[2])
            self._consent(row[2], row[3])
            self.db.execute(
                "UPDATE d2_outbox SET state='acked' WHERE event_id=?",
                (event_id,))
            self.db.execute("COMMIT")
            return {"status": "acked", "actions_executed": False}
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
