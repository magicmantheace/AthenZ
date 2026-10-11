"""Private episodic memories and resumable (non-executing) task checkpoints.

All memory text is explicitly reviewed. The event log contains metadata only.
A checkpoint is stored data, NEVER permission to execute a command.
"""
from __future__ import annotations

import json
import re

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
        for r in self.db.execute("SELECT * FROM episodes WHERE status='approved'"):
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
        with self.db:
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
