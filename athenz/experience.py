"""Private episodic memories and resumable (non-executing) task checkpoints.

All memory text is explicitly reviewed. The event log contains metadata only.
A checkpoint is stored data, NEVER permission to execute a command.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
import re
from pathlib import Path

from .learning import LearningStore
from .store import STATES, utc_now

STOP = frozenset("the and for with from this that what when where how who why can you your"
                 " are was were have has had will should would could into then them their"
                 " its just only also about after before while done make task review".split())


def tokens(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", text.lower()) if x not in STOP}


def relevance(query: str, text: str, tags: list[str] | None = None) -> int:
    """Conservative lexical overlap; no related words -> no private memory retrieval."""
    q = tokens(query)
    return sum(3 if t in (tags or []) else 1 for t in q if t in tokens(text) | set(tags or []))


def clean_tags(tags: list[str]) -> list[str]:
    if len(tags) > 12 or any(not isinstance(t, str) or
                             not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,31}", t) for t in tags):
        raise ValueError("Use up to 12 lowercase, short topical tags")
    return sorted(set(tags))


class ExperienceStore(LearningStore):
    def observe(self, topic: str, detail: str, *, tags: list[str],
                source: str, source_ref: str = "", supersedes_id: int | None = None) -> int:
        """Suggest an episode; it cannot be retrieved until explicitly approved."""
        if not all(isinstance(s, str) and s.strip() for s in (topic, detail, source)):
            raise ValueError("Topic, detail and provenance are required")
        if len(detail) > 12000 or len(topic) > 300:
            raise ValueError("Episode is too large")
        labels = clean_tags(tags)
        with self.db:
            if supersedes_id is not None:
                old = self.db.execute("SELECT id,status FROM episodes WHERE id=?", (supersedes_id,)).fetchone()
                if not old or old["status"] != "approved":
                    raise ValueError("Only an approved existing episode may be superseded")
            cur = self.db.execute("""INSERT INTO episodes
                (topic,detail,tags_json,source,source_ref,status,supersedes_id,created_at,updated_at)
                VALUES (?,?,?,?,?,'pending',?,?,?)""",
                (topic.strip(), detail.strip(), json.dumps(labels), source,
                 source_ref, supersedes_id, utc_now(), utc_now()))
            self._event("created", "episodes", cur.lastrowid)
        return int(cur.lastrowid)

    def review_episode(self, episode_id: int, state: str) -> bool:
        if state not in STATES:
            raise ValueError("Invalid review state")
        with self.db:
            row = self.db.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
            if row is None:
                return False
            if row["status"] == state:
                return True
            if state == "approved" and row["supersedes_id"]:
                old = self.db.execute("SELECT status FROM episodes WHERE id=?",
                                      (row["supersedes_id"],)).fetchone()
                if old is None or old["status"] != "approved":
                    raise ValueError("Predecessor is no longer approved")
                self.db.execute("UPDATE episodes SET status='rejected', updated_at=? WHERE id=?",
                                (utc_now(), row["supersedes_id"]))
                self._event("superseded", "episodes", row["supersedes_id"])
            self.db.execute("UPDATE episodes SET status=?,updated_at=? WHERE id=?",
                            (state, utc_now(), episode_id))
            self._event("status:" + state, "episodes", episode_id)
        return True

    def relevant_episodes(self, query: str, limit: int = 5) -> list[dict]:
        if not 0 < limit <= 50:
            raise ValueError("Invalid limit")
        ranked = []
        for r in self.db.execute("""SELECT * FROM episodes e
            WHERE e.status='approved' AND NOT EXISTS (
                SELECT 1 FROM episode_disputes d WHERE d.status='unresolved'
                    AND (d.episode_a=e.id OR d.episode_b=e.id))"""):
            labels = json.loads(r["tags_json"])
            score = relevance(query, r["topic"] + " " + r["detail"], labels)
            if score:
                ranked.append((score, r["id"], {"topic": r["topic"], "detail": r["detail"],
                                               "source": r["source"], "tags": labels}))
        ranked.sort(key=lambda p: (p[0], p[1]), reverse=True)
        return [r[2] for r in ranked[:limit]]

    def potential_conflicts(self, episode_id: int) -> list[dict]:
        """Surface topical overlaps for human review; does not pretend to detect semantic contradictions."""
        candidate = self.db.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
        if candidate is None:
            raise ValueError("Unknown episode")
        tags = set(json.loads(candidate["tags_json"]))
        if not tags:
            return []
        return [{"id": r["id"], "topic": r["topic"], "tags": json.loads(r["tags_json"])}
                for r in self.db.execute(
                    "SELECT * FROM episodes WHERE status='approved' AND id<>?", (episode_id,))
                if tags.intersection(json.loads(r["tags_json"]))]

    def forget_episode(self, episode_id: int) -> bool:
        with self.db:
            cur = self.db.execute("DELETE FROM episodes WHERE id=?", (episode_id,))
            if cur.rowcount:
                self._event("deleted", "episodes", episode_id)
        return bool(cur.rowcount)

    def checkpoint(self, key: str, task: str, state: dict, *,
                   status: str = "paused", expected_revision: int | None = None) -> int:
        """CAS update prevents stale workers from clobbering newer checkpoint state."""
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", key):
            raise ValueError("Invalid checkpoint key")
        if not task.strip() or len(task) > 500 or status not in {
            "queued", "running", "paused", "failed", "complete"
        }:
            raise ValueError("Invalid checkpoint")
        if not isinstance(state, dict):
            raise ValueError("Checkpoint state must be a JSON object")
        state_json = json.dumps(state, ensure_ascii=False, allow_nan=False)
        if len(state_json.encode("utf-8")) > 16000:
            raise ValueError("Checkpoint state exceeds limit")
        # Keep checkpoint and scheduled proposal in one caller transaction.
        with (nullcontext() if self.db.in_transaction else self.db):
            old = self.db.execute("SELECT revision FROM checkpoints WHERE task_key=?", (key,)).fetchone()
            if old is None:
                if expected_revision not in (None, 0):
                    raise ValueError("Stale new checkpoint revision")
                cur = self.db.execute("""INSERT INTO checkpoints
                    (task_key,task,state_json,status,revision,updated_at)
                    VALUES (?,?,?,?,1,?)""", (key, task, state_json, status, utc_now()))
                record_id = cur.lastrowid
            else:
                if expected_revision != old["revision"]:
                    raise ValueError("Checkpoint revision conflict; reload before updating")
                cur = self.db.execute("""UPDATE checkpoints SET task=?,state_json=?,status=?,
                    revision=revision+1,updated_at=? WHERE task_key=? AND revision=?""",
                    (task, state_json, status, utc_now(), key, expected_revision))
                if cur.rowcount != 1:
                    raise ValueError("Checkpoint update race")
                record_id = self.db.execute(
                    "SELECT id FROM checkpoints WHERE task_key=?", (key,)).fetchone()[0]
            self._event("checkpoint:" + status, "checkpoints", record_id)
        return int(record_id)

    def get_checkpoint(self, key: str) -> dict | None:
        row = self.db.execute("SELECT * FROM checkpoints WHERE task_key=?", (key,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["state"] = json.loads(item.pop("state_json"))
        return item

    def forget_checkpoint(self, key: str) -> bool:
        with self.db:
            cur = self.db.execute("DELETE FROM checkpoints WHERE task_key=?", (key,))
            if cur.rowcount:
                self._event("deleted", "checkpoints", None)
        return bool(cur.rowcount)

    def dispute(self, first_id: int, second_id: int, note: str) -> int:
        """Quarantine BOTH approved memories pending human adjudication."""
        if first_id == second_id or not note.strip() or len(note) > 1000:
            raise ValueError("Two distinct episodes and a short explanation are required")
        a, b = sorted((first_id, second_id))
        with self.db:
            rows = self.db.execute("SELECT id,status FROM episodes WHERE id IN (?,?)", (a, b)).fetchall()
            if len(rows) != 2 or any(r['status'] != 'approved' for r in rows):
                raise ValueError("Only two approved episodes may be disputed")
            cur = self.db.execute("""INSERT INTO episode_disputes
                (episode_a,episode_b,note,status,created_at,updated_at)
                VALUES (?,?,?,'unresolved',?,?)""", (a, b, note.strip(), utc_now(), utc_now()))
            self._event("disputed", "episode_disputes", cur.lastrowid)
        return int(cur.lastrowid)

    def resolve_dispute(self, dispute_id: int, winner_id: int) -> bool:
        """Human chooses an already approved record; reject other as superseded."""
        with self.db:
            row = self.db.execute("SELECT * FROM episode_disputes WHERE id=?", (dispute_id,)).fetchone()
            if row is None:
                return False
            if row['status'] != 'unresolved' or winner_id not in (row['episode_a'], row['episode_b']):
                raise ValueError("Invalid or previously resolved dispute decision")
            winner = self.db.execute("SELECT status FROM episodes WHERE id=?", (winner_id,)).fetchone()
            if winner is None or winner['status'] != 'approved':
                raise ValueError("Chosen winner is not approved")
            loser_id = row['episode_b'] if winner_id == row['episode_a'] else row['episode_a']
            self.db.execute("UPDATE episodes SET status='rejected',updated_at=? WHERE id=?",
                            (utc_now(), loser_id))
            self.db.execute("""UPDATE episode_disputes SET status='resolved',winner_id=?,updated_at=?
                               WHERE id=?""", (winner_id, utc_now(), dispute_id))
            self._event("dispute-resolved", "episode_disputes", dispute_id)
        return True

    def record_artifact(self, test_run_id: int, artifact_id: str, path: Path) -> int:
        """Hash existing local evidence; never retain its bytes or path in the database.

        This records the file as observed locally. It does NOT by itself attest
        to a trusted CI run or grant any learning approval.
        """
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", artifact_id):
            raise ValueError("Artifact identifier must be short and opaque")
        if not self.db.execute("SELECT 1 FROM test_runs WHERE id=?", (test_run_id,)).fetchone():
            raise ValueError("Unknown test run")
        path = Path(path).expanduser()
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("Select a regular local evidence file up to 32 MiB")
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
        with self.db:
            cur = self.db.execute("""INSERT INTO evidence_artifacts
                (test_run_id,artifact_id,sha256,size_bytes,observed_at)
                VALUES (?,?,?,?,?)""", (test_run_id, artifact_id, digest.hexdigest(),
                                             path.stat().st_size, utc_now()))
            self._event('artifact-hashed', 'evidence_artifacts', cur.lastrowid)
        return int(cur.lastrowid)

    def verify_artifact(self, artifact_record_id: int, path: Path) -> bool:
        record = self.db.execute("SELECT * FROM evidence_artifacts WHERE id=?",
                                 (artifact_record_id,)).fetchone()
        if record is None:
            raise ValueError("Unknown artifact evidence")
        path = Path(path).expanduser()
        if path.is_symlink() or not path.is_file() or path.stat().st_size != record['size_bytes']:
            return False
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
        return digest.hexdigest() == record['sha256']
