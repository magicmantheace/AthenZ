"""Private, explicit review registry for synthetic Developmental AI sources.

The human-facing confirm flag is a local API contract, NOT verified user
authentication. It cannot authorize learning from personal data or real actions.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from .developmental_bridge import BridgeError
from .store import private_home_path

_SOURCE = re.compile(r"synthetic:[A-Za-z0-9_-]{1,64}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_MAX_REVISION = 1_000_000
_PURPOSE = "adaptive_sandbox"
_SCOPE = "proposal_only"
_SCHEMA = 1


def _source(ref: str) -> None:
    if type(ref) is not str or not _SOURCE.fullmatch(ref):
        raise BridgeError("Only synthetic source references may be reviewed")


def _review_digest(ref: str, revision: int, decision: str) -> str:
    payload = {
        "schema": "athenz.d2.synthetic-grant/v1", "source_ref": ref,
        "revision": revision, "purpose": _PURPOSE, "scope": _SCOPE,
        "decision": decision,
    }
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")).hexdigest()


class SyntheticSourceRegistry:
    """Opt-in private SQLite synthetic source grants, revisioned and deny-first.

    The persisted grant contains identifiers and status ONLY. There are no
    credentials, owner messages, human memories or unrestricted permissions.
    """

    def __init__(self, home: Path | None = None):
        try:
            self.home = private_home_path(home)
        except ValueError as exc:
            raise BridgeError("Synthetic grants require an outside-Git private home") from exc
        self.home.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.home.is_symlink():
            raise BridgeError("Synthetic grant home cannot be a pointer")
        if os.name != "nt":
            self.home.chmod(0o700)
            if self.home.stat().st_mode & 0o077:
                raise BridgeError("Synthetic grant home must be owner-only")
        self.path = self.home / "d2_synthetic_grants.sqlite3"
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise BridgeError("Synthetic grant database cannot be a pointer")
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=3)
        self.db.execute("PRAGMA busy_timeout=3000")
        self.db.execute("""CREATE TABLE IF NOT EXISTS synthetic_grants (
            source_ref TEXT PRIMARY KEY, revision INTEGER NOT NULL
                CHECK(revision BETWEEN 1 AND 1000000),
            state TEXT NOT NULL CHECK(state IN ('approved','revoked')),
            purpose TEXT NOT NULL CHECK(purpose='adaptive_sandbox'),
            scope TEXT NOT NULL CHECK(scope='proposal_only')
        )""")
        if os.name != "nt":
            self.path.chmod(0o600)
        if self.db.execute("PRAGMA table_info(synthetic_grants)").fetchall() == []:
            raise BridgeError("Synthetic approval schema missing")

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "SyntheticSourceRegistry":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _current(self, source_ref: str):
        return self.db.execute(
            "SELECT revision,state,purpose,scope FROM synthetic_grants "
            "WHERE source_ref=?", (source_ref,)).fetchone()

    def preview(self, source_ref: str, decision: str) -> dict:
        """Return the exact next revision and digest for a separate review step."""
        _source(source_ref)
        if decision not in ("approve", "revoke"):
            raise BridgeError("Only approve or revoke decisions are supported")
        row = self._current(source_ref)
        if decision == "revoke" and (not row or row[1] != "approved"):
            raise BridgeError("Only an approved source can be revoked")
        if decision == "approve" and row and row[1] == "approved":
            raise BridgeError("Revoke an existing approval before reconsideration")
        revision = row[0] + 1 if row else 1
        if revision > _MAX_REVISION:
            raise BridgeError("Synthetic grant revision exhausted")
        return {
            "source_ref": source_ref, "revision": revision, "decision": decision,
            "purpose": _PURPOSE, "scope": _SCOPE,
            "review_sha256": _review_digest(source_ref, revision, decision),
        }

    def review(self, source_ref: str, decision: str, *, review_sha256: str,
               confirmed: bool = False) -> dict:
        """Apply exactly the previewed change only after explicit confirmation."""
        _source(source_ref)
        if (confirmed is not True or type(review_sha256) is not str
                or not _DIGEST.fullmatch(review_sha256)):
            raise BridgeError("Explicit review confirmation and preview digest required")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            preview = self.preview(source_ref, decision)
            if preview["review_sha256"] != review_sha256:
                raise BridgeError("Synthetic review changed; inspect latest revision")
            state = "approved" if decision == "approve" else "revoked"
            self.db.execute(
                "INSERT INTO synthetic_grants VALUES (?,?,?,?,?) "
                "ON CONFLICT(source_ref) DO UPDATE SET "
                "revision=excluded.revision,state=excluded.state,"
                "purpose=excluded.purpose,scope=excluded.scope",
                (source_ref, preview["revision"], state, _PURPOSE, _SCOPE))
            self.db.execute("COMMIT")
            return {
                "source_ref": source_ref, "revision": preview["revision"],
                "state": state, "purpose": _PURPOSE, "scope": _SCOPE,
                "actions_executed": False,
            }
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def is_current(self, source_ref: str, revision: int) -> bool:
        """Fail closed on missing/withdrawn/stale sources, also after restart."""
        if (type(source_ref) is not str or not _SOURCE.fullmatch(source_ref)
                or type(revision) is not int or not 1 <= revision <= _MAX_REVISION):
            return False
        try:
            row = self._current(source_ref)
        except sqlite3.DatabaseError:
            return False
        return bool(row and row == (revision, "approved", _PURPOSE, _SCOPE))

    def status(self, source_ref: str) -> dict:
        """Small owner-facing status without any personal history content."""
        _source(source_ref)
        row = self._current(source_ref)
        return {
            "source_ref": source_ref,
            "revision": row[0] if row else 0,
            "state": row[1] if row else "absent",
            "purpose": _PURPOSE,
            "scope": _SCOPE,
        }
