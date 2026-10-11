"""Reviewable local identity store: approval, source provenance, revisions and deletion."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

KINDS = frozenset({"identity", "style", "value", "preference", "knowledge", "skill", "lesson"})
STATES = frozenset({"pending", "approved", "rejected"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_home() -> Path:
    return Path(os.environ.get("ATHENZ_HOME", str(Path.home() / ".athenz"))).expanduser()


class IdentityStore:
    """Private SQLite source of truth. Unapproved data never enters prompt context."""

    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home is not None else default_home()
        self.home.mkdir(parents=True, exist_ok=True)
        try:
            self.home.chmod(0o700)
        except OSError:
            pass
        self.path = self.home / "identity.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        self._migrate()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _migrate(self) -> None:
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError(f"Database schema v{version} is newer than this application")
        if version == 0:
            with self.db:
                self.db.executescript("""
                CREATE TABLE identity (
                    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, text TEXT NOT NULL,
                    source TEXT NOT NULL, source_ref TEXT NOT NULL DEFAULT '',
                    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE identity_revisions (
                    id INTEGER PRIMARY KEY, identity_id INTEGER NOT NULL,
                    prior_text TEXT NOT NULL, new_text TEXT NOT NULL,
                    reason TEXT NOT NULL, changed_at TEXT NOT NULL
                );
                CREATE TABLE decisions (
                    id INTEGER PRIMARY KEY, scenario TEXT NOT NULL, choice TEXT NOT NULL,
                    rationale TEXT NOT NULL, exception TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL, source_ref TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE writing_samples (
                    id INTEGER PRIMARY KEY, text TEXT NOT NULL, source TEXT NOT NULL,
                    source_ref TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
                );
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY, operation TEXT NOT NULL, subject_type TEXT NOT NULL,
                    subject_id INTEGER, created_at TEXT NOT NULL
                );
                CREATE INDEX idx_identity_status ON identity(status,kind);
                CREATE INDEX idx_decisions_status ON decisions(status);
                CREATE INDEX idx_samples_source ON writing_samples(source,source_ref);
                PRAGMA user_version = 1;
                """)

    def _event(self, operation: str, subject_type: str, subject_id: int | None) -> None:
        # Intentionally exclude personal content; deletion must not leave it in event logs.
        self.db.execute("INSERT INTO events(operation,subject_type,subject_id,created_at) VALUES (?,?,?,?)",
                        (operation, subject_type, subject_id, utc_now()))

    def propose(self, kind: str, text: str, *, source: str, source_ref: str = "",
                confidence: float = 1.0, approved: bool = False) -> int:
        if kind not in KINDS:
            raise ValueError(f"Invalid kind: {kind}")
        if not text.strip() or not source.strip():
            raise ValueError("Text and provenance source are required")
        if not 0 <= confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        time = utc_now()
        with self.db:
            cur = self.db.execute("""INSERT INTO identity
              (kind,text,source,source_ref,confidence,status,created_at,updated_at)
              VALUES (?,?,?,?,?,?,?,?)""", (kind, text.strip(), source, source_ref, confidence,
                                             "approved" if approved else "pending", time, time))
            self._event("created", "identity", cur.lastrowid)
        return int(cur.lastrowid)

    def status(self, item_id: int, status: str) -> bool:
        if status not in STATES:
            raise ValueError("Invalid approval state")
        with self.db:
            cur = self.db.execute("UPDATE identity SET status=?,updated_at=? WHERE id=?",
                                  (status, utc_now(), item_id))
            if cur.rowcount:
                self._event(f"status:{status}", "identity", item_id)
        return bool(cur.rowcount)

    def revise(self, item_id: int, text: str, reason: str) -> bool:
        if not text.strip() or not reason.strip():
            raise ValueError("Replacement text and revision reason are required")
        with self.db:
            old = self.db.execute("SELECT text FROM identity WHERE id=?", (item_id,)).fetchone()
            if old is None:
                return False
            self.db.execute("""INSERT INTO identity_revisions(identity_id,prior_text,new_text,reason,changed_at)
                             VALUES (?,?,?,?,?)""", (item_id, old["text"], text.strip(), reason, utc_now()))
            self.db.execute("UPDATE identity SET text=?,status='pending',updated_at=? WHERE id=?",
                            (text.strip(), utc_now(), item_id))
            self._event("revised", "identity", item_id)
        return True

    def delete(self, table: str, item_id: int) -> bool:
        if table not in {"identity", "decisions", "writing_samples"}:
            raise ValueError("Unsupported deletion table")
        with self.db:
            if table == "identity":
                self.db.execute("DELETE FROM identity_revisions WHERE identity_id=?", (item_id,))
            cur = self.db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
            if cur.rowcount:
                self._event("deleted", table, item_id)
        return bool(cur.rowcount)

    def add_decision(self, scenario: str, choice: str, rationale: str, *, source: str,
                     exception: str = "", source_ref: str = "", approved: bool = False) -> int:
        if not all(s.strip() for s in (scenario, choice, rationale, source)):
            raise ValueError("Scenario, choice, rationale and source are required")
        with self.db:
            cur = self.db.execute("""INSERT INTO decisions
              (scenario,choice,rationale,exception,source,source_ref,status,created_at)
              VALUES (?,?,?,?,?,?,?,?)""", (scenario, choice, rationale, exception, source,
                                             source_ref, "approved" if approved else "pending", utc_now()))
            self._event("created", "decisions", cur.lastrowid)
        return int(cur.lastrowid)

    def decision_status(self, item_id: int, status: str) -> bool:
        if status not in STATES:
            raise ValueError("Invalid approval state")
        with self.db:
            cur = self.db.execute("UPDATE decisions SET status=? WHERE id=?", (status, item_id))
            if cur.rowcount:
                self._event(f"status:{status}", "decisions", item_id)
        return bool(cur.rowcount)

    def add_sample(self, text: str, *, source: str, source_ref: str = "") -> int:
        if not text.strip() or not source.strip():
            raise ValueError("Text and source required")
        with self.db:
            cur = self.db.execute("""INSERT INTO writing_samples(text,source,source_ref,created_at)
                                     VALUES (?,?,?,?)""", (text, source, source_ref, utc_now()))
            self._event("created", "writing_samples", cur.lastrowid)
        return int(cur.lastrowid)

    def purge_source(self, source: str, source_ref: str = "") -> dict[str, int]:
        """Remove items from one exact source; don't silently purge similarly named sources."""
        if not source.strip():
            raise ValueError("Source must not be blank")
        counts = {}
        with self.db:
            for table in ("identity", "decisions", "writing_samples"):
                if table == "identity":
                    self.db.execute("""DELETE FROM identity_revisions WHERE identity_id IN
                      (SELECT id FROM identity WHERE source=? AND source_ref=?)""", (source, source_ref))
                cur = self.db.execute(f"DELETE FROM {table} WHERE source=? AND source_ref=?",
                                      (source, source_ref))
                counts[table] = cur.rowcount
            self._event("source-purged", "source", None)
        return counts

    def list_items(self, table: str, status: str | None = None, limit: int = 200) -> list[dict]:
        if table not in {"identity", "decisions", "writing_samples", "events", "identity_revisions"}:
            raise ValueError("Unsupported table")
        if status is not None and table not in {"identity", "decisions"}:
            raise ValueError("This table does not contain status")
        if status is not None and status not in STATES:
            raise ValueError("Invalid status")
        query = f"SELECT * FROM {table}"
        args = []
        if status is not None:
            query += " WHERE status=?"
            args.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        return [dict(row) for row in self.db.execute(query, (*args, limit)).fetchall()]

    def context(self) -> dict:
        return {
            "identity": self.list_items("identity", "approved"),
            "decisions": self.list_items("decisions", "approved"),
        }

    def export(self) -> dict:
        """Private export; caller is responsible for secure destination and backup."""
        return {"schema": 1, "identity": self.list_items("identity"),
                "identity_revisions": self.list_items("identity_revisions"),
                "decisions": self.list_items("decisions"),
                "writing_samples": self.list_items("writing_samples")}

    def close(self) -> None:
        self.db.close()
