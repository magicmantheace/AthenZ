"""Private, owner-reviewed independent task bank for Twin writing-style pilots.

Task prompts are owner-authored and approved before any model generation.
They never enter training context, cannot grant permissions, and are consumed
at most once. The table lives in the existing owner-only style comparison
SQLite archive, not the public repository or the identity training store.
"""
from __future__ import annotations

import hashlib
import sqlite3

from .experience import ExperienceStore
from .store import utc_now
from .style_readiness import _normalized
from .style_comparison import (
    ComparisonArchive, MAX_TASK, _evidence_state, _validate_task,
)


def _task_digest(task: str) -> str:
    return hashlib.sha256(_normalized(task).encode("utf-8")).hexdigest()


class StyleTaskBank:
    def __init__(self, store: ExperienceStore, *, create: bool = False):
        self.archive = ComparisonArchive(store, create=create)
        self.db = self.archive.db
        if create:
            self.db.executescript("""CREATE TABLE IF NOT EXISTS style_tasks (
                id INTEGER PRIMARY KEY,
                task TEXT NOT NULL,
                task_digest TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','approved','rejected')),
                training_digest TEXT,
                heldout_digest TEXT,
                created_at TEXT NOT NULL,
                approved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS style_task_uses (
                task_id INTEGER UNIQUE NOT NULL
                    REFERENCES style_tasks(id) ON DELETE RESTRICT,
                comparison_id INTEGER UNIQUE NOT NULL
                    REFERENCES comparisons(id) ON DELETE CASCADE
            );
            """)
            self.db.commit()

    def close(self) -> None:
        self.archive.close()

    def _get(self, task_id: int) -> sqlite3.Row:
        if type(task_id) is not int or task_id <= 0:
            raise ValueError("Positive private task ID required")
        try:
            row = self.db.execute(
                "SELECT * FROM style_tasks WHERE id=?", (task_id,)).fetchone()
        except sqlite3.OperationalError:
            raise ValueError("No approved private task bank exists") from None
        if row is None:
            raise ValueError("Unknown private style task")
        return row

    def add(self, task: str, *, confirmed: bool = False) -> int:
        if not confirmed:
            raise ValueError("Explicit owner confirmation is required to save a task")
        if (not isinstance(task, str) or not 8 <= len(task.strip()) <= MAX_TASK
                or not _normalized(task)):
            raise ValueError("Provide one bounded independent writing task")
        try:
            with self.db:
                cur = self.db.execute(
                    "INSERT INTO style_tasks(task,task_digest,created_at) "
                    "VALUES (?,?,?)",
                    (task.strip(), _task_digest(task), utc_now()))
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            raise ValueError("Writing task already exists in private task bank") from None

    def review(self, store: ExperienceStore, task_id: int, decision: str,
               *, confirmed: bool = False) -> None:
        if not confirmed or decision not in {"approved", "rejected"}:
            raise ValueError("Explicit confirmed owner task review required")
        row = self._get(task_id)
        if self.db.execute(
            "SELECT 1 FROM style_task_uses WHERE task_id=?", (task_id,)
        ).fetchone() is not None:
            raise ValueError("Consumed task cannot be changed after a comparison")
        if decision == "approved":
            _validate_task(store, row["task"])
            evidence = _evidence_state(store)
            with self.db:
                updated = self.db.execute(
                    "UPDATE style_tasks SET status='approved',training_digest=?,"
                    "heldout_digest=?,approved_at=? WHERE id=?",
                    (*evidence, utc_now(), task_id))
        else:
            with self.db:
                updated = self.db.execute(
                    "UPDATE style_tasks SET status='rejected',training_digest=NULL,"
                    "heldout_digest=NULL,approved_at=NULL WHERE id=?",
                    (task_id,))
        if updated.rowcount != 1:
            raise ValueError("Task changed during review")

    def delete(self, task_id: int, *, confirmed: bool = False) -> None:
        """Explicitly erase a source task and its derived comparison pair."""
        if not confirmed:
            raise ValueError("Owner confirmation required to forget a private task")
        self._get(task_id)
        with self.db:
            # The comparison includes the raw owner-authored task. Delete
            # it before the original to avoid retained private derivatives.
            self.db.execute(
                "DELETE FROM comparisons WHERE id IN "
                "(SELECT comparison_id FROM style_task_uses WHERE task_id=?)",
                (task_id,))
            updated = self.db.execute(
                "DELETE FROM style_tasks WHERE id=?", (task_id,))
            if updated.rowcount != 1:
                raise ValueError("Private writing task changed during deletion")

    def summary(self, store: ExperienceStore) -> dict:
        evidence = _evidence_state(store)
        result = {
            "schema": 1,
            "pending": 0,
            "approved_ready_unused": 0,
            "approved_stale_unused": 0,
            "rejected": 0,
            "consumed": 0,
            "already_compared_outside_bank": 0,
            "private_task_text_returned": False,
        }
        try:
            rows = self.db.execute(
                "SELECT t.id,t.status,t.training_digest,t.heldout_digest,"
                "u.task_id AS consumed_id,c.id AS compared_id "
                "FROM style_tasks t "
                "LEFT JOIN style_task_uses u ON u.task_id=t.id "
                "LEFT JOIN comparisons c ON c.task_digest=t.task_digest"
            ).fetchall()
        except sqlite3.OperationalError:
            return result
        for row in rows:
            if row["consumed_id"] is not None:
                result["consumed"] += 1
            elif row["compared_id"] is not None:
                result["already_compared_outside_bank"] += 1
            elif row["status"] == "pending":
                result["pending"] += 1
            elif row["status"] == "rejected":
                result["rejected"] += 1
            elif (row["training_digest"], row["heldout_digest"]) == evidence:
                result["approved_ready_unused"] += 1
            else:
                result["approved_stale_unused"] += 1
        return result

    def next_approved(self, store: ExperienceStore) -> dict:
        """Use deterministic owner-approved evaluation tasks, never train data."""
        evidence = _evidence_state(store)
        rows = self.db.execute(
            "SELECT t.* FROM style_tasks t "
            "LEFT JOIN style_task_uses u ON u.task_id=t.id "
            "WHERE t.status='approved' AND u.task_id IS NULL "
            "ORDER BY t.id").fetchall()
        for row in rows:
            if (row["training_digest"], row["heldout_digest"]) != evidence:
                continue
            # Explicit tasks duplicated in earlier ad-hoc comparisons
            # cannot be relabeled as independent new held-out questions.
            if self.db.execute(
                "SELECT 1 FROM comparisons WHERE task_digest=?",
                (row["task_digest"],)).fetchone():
                continue
            _validate_task(store, row["task"])
            return {"id": int(row["id"]), "task": row["task"],
                    "digest": row["task_digest"], "evidence": evidence}
        raise ValueError("No current reviewed unused writing task is available")

    def ensure_unchanged(self, store: ExperienceStore,
                         task_id: int, expected: dict) -> None:
        row = self._get(task_id)
        evidence = _evidence_state(store)
        if (row["status"] != "approved"
                or row["task_digest"] != expected["digest"]
                or row["task"] != expected["task"]
                or (row["training_digest"], row["heldout_digest"]) != evidence
                or evidence != expected["evidence"]):
            raise ValueError("Approved writing task or owner evidence changed")
        if self.db.execute(
            "SELECT 1 FROM style_task_uses WHERE task_id=?",
            (task_id,)).fetchone():
            raise ValueError("This writing task was already consumed")


def start_next(store: ExperienceStore, *, confirmed: bool = False,
               model_tag: str | None = None, client_factory=None,
               digest_fn=None, route_fn=None, chooser=None) -> int:
    """Run one independently approved task with both arms and one-time use."""
    if not confirmed:
        raise ValueError("Owner confirmation required to run a private test task")
    bank = StyleTaskBank(store)
    try:
        selected = bank.next_approved(store)
    finally:
        bank.close()

    def guard() -> None:
        current = StyleTaskBank(store)
        try:
            current.ensure_unchanged(store, selected["id"], selected)
        finally:
            current.close()

    # Import inside the function to avoid circular import of class methods.
    from .style_comparison import create_comparison
    return create_comparison(
        store, selected["task"], confirmed=True, model_tag=model_tag,
        client_factory=client_factory, digest_fn=digest_fn,
        route_fn=route_fn, chooser=chooser, task_id=selected["id"],
        task_guard=guard,
    )
