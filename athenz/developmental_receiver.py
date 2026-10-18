"""Durable synthetic D2 framed-event receipt across process restarts.

Only fresh, session-authenticated binary frames may be received. Previously
signed learner envelopes may be old *inside* those frames. This journal stores
minimal identifiers/digests, NEVER real owner data or simulator payloads.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
from typing import BinaryIO, Mapping

from .developmental_bridge import BridgeError, _key, _validate
from .developmental_frames import SyntheticFrameSession
from .store import private_home_path

MAX_RECEIVED = 5000
_RECEIPT = re.compile(r"independently replayed (?:[1-9][0-9]{0,3}) simulator events\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class SyntheticDurableReceiver:
    """Private, opt-in receiver for authenticated synthetic stream frames.

    Its SQLite journal fences event-ID replay and producer/task sequence
    across sessions. No raw signed JSON, personal content or credentials
    are stored. A caller cannot bypass fresh frame authentication through
    a public `receive(event)` shortcut.
    """

    def __init__(self, file: Path, *, keys: Mapping[str, bytes],
                 revision_check, enabled: bool = False):
        if set(keys) != {"athenz", "learner"} or not callable(revision_check):
            raise BridgeError("Durable receiver requires separate producer keys and revision check")
        for key in keys.values():
            _key(key)
        path = Path(file).absolute()
        try:
            private_home_path(path.parent)
        except ValueError as exc:
            raise BridgeError("Receiver database must be outside Git") from exc
        if not path.parent.is_dir() or path.is_symlink() or (
                path.exists() and not path.is_file()):
            raise BridgeError("Receiver requires an existing private database directory")
        if os.name != "nt" and path.parent.stat().st_mode & 0o077:
            raise BridgeError("Receiver directory must be owner-only")
        self.db_file_home = path.parent
        self.keys = dict(keys)
        self.revision_check = revision_check
        self.enabled = enabled
        self.db = sqlite3.connect(path, timeout=3, isolation_level=None)
        self.db.execute("PRAGMA busy_timeout=3000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS d2_framed_received (
            event_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
            producer TEXT NOT NULL CHECK(producer IN ('athenz','learner')),
            task_id TEXT NOT NULL, seq INTEGER NOT NULL,
            source_ref TEXT NOT NULL, source_revision INTEGER NOT NULL,
            kind TEXT NOT NULL, received_at TEXT NOT NULL,
            UNIQUE(producer,task_id,seq))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS d2_framed_stream (
            producer TEXT NOT NULL, task_id TEXT NOT NULL, last_seq INTEGER NOT NULL,
            PRIMARY KEY(producer,task_id))""")
        if os.name != "nt":
            path.chmod(0o600)

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "SyntheticDurableReceiver":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _approval(self, event: dict) -> None:
        try:
            allowed = self.revision_check(
                event["source_ref"], event["source_revision"]) is True
        except Exception as exc:
            raise BridgeError("Durable receiver revision check failed") from exc
        if not allowed:
            raise BridgeError("Durable receiver source is not approved")

    @staticmethod
    def _narrow(event: dict) -> None:
        """Allow only fixed-text proposals/receipts and trace-digest requests."""
        if event["producer"] == "athenz":
            if (event["kind"] != "observation" or event["payload"].get("signal") != "trace_sha256"
                    or not isinstance(event["payload"].get("value"), str)
                    or not _SHA.fullmatch(event["payload"]["value"])):
                raise BridgeError("Unsupported synthetic AthenZ trace reference")
        elif event["producer"] == "learner":
            if event["kind"] == "action_proposed":
                if event["payload"] != {
                    "summary": "synthetic proposal only; no system action"
                }:
                    raise BridgeError("Only fixed non-executable proposal is allowed")
            elif event["kind"] == "evaluation_receipt":
                if not _RECEIPT.fullmatch(event["payload"]["result"]):
                    raise BridgeError("Only fixed simulator receipt is allowed")
            else:
                raise BridgeError("Unsupported synthetic learner event")
        else:
            raise BridgeError("Unknown synthetic event producer")

    def receive_frame(self, session: SyntheticFrameSession, reader: BinaryIO, *,
                      expected_producer: str = "learner",
                      include_event: bool = False,
                      expected_task_id: str | None = None,
                      expected_kind: str | None = None,
                      expected_source_ref: str | None = None,
                      expected_source_revision: int | None = None) -> dict:
        """Persist metadata after verifying fresh frame, signed event and approval."""
        if not self.enabled:
            return {"status": "disabled", "actions_executed": False}
        if type(include_event) is not bool:
            raise BridgeError("Invalid durable receiver event visibility option")
        if not isinstance(session, SyntheticFrameSession):
            raise BridgeError("Durable receiving requires authenticated D2 frame session")
        if session.producer_keys != self.keys:
            raise BridgeError("Durable receiver producer keys differ from session")
        if expected_producer not in ("athenz", "learner"):
            raise BridgeError("Expected receiver producer is invalid")
        for value in (expected_task_id, expected_kind, expected_source_ref):
            if value is not None and (type(value) is not str or not 1 <= len(value) <= 80):
                raise BridgeError("Invalid expected D2 event field")
        if (expected_source_revision is not None
                and (type(expected_source_revision) is not int
                     or not 1 <= expected_source_revision <= 1000000)):
            raise BridgeError("Invalid expected D2 source revision")
        # Session must authenticate a fresh outer frame before the signed
        # *inner* event can be read from an old durable sender outbox.
        event = session.receive(reader, expected_producer=expected_producer)
        if (expected_task_id is not None and event["task_id"] != expected_task_id
                or expected_kind is not None and event["kind"] != expected_kind
                or expected_source_ref is not None and event["source_ref"] != expected_source_ref
                or expected_source_revision is not None
                and event["source_revision"] != expected_source_revision):
            raise BridgeError("Authenticated D2 event does not match expected request")
        self._narrow(event)
        stamp = datetime.fromisoformat(event["created_at"])
        raw = _validate(event, self.keys, now=stamp)
        fingerprint = hashlib.sha256(raw).hexdigest()
        self._approval(event)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._approval(event)
            existing = self.db.execute(
                "SELECT digest FROM d2_framed_received WHERE event_id=?",
                (event["event_id"],)).fetchone()
            if existing:
                if existing[0] != fingerprint:
                    raise BridgeError("Conflicting durable framed event replay")
                self.db.execute("COMMIT")
                return {"status": "duplicate", "actions_executed": False, **({"event": event} if include_event else {})}
            last = self.db.execute(
                "SELECT last_seq FROM d2_framed_stream WHERE producer=? AND task_id=?",
                (event["producer"], event["task_id"])).fetchone()
            required = last[0] + 1 if last else 1
            if event["seq"] != required:
                raise BridgeError("Durable receiver event sequence missing or replayed")
            if self.db.execute(
                    "SELECT count(*) FROM d2_framed_received").fetchone()[0] >= MAX_RECEIVED:
                raise BridgeError("Durable receiver has reached its bounded capacity")
            self.db.execute(
                "INSERT INTO d2_framed_received VALUES (?,?,?,?,?,?,?,?,?)",
                (event["event_id"], fingerprint, event["producer"],
                 event["task_id"], event["seq"], event["source_ref"],
                 event["source_revision"], event["kind"],
                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
            self.db.execute(
                "INSERT INTO d2_framed_stream VALUES (?,?,?) "
                "ON CONFLICT(producer,task_id) DO UPDATE SET last_seq=excluded.last_seq",
                (event["producer"], event["task_id"], event["seq"]))
            self._approval(event)
            self.db.execute("COMMIT")
            return {"status": "accepted", "actions_executed": False, **({"event": event} if include_event else {})}
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def recorded_fingerprint(self, event: dict) -> str | None:
        """Return a fingerprint only for currently authorized matching events."""
        if not self.enabled:
            return None
        self._narrow(event)
        stamp = datetime.fromisoformat(event["created_at"])
        raw = _validate(event, self.keys, now=stamp)
        self._approval(event)
        row = self.db.execute(
            "SELECT digest,source_ref,source_revision,producer FROM d2_framed_received "
            "WHERE event_id=?", (event["event_id"],)).fetchone()
        digest = hashlib.sha256(raw).hexdigest()
        if row and row == (digest, event["source_ref"],
                           event["source_revision"], event["producer"]):
            return row[0]
        return None
