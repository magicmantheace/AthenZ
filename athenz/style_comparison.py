"""Private, owner-blinded comparison of Twin writing style against a neutral model.

Both arms use the same *locally installed* Ollama model. Only the Twin arm sees
approved training evidence. Neither arm receives protected held-out writing.
The owner rates unlabeled A/B responses; only private aggregate results are
reported. This is an owner-preference pilot, not identity certification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat

from .chat import OllamaClient
from .evaluation import _reference_fingerprint, _wilson_interval
from .experience import ExperienceStore
from .prompting import build_messages
from .store import private_home_path, utc_now
from .style_readiness import _normalized, style_readiness


_FILENAME = "twin-style-comparisons.sqlite3"
_BASELINE_POLICY = (
    "You are an unpersonalized writing assistant. Complete the user's writing "
    "task clearly and naturally. Do not invent a particular person's memories "
    "or claim that you are that person. You have no access to a personal "
    "profile or personal writing samples. Return only the requested text."
)
MAX_TASK = 3000
MAX_OUTPUT = 12000


def _heldout_digest(store: ExperienceStore) -> str:
    """Capture protected evidence revisions without exposing them or prompts."""
    rows = [list(row) for row in store.db.execute(
        "SELECT id,text,status,split,source,source_ref,created_at "
        "FROM writing_samples WHERE status='approved' "
        "AND split IN ('test','calibration') ORDER BY id")]
    value = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _evidence_state(store: ExperienceStore) -> tuple[str, str]:
    return _reference_fingerprint(store), _heldout_digest(store)


def _validate_task(store: ExperienceStore, task: str) -> None:
    if not isinstance(task, str) or not 8 <= len(task.strip()) <= MAX_TASK:
        raise ValueError("Provide a writing task of 8 to 3000 characters")
    if not style_readiness(store)["pilot_evaluation_sufficient"]:
        raise ValueError("Review at least 3 independent train and test samples first")
    query = _normalized(task)
    for row in store.db.execute(
        "SELECT text FROM writing_samples WHERE status='approved' "
        "AND split IN ('test','calibration')"):
        heldout = _normalized(row["text"])
        if len(heldout) >= 24 and len(heldout.split()) >= 5 and heldout in query:
            raise ValueError("Writing task copies protected evaluation evidence")


def _db_path(store: ExperienceStore) -> Path:
    home = private_home_path(store.home)
    path = home / _FILENAME
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("Private comparison database path is not regular")
    if path.exists():
        status = path.stat()
        if (not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
                or (os.name != "nt" and status.st_mode & 0o077)):
            raise ValueError("Private comparison database is not owner-only")
    return path


class ComparisonArchive:
    """Isolated unencrypted owner-only SQLite state; no training auto-import."""

    def __init__(self, store: ExperienceStore, *, create: bool = False):
        self.path = _db_path(store)
        if not self.path.exists():
            if not create:
                raise ValueError("No private style comparisons exist")
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(self.path, flags, 0o600)
            os.close(fd)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        if create:
            self.db.execute("""CREATE TABLE IF NOT EXISTS comparisons (
                id INTEGER PRIMARY KEY,
                task TEXT NOT NULL,
                task_digest TEXT NOT NULL UNIQUE,
                option_a TEXT NOT NULL,
                option_b TEXT NOT NULL,
                twin_option TEXT NOT NULL CHECK(twin_option IN ('A','B')),
                model_tag TEXT NOT NULL,
                model_digest TEXT NOT NULL,
                training_digest TEXT NOT NULL,
                heldout_digest TEXT NOT NULL,
                chosen TEXT CHECK(chosen IN ('A','B','tie')),
                created_at TEXT NOT NULL,
                rated_at TEXT)""")
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    def save(self, *, task: str, options: tuple[str, str], twin_option: str,
             model_tag: str, model_digest: str, evidence: tuple[str, str],
             task_id: int | None = None) -> int:
        digest = hashlib.sha256(_normalized(task).encode("utf-8")).hexdigest()
        with self.db:
            if task_id is not None:
                # Review/consumption check and insertion are one transaction
                # in the SAME private SQLite database as the task bank.
                approved = self.db.execute(
                    "SELECT status,task_digest,training_digest,heldout_digest "
                    "FROM style_tasks WHERE id=?", (task_id,)).fetchone()
                if (approved is None or approved["status"] != "approved"
                        or approved["task_digest"] != digest
                        or (approved["training_digest"],
                            approved["heldout_digest"]) != evidence
                        or self.db.execute(
                            "SELECT 1 FROM style_task_uses WHERE task_id=?",
                            (task_id,)).fetchone()):
                    raise ValueError("Reviewed writing task changed or was used")
            cursor = self.db.execute(
                """INSERT INTO comparisons
                (task,task_digest,option_a,option_b,twin_option,model_tag,
                 model_digest,training_digest,heldout_digest,created_at)
                 VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (task.strip(), digest, *options, twin_option, model_tag,
                 model_digest, *evidence, utc_now()))
            if task_id is not None:
                self.db.execute(
                    "INSERT INTO style_task_uses(task_id,comparison_id) "
                    "VALUES (?,?)", (task_id, cursor.lastrowid))
        return int(cursor.lastrowid)

    def show(self, case_id: int) -> dict:
        row = self.db.execute(
            "SELECT id,task,option_a,option_b,chosen FROM comparisons WHERE id=?",
            (case_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown private style comparison")
        return {"id": int(row["id"]), "task": row["task"],
                "A": row["option_a"], "B": row["option_b"],
                "rated": row["chosen"] is not None}

    def rate(self, store: ExperienceStore, case_id: int, choice: str,
             *, confirmed: bool = False) -> None:
        if not confirmed or choice not in {"A", "B", "tie"}:
            raise ValueError("Explicit confirmed choice of A, B or tie required")
        with self.db:
            row = self.db.execute(
                "SELECT training_digest,heldout_digest,chosen "
                "FROM comparisons WHERE id=?", (case_id,)).fetchone()
            if row is None or row["chosen"] is not None:
                raise ValueError("Comparison is missing or already rated")
            if (row["training_digest"], row["heldout_digest"]) != _evidence_state(store):
                raise ValueError("Evidence changed: discard and repeat this comparison")
            updated = self.db.execute(
                "UPDATE comparisons SET chosen=?,rated_at=? "
                "WHERE id=? AND chosen IS NULL",
                (choice, utc_now(), case_id))
            if updated.rowcount != 1:
                raise ValueError("Comparison rating changed concurrently")

    def remove(self, case_id: int, *, confirmed: bool = False) -> None:
        if not confirmed:
            raise ValueError("Explicit confirmation required to delete a comparison")
        with self.db:
            changed = self.db.execute("DELETE FROM comparisons WHERE id=?", (case_id,))
            if changed.rowcount != 1:
                raise ValueError("Unknown comparison")

    def report(self, store: ExperienceStore) -> dict:
        current = _evidence_state(store)
        counts = {"twin": 0, "neutral": 0, "tie": 0}
        stale, unrated, total = 0, 0, 0
        for r in self.db.execute(
            "SELECT chosen,twin_option,training_digest,heldout_digest "
            "FROM comparisons ORDER BY id"):
            total += 1
            if (r["training_digest"], r["heldout_digest"]) != current:
                stale += 1
            elif r["chosen"] is None:
                unrated += 1
            elif r["chosen"] == "tie":
                counts["tie"] += 1
            elif r["chosen"] == r["twin_option"]:
                counts["twin"] += 1
            else:
                counts["neutral"] += 1
        decisions = counts["twin"] + counts["neutral"]
        return {
            "schema": 1, "kind": "blinded-owner-style-preference-pilot",
            "total_cases": total, "stale_cases": stale,
            "unrated_current_cases": unrated,
            "valid_owner_ratings": sum(counts.values()),
            "twin_preferred": counts["twin"],
            "neutral_preferred": counts["neutral"],
            "ties": counts["tie"],
            "twin_preference_non_tie_rate":
                counts["twin"] / decisions if decisions else None,
            "wilson_interval_95":
                _wilson_interval(counts["twin"], decisions) if decisions else None,
            "minimum_pilot_non_ties_reached": decisions >= 5,
            "model_accuracy_or_identity_certified": False,
            "owner_text_in_report": False,
            "limitations": "Owner-reported, blinded style preference only; "
                           "no semantic leak audit, consciousness or identity proof."
        }


def create_comparison(store: ExperienceStore, task: str, *,
                      confirmed: bool = False, model_tag: str | None = None,
                      client_factory=None, digest_fn=None,
                      route_fn=None, chooser=None, task_id: int | None = None,
                      task_guard=None) -> int:
    """Generate both arms before saving; no partial result after model failure."""
    if not confirmed:
        raise ValueError("Owner confirmation required before local inference")
    if task_id is not None and task_guard is None:
        raise ValueError("Reviewed style task requires a private task guard")
    if task_guard is not None:
        task_guard()
    _validate_task(store, task)
    from .runtime import checked_active_tag, model_digest
    route = route_fn or checked_active_tag
    digest = digest_fn or model_digest
    active_tag = route(store)
    chosen_tag = model_tag or active_tag or OllamaClient().model
    if not isinstance(chosen_tag, str) or not chosen_tag.strip():
        raise ValueError("Local model tag required")
    before = _evidence_state(store)
    model_sha = digest(chosen_tag)
    model = (client_factory or (lambda tag: OllamaClient(model=tag)))(chosen_tag)
    twin_messages = build_messages(store, task, mode="twin")
    # A concurrent consent or task-review change must not get a stale
    # personalized prompt sent to the local model.
    if task_guard is not None:
        task_guard()
    if (_evidence_state(store) != before or route(store) != active_tag
            or digest(chosen_tag) != model_sha):
        raise ValueError("Source or local model changed before model inference")
    neutral_messages = [
        {"role": "system", "content": _BASELINE_POLICY},
        {"role": "user", "content": task.strip()}]
    # Never inspect, retrieve, display or send withheld test writing here.
    try:
        neutral = model.generate(neutral_messages, temperature=0.3, seed=11)
    except Exception:
        # A local model may echo a private prompt in an exception string.
        raise ValueError("Local blinded comparison inference failed") from None
    if task_guard is not None:
        task_guard()
    if (_evidence_state(store) != before or route(store) != active_tag
            or digest(chosen_tag) != model_sha):
        raise ValueError("Source or local model changed during blinded comparison")
    try:
        twin = model.generate(twin_messages, temperature=0.3, seed=11)
    except Exception:
        raise ValueError("Local blinded comparison inference failed") from None
    if task_guard is not None:
        task_guard()
    if (_evidence_state(store) != before or route(store) != active_tag
            or digest(chosen_tag) != model_sha):
        raise ValueError("Source or local model changed during blinded comparison")
    if (not isinstance(neutral, str) or not isinstance(twin, str)
            or not 1 <= len(neutral.strip()) <= MAX_OUTPUT
            or not 1 <= len(twin.strip()) <= MAX_OUTPUT):
        raise ValueError("Model returned an unusable or oversized comparison")
    twin_first = (chooser or secrets.randbelow)(2) == 0
    options = (twin, neutral) if twin_first else (neutral, twin)
    archive = ComparisonArchive(store, create=True)
    try:
        # Recheck after opening the separate private archive: the source can
        # be revoked while SQLite is establishing the comparison database.
        if task_guard is not None:
            task_guard()
        if (_evidence_state(store) != before or route(store) != active_tag
                or digest(chosen_tag) != model_sha):
            raise ValueError("Source or local model changed before comparison save")
        try:
            return archive.save(
                task=task, options=options, twin_option="A" if twin_first else "B",
                model_tag=chosen_tag, model_digest=model_sha, evidence=before,
                task_id=task_id)
        except sqlite3.IntegrityError:
            raise ValueError("This normalized writing task has already been compared") from None
    finally:
        archive.close()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description="Private local, owner-blinded Twin writing style comparison")
    p.add_argument("--home", type=Path, help="Private AthenZ profile directory")
    sub = p.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("task", help="Independent writing task, NOT held-out prose")
    start.add_argument("--model", help="Explicit installed Ollama model (optional)")
    start.add_argument("--confirm", action="store_true")
    show = sub.add_parser("show")
    show.add_argument("id", type=int)
    rate = sub.add_parser("rate")
    rate.add_argument("id", type=int)
    rate.add_argument("choice", choices=("A", "B", "tie"))
    rate.add_argument("--confirm", action="store_true")
    sub.add_parser("report")
    delete = sub.add_parser("delete")
    delete.add_argument("id", type=int)
    delete.add_argument("--confirm", action="store_true")
    args = p.parse_args(argv)
    store = ExperienceStore(args.home)
    try:
        try:
            if args.command == "start":
                number = create_comparison(
                    store, args.task, confirmed=args.confirm, model_tag=args.model)
                print(f"Private blinded comparison #{number} saved; "
                      f"review with athenz-style-compare show {number}")
            else:
                archive = ComparisonArchive(store)
                try:
                    if args.command == "show":
                        print(json.dumps(archive.show(args.id), ensure_ascii=False))
                    elif args.command == "rate":
                        archive.rate(store, args.id, args.choice, confirmed=args.confirm)
                        print("Owner rating recorded privately")
                    elif args.command == "report":
                        print(json.dumps(archive.report(store), sort_keys=True))
                    elif args.command == "delete":
                        archive.remove(args.id, confirmed=args.confirm)
                        print("Private comparison deleted")
                finally:
                    archive.close()
        except (ValueError, sqlite3.Error, OSError) as exc:
            # Do not echo unexpected exceptions that can contain private paths
            # or model outputs. The known validation errors contain no text.
            raise SystemExit("Style comparison refused; check input, owner "
                             "approval, model availability and source freshness") from None
    finally:
        store.close()


if __name__ == "__main__":
    main()
