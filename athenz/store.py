"""Reviewable identity store. No personal data is written to the source repository."""
from __future__ import annotations

import json
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


def private_home_path(home: Path | None = None) -> Path:
    """Validate private SQLite storage BEFORE creating directories or files.

    Refuse source checkouts and symlinked ancestors to prevent accidentally
    committing personal memory, and reject existing DB/WAL pointers. This
    guards common configuration mistakes but is not an atomic filesystem
    sandbox against a concurrent hostile process replacing path components.
    """
    raw = Path(home if home is not None else default_home()).expanduser().absolute()
    if any(path.is_symlink() or getattr(path, 'is_junction', lambda: False)()
           for path in (raw, *raw.parents)):
        raise ValueError('AthenZ private profile cannot use symlinks or junctions')
    if any((path / '.git').exists() or (path / '.git').is_symlink()
           for path in (raw, *raw.parents)):
        raise ValueError('AthenZ private profile cannot be stored inside a Git checkout')
    for filename in ('identity.sqlite3', 'identity.sqlite3-wal', 'identity.sqlite3-shm'):
        path = raw / filename
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('AthenZ SQLite database or sidecar cannot be a pointer')
    return raw


class IdentityStore:
    """SQLite source-of-truth with provenance, revision history and explicit approval."""

    def __init__(self, home: Path | None = None):
        self.home = private_home_path(home)
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.home.chmod(0o700)
        except OSError:
            pass
        if os.name != 'nt' and self.home.stat().st_mode & 0o077:
            raise ValueError('AthenZ private profile permissions are not owner-only')
        self.path = self.home / "identity.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.execute("PRAGMA journal_mode = WAL")
        # Deleted personal content is zeroed in the b-tree at deletion time;
        # scrub_erased_content() removes the copies deletion leaves behind
        # in freelist pages and the write-ahead log.
        self.db.execute("PRAGMA secure_delete = ON")
        self._migrate()
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _migrate(self) -> None:
        # Never blindly ALTER a live database or silently rewrite private records.
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 6:
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

        from .migrations import migrate_v2, migrate_v3, migrate_v4, migrate_v5, migrate_v6
        migrate_v2(self.db)
        migrate_v3(self.db)
        migrate_v4(self.db)
        migrate_v5(self.db)
        migrate_v6(self.db)

    def _event(self, operation: str, subject_type: str, subject_id: int | None) -> None:
        # Deliberately exclude content from event logs so deleting content truly removes it.
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
            # Owner correction must be reviewed again; previous approval does not transfer.
            self.db.execute("UPDATE identity SET text=?,status='pending',updated_at=? WHERE id=?",
                            (text.strip(), utc_now(), item_id))
            self._event("revised", "identity", item_id)
        return True

    def scrub_erased_content(self) -> None:
        """Physically remove erased personal content from the SQLite files.

        A committed DELETE alone leaves the erased bytes recoverable in
        freelist pages and in the write-ahead log. Truncating the WAL and
        rebuilding the database with VACUUM drops every residue copy, so a
        later raw-file read or backup cannot resurrect forgotten content.
        Owner-initiated erasure paths call this after their transaction
        commits; it is deliberately not used on hot paths.
        """
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.execute("VACUUM")

    def delete(self, table: str, item_id: int) -> bool:
        if table not in {"identity", "decisions", "writing_samples"}:
            raise ValueError("Unsupported deletion table")
        with self.db:
            if table == "identity":
                self.db.execute("DELETE FROM identity_revisions WHERE identity_id=?", (item_id,))
            cur = self.db.execute(f"DELETE FROM {table} WHERE id=?", (item_id,))
            if cur.rowcount:
                self._event("deleted", table, item_id)
        if cur.rowcount:
            self.scrub_erased_content()
        return bool(cur.rowcount)

    def add_decision(self, scenario: str, choice: str, rationale: str, *, source: str,
                     exception: str = "", source_ref: str = "", approved: bool = False,
                     options: list[str] | None = None, split: str = 'train') -> int:
        if not all(s.strip() for s in (scenario, choice, rationale, source)):
            raise ValueError("Scenario, choice, rationale and source are required")
        if split not in {'train', 'calibration', 'test'}:
            raise ValueError('Invalid decision split')
        if options is not None:
            if not (2 <= len(options) <= 6 and all(isinstance(o, str) and o.strip() for o in options)
                    and len({o.casefold().strip() for o in options}) == len(options)
                    and choice in options):
                raise ValueError('Provide 2-6 unique options and select one exact option')
        elif split != 'train':
            raise ValueError('Held-out decisions need explicit multiple-choice options')
        if self.db.execute('SELECT 1 FROM decisions WHERE lower(scenario)=lower(?)',
                           (scenario.strip(),)).fetchone():
            raise ValueError('Duplicate decision scenario may contaminate evaluation')
        with self.db:
            cur = self.db.execute("""INSERT INTO decisions
              (scenario,choice,rationale,exception,source,source_ref,status,created_at,options_json,split)
              VALUES (?,?,?,?,?,?,?,?,?,?)""", (scenario.strip(), choice, rationale, exception, source,
                  source_ref, "approved" if approved else "pending", utc_now(), json.dumps(options or []), split))
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

    def add_sample(self, text: str, *, source: str, source_ref: str = "",
                   split: str = "train") -> int:
        if not isinstance(text, str) or not text.strip() or not isinstance(source, str) or not source.strip():
            raise ValueError("Text and source required")
        if split not in {"train", "calibration", "test"}:
            raise ValueError("Writing sample split must be train, calibration or test")
        with self.db:
            cur = self.db.execute("""INSERT INTO writing_samples(text,source,source_ref,created_at,split)
                                     VALUES (?,?,?,?,?)""",
                                  (text, source, source_ref, utc_now(), split))
            self._event("created", "writing_samples", cur.lastrowid)
        return int(cur.lastrowid)

    def purge_source(self, source: str, source_ref: str = "") -> dict[str, int]:
        """Forget everything imported under the exact source and reference pair."""
        if not source.strip():
            raise ValueError("Source must not be blank")
        counts = {}
        with self.db:
            for table in ("identity", "decisions", "writing_samples", "episodes"):
                # Remove identity revision content as well.
                if table == "identity":
                    self.db.execute("""DELETE FROM identity_revisions WHERE identity_id IN
                      (SELECT id FROM identity WHERE source=? AND source_ref=?)""", (source, source_ref))
                cur = self.db.execute(f"DELETE FROM {table} WHERE source=? AND source_ref=?",
                                      (source, source_ref))
                counts[table] = cur.rowcount
            self._event("source-purged", "source", None)
        if any(counts.values()):
            self.scrub_erased_content()
        return counts

    def list_items(self, table: str, status: str | None = None, limit: int = 200) -> list[dict]:
        if table not in {"identity", "decisions", "writing_samples", "events", "identity_revisions", "messages", "feedback", "train_pairs", "proposals", "test_runs", "experiences", "episodes", "checkpoints", "episode_disputes", "evidence_artifacts"}:
            raise ValueError("Unsupported table")
        if status is not None and table not in {"identity", "decisions", "writing_samples", "train_pairs", "experiences", "episodes"}:
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
        """Never surface unapproved personal claims as facts."""
        return {
            "identity": self.list_items("identity", "approved"),
            "decisions": [dict(row) for row in self.db.execute("""SELECT * FROM decisions
                WHERE status='approved' AND split='train' ORDER BY id DESC LIMIT 200""")],
        }

    def export(self) -> dict:
        """Export user-controlled identity data; output contains sensitive content."""
        return {"schema": 2, "identity": self.list_items("identity", limit=100000),
                "identity_revisions": self.list_items("identity_revisions", limit=100000),
                "decisions": self.list_items("decisions", limit=100000),
                "writing_samples": self.list_items("writing_samples", limit=100000),
                "messages": self.list_items("messages", limit=100000),
                "feedback": self.list_items("feedback", limit=100000),
                "train_pairs": self.list_items("train_pairs", limit=100000),
                "proposals": self.list_items("proposals", limit=100000),
                "test_runs": self.list_items("test_runs", limit=100000),
                "experiences": self.list_items("experiences", limit=100000),
                "episodes": self.list_items("episodes", limit=100000),
                "checkpoints": self.list_items("checkpoints", limit=100000)}

    def close(self) -> None:
        self.db.close()
