"""Forward-only private database migrations for conversation and work evidence."""
from __future__ import annotations
import sqlite3


def migrate_v2(db: sqlite3.Connection) -> None:
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version != 1:
        if version >= 2:
            return
        raise RuntimeError(f'Unexpected schema version {version}')
    # All records from the identity v1 tables remain intact.
    try:
        # sqlite3.executescript commits a pending transaction first, so we put
        # BEGIN/COMMIT inside the SQL to make migrations crash-atomic.
        db.executescript('''BEGIN IMMEDIATE;
        ALTER TABLE writing_samples ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','approved','rejected'));
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, session TEXT NOT NULL, mode TEXT NOT NULL
            CHECK(mode IN ('twin','agent')), role TEXT NOT NULL
            CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_messages_session ON messages(session,mode,id);
        CREATE TABLE feedback (
            id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL
            REFERENCES messages(id) ON DELETE CASCADE,
            rating TEXT NOT NULL CHECK(rating IN ('up','down')),
            correction TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE train_pairs (
            id INTEGER PRIMARY KEY, instruction TEXT NOT NULL,
            ideal_answer TEXT NOT NULL,
            feedback_id INTEGER REFERENCES feedback(id) ON DELETE CASCADE,
            source TEXT NOT NULL, source_ref TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE proposals (
            id INTEGER PRIMARY KEY, repo TEXT NOT NULL, task TEXT NOT NULL,
            changes_json TEXT NOT NULL, summary TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('proposed','applied','undone')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE test_runs (
            id INTEGER PRIMARY KEY,
            proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
            command TEXT NOT NULL, returncode INTEGER NOT NULL,
            output_excerpt TEXT NOT NULL, output_sha256 TEXT NOT NULL,
            files_sha256 TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE experiences (
            id INTEGER PRIMARY KEY,
            proposal_id INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
            test_run_id INTEGER NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
            task TEXT NOT NULL, outcome TEXT NOT NULL
            CHECK(outcome IN ('test_pass','test_fail')),
            lesson TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
            CHECK(status IN ('pending','approved','rejected')),
            evidence_sha256 TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX idx_experiences_status ON experiences(status,outcome);
        PRAGMA user_version = 2;
        COMMIT;
        ''')
    except Exception:
        db.rollback()
        raise


def migrate_v3(db: sqlite3.Connection) -> None:
    """Separate held-out owner choices from retrieved training demonstrations."""
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version >= 3:
        return
    if version != 2:
        raise RuntimeError(f'Unexpected schema version {version}; expected 2 or 3')
    try:
        db.executescript('''BEGIN IMMEDIATE;
            ALTER TABLE decisions ADD COLUMN options_json TEXT NOT NULL DEFAULT '[]';
            ALTER TABLE decisions ADD COLUMN split TEXT NOT NULL DEFAULT 'train'
                CHECK(split IN ('train','calibration','test'));
            CREATE INDEX idx_decision_eval ON decisions(status,split,id);
            PRAGMA user_version=3;
            COMMIT;
        ''')
    except Exception:
        db.rollback()
        raise


def migrate_v4(db: sqlite3.Connection) -> None:
    """Private reviewed episodes, resumable task data and immutable metadata events."""
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version >= 4:
        return
    if version != 3:
        raise RuntimeError(f'Unexpected schema version {version}; expected 3 or 4')
    try:
        db.executescript('''BEGIN IMMEDIATE;
            CREATE TABLE episodes (
                id INTEGER PRIMARY KEY, topic TEXT NOT NULL, detail TEXT NOT NULL,
                tags_json TEXT NOT NULL, source TEXT NOT NULL,
                source_ref TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                supersedes_id INTEGER REFERENCES episodes(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX idx_episodes_review ON episodes(status,id);
            CREATE INDEX idx_episodes_source ON episodes(source,source_ref);
            CREATE TABLE checkpoints (
                id INTEGER PRIMARY KEY, task_key TEXT UNIQUE NOT NULL,
                task TEXT NOT NULL, state_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN
                  ('queued','running','paused','failed','complete')),
                revision INTEGER NOT NULL CHECK(revision > 0), updated_at TEXT NOT NULL
            );
            CREATE TRIGGER events_append_only_update BEFORE UPDATE ON events
                BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
            CREATE TRIGGER events_append_only_delete BEFORE DELETE ON events
                BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
            PRAGMA user_version=4;
            COMMIT;
        ''')
    except Exception:
        db.rollback()
        raise


def migrate_v5(db: sqlite3.Connection) -> None:
    """Explicit dispute quarantine and locally observed artifact fingerprints."""
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version >= 5:
        return
    if version != 4:
        raise RuntimeError(f'Unexpected schema version {version}; expected 4 or 5')
    try:
        db.executescript('''BEGIN IMMEDIATE;
            CREATE TABLE episode_disputes (
                id INTEGER PRIMARY KEY,
                episode_a INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
                episode_b INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'unresolved'
                    CHECK(status IN ('unresolved','resolved')),
                winner_id INTEGER REFERENCES episodes(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(episode_a,episode_b), CHECK(episode_a < episode_b)
            );
            CREATE INDEX idx_episode_disputes_review ON episode_disputes(status,episode_a,episode_b);
            CREATE TABLE evidence_artifacts (
                id INTEGER PRIMARY KEY,
                test_run_id INTEGER NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
                artifact_id TEXT NOT NULL, sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, observed_at TEXT NOT NULL,
                UNIQUE(test_run_id,artifact_id)
            );
            PRAGMA user_version=5;
            COMMIT;
        ''')
    except Exception:
        db.rollback()
        raise


def migrate_v6(db: sqlite3.Connection) -> None:
    """Reserve independently reviewed writing samples for style evaluation.

    Legacy v5 writing samples become TRAINING examples, never held-out
    references retroactively. Future withheld samples require explicit
    creation in calibration/test. Migration preserves review status and
    source provenance and never reads the private sample bytes into logs.
    """
    version = db.execute('PRAGMA user_version').fetchone()[0]
    if version >= 6:
        return
    if version != 5:
        raise RuntimeError(f'Unexpected schema version {version}; expected 5 or 6')
    try:
        db.executescript('''BEGIN IMMEDIATE;
            ALTER TABLE writing_samples ADD COLUMN split TEXT NOT NULL DEFAULT 'train'
                CHECK(split IN ('train','calibration','test'));
            CREATE INDEX idx_writing_split ON writing_samples(status,split,id);
            PRAGMA user_version=6;
            COMMIT;
        ''')
    except Exception:
        db.rollback()
        raise
