"""Owner-controlled experience, chat and training-candidate storage.

Test success is an observation, not a claim that the patch is correct. Procedural
lessons only enter prompts after explicit review.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from contextlib import nullcontext
from .store import IdentityStore, KINDS, STATES, utc_now
from .style_overlap import strongly_overlaps


def _writing_split_key(text: str) -> str:
    """Conservative normalized exact-duplicate check, not semantic overlap."""
    return ' '.join(re.findall(
        r'\w+', unicodedata.normalize('NFKC', text).casefold()))


class LearningStore(IdentityStore):
    @staticmethod
    def _message_review_digest(row) -> str:
        """One user-authored message AND its session provenance, never assistant text."""
        payload = [row["id"], row["session"], row["mode"],
                   row["role"], row["content"]]
        return hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")).hexdigest()

    def memory_source_preview(self, message_id: int) -> dict:
        """Return a private owner-preview; not a model prompt or public report."""
        if type(message_id) is not int or message_id <= 0:
            raise ValueError("Choose an existing owner-authored message")
        row = self.db.execute(
            "SELECT id,session,mode,role,content FROM messages WHERE id=?",
            (message_id,)).fetchone()
        if row is None or row["role"] != "user":
            raise ValueError("Only an owner-authored chat message can be remembered")
        if row["mode"] not in ("agent", "twin"):
            raise ValueError("Message mode is invalid")
        return {
            "id": row["id"], "session": row["session"], "mode": row["mode"],
            "content": row["content"],
            "review_sha256": self._message_review_digest(row),
        }

    def propose_message_memory(self, message_id: int, kind: str, text: str, *,
                               review_sha256: str, confirmed: bool = False,
                               expected_session: str | None = None,
                               expected_mode: str | None = None) -> int:
        """One pending memory per pinned source; no model extraction or approval."""
        if confirmed is not True:
            raise ValueError("Explicit owner confirmation is required")
        if (type(kind) is not str or kind not in KINDS
                or type(text) is not str or not text.strip()
                or len(text) > 1200):
            raise ValueError("Choose a memory type and 1-1200 character owner summary")
        if (type(review_sha256) is not str or
                re.fullmatch(r"[a-f0-9]{64}", review_sha256) is None):
            raise ValueError("Inspect the exact source message before proposing memory")
        if type(message_id) is not int or message_id <= 0:
            raise ValueError("Invalid source message")
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            source = self.db.execute(
                "SELECT id,session,mode,role,content FROM messages WHERE id=?",
                (message_id,)).fetchone()
            if (source is None or source["role"] != "user"
                    or self._message_review_digest(source) != review_sha256
                    or (expected_session is not None and
                        source["session"] != expected_session)
                    or (expected_mode is not None and
                        source["mode"] != expected_mode)):
                raise ValueError("Source message changed after owner review; inspect again")
            ref = str(message_id)
            if self.db.execute(
                "SELECT 1 FROM identity WHERE source='owner:chat-message' "
                "AND source_ref=?", (ref,)).fetchone():
                raise ValueError("This source message already has a memory proposal")
            now = utc_now()
            cur = self.db.execute(
                "INSERT INTO identity "
                "(kind,text,source,source_ref,confidence,status,created_at,updated_at) "
                "VALUES (?,?,?,?,1.0,'pending',?,?)",
                (kind, text.strip(), "owner:chat-message", ref, now, now))
            self._event("created", "identity", cur.lastrowid)
            return int(cur.lastrowid)

    def _forget_message_memories(self, predicate: str, key) -> None:
        """Delete derived identity and revisions inside the source deletion."""
        if predicate not in ("id=?", "session=?", "session=? AND mode=?"):
            raise ValueError("Invalid source scope")
        source = "SELECT CAST(id AS TEXT) FROM messages WHERE " + predicate
        criteria = "source='owner:chat-message' AND source_ref IN (" + source + ")"
        args = key if predicate == "session=? AND mode=?" else (key,)
        self.db.execute(
            "DELETE FROM identity_revisions WHERE identity_id IN "
            "(SELECT id FROM identity WHERE " + criteria + ")", args)
        self.db.execute("DELETE FROM identity WHERE " + criteria, args)

    def add_message(self, session: str, mode: str, role: str, content: str) -> int:
        if mode not in {'twin', 'agent'} or role not in {'user', 'assistant'}:
            raise ValueError('Invalid mode or role')
        if not session.strip() or not content.strip():
            raise ValueError('Session and message cannot be empty')
        with self.db:
            cur = self.db.execute('''INSERT INTO messages(session,mode,role,content,created_at)
                                     VALUES (?,?,?,?,?)''', (session, mode, role, content, utc_now()))
        return int(cur.lastrowid)

    def conversation(self, session: str, mode: str, limit: int = 12) -> list[dict]:
        if mode not in {'twin', 'agent'} or not 0 < limit <= 100:
            raise ValueError('Invalid mode or limit')
        rows = self.db.execute('''SELECT id,role,content FROM messages
            WHERE session=? AND mode=? ORDER BY id DESC LIMIT ?''', (session, mode, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def add_feedback(self, message_id: int, rating: str, correction: str = '') -> int:
        if rating not in {'up', 'down'}:
            raise ValueError('Rating must be up or down')
        message = self.db.execute("SELECT * FROM messages WHERE id=? AND role='assistant'",
                                  (message_id,)).fetchone()
        if message is None:
            raise ValueError('Feedback requires an assistant reply')
        with self.db:
            cur = self.db.execute('''INSERT INTO feedback(message_id,rating,correction,created_at)
                                     VALUES (?,?,?,?)''', (message_id, rating, correction.strip(), utc_now()))
            previous = self.db.execute('''SELECT content FROM messages
                WHERE session=? AND mode=? AND role='user' AND id<?
                ORDER BY id DESC LIMIT 1''', (message['session'], message['mode'], message_id)).fetchone()
            if previous and (correction.strip() or rating == 'up'):
                self.db.execute('''INSERT INTO train_pairs
                    (instruction,ideal_answer,feedback_id,source,source_ref,status,created_at)
                    VALUES (?,?,?,?,?,'pending',?)''', (previous['content'],
                    correction.strip() or message['content'], cur.lastrowid,
                    'owner:feedback', str(cur.lastrowid), utc_now()))
            self._event('feedback-added', 'feedback', cur.lastrowid)
        return int(cur.lastrowid)

    def set_review(self, table: str, item_id: int, state: str) -> bool:
        if table not in {'writing_samples', 'train_pairs', 'experiences'} or state not in STATES:
            raise ValueError('Invalid review table or state')
        row = self.db.execute(f'SELECT * FROM {table} WHERE id=?', (item_id,)).fetchone()
        if row is None:
            return False
        if table == 'writing_samples' and state == 'approved':
            normalized = _writing_split_key(row['text'])
            if not normalized:
                raise ValueError('Reviewed writing sample cannot be empty')
            for other in self.db.execute(
                """SELECT text FROM writing_samples
                   WHERE status='approved' AND split<>? AND id<>?""",
                (row['split'], item_id)
            ):
                if (_writing_split_key(other['text']) == normalized
                        or strongly_overlaps(row['text'], other['text'])):
                    raise ValueError(
                        'Duplicate writing sample in a separate evaluation split '
                        '(exact or near-copy)')
        if table == 'experiences' and state == 'approved':
            if row['outcome'] != 'test_pass':
                raise ValueError('Cannot approve a failed test as a successful lesson')
            test_row = self.db.execute('SELECT command FROM test_runs WHERE id=?',
                                       (row['test_run_id'],)).fetchone()
            if test_row is None or (test_row['command'] == 'athenz:ast.parse (no execution)'
                                    or ' -m py_compile ' in test_row['command']):
                raise ValueError('Syntax parsing alone cannot prove procedural success')
            if self.get_proposal(row['proposal_id'])['status'] != 'applied':
                raise ValueError('Cannot approve a lesson for an unapplied or undone patch')
            latest = self.db.execute('SELECT MAX(id) FROM test_runs WHERE proposal_id=?',
                                     (row['proposal_id'],)).fetchone()[0]
            if row['test_run_id'] != latest:
                raise ValueError('Cannot approve superseded test evidence')
        with self.db:
            self.db.execute(f'UPDATE {table} SET status=? WHERE id=?', (state, item_id))
            self._event('status:' + state, table, item_id)
        return True

    def approved_training_pairs(self) -> list[dict]:
        return [{'instruction': r['instruction'], 'output': r['ideal_answer']}
                for r in self.list_items('train_pairs', 'approved', 100000)]

    def approved_experiences(self, limit: int = 10, query: str | None = None) -> list[dict]:
        """Retrieve *relevant*, human-reviewed lessons with CURRENT passing evidence."""
        from .experience import relevance
        rows = self.db.execute("""SELECT e.task,e.lesson,e.evidence_sha256
            FROM experiences e
            JOIN proposals p ON p.id=e.proposal_id AND p.status='applied'
            JOIN test_runs t ON t.id=e.test_run_id AND t.returncode=0
            WHERE e.status='approved' AND e.outcome='test_pass'
              AND t.id=(SELECT MAX(t2.id) FROM test_runs t2 WHERE t2.proposal_id=e.proposal_id)
              AND e.evidence_sha256=t.output_sha256
              AND t.command <> 'athenz:ast.parse (no execution)'
              AND instr(t.command,' -m py_compile ') = 0
            ORDER BY e.id DESC""")
        ranked = [(relevance(query, r['task'] + ' ' + r['lesson']) if query is not None else 1,
                   i, dict(r)) for i, r in enumerate(rows)]
        ranked = [r for r in ranked if r[0] > 0]
        ranked.sort(key=lambda x: (x[0], -x[1]), reverse=True)
        return [r[2] for r in ranked[:limit]]

    def new_proposal(self, repo: str, task: str, changes: list[dict], summary: str) -> int:
        if not changes or not task.strip():
            raise ValueError('Proposal must have task and changes')
        # Do not prematurely commit the scheduler's lease-fenced transaction.
        with (nullcontext() if self.db.in_transaction else self.db):
            cur = self.db.execute('''INSERT INTO proposals(repo,task,changes_json,summary,status,created_at)
                                    VALUES (?,?,?,?,'proposed',?)''',
                                  (repo, task, json.dumps(changes), summary[:1000], utc_now()))
        return int(cur.lastrowid)

    def get_proposal(self, proposal_id: int) -> dict:
        row = self.db.execute('SELECT * FROM proposals WHERE id=?', (proposal_id,)).fetchone()
        if row is None:
            raise ValueError(f'Unknown proposal {proposal_id}')
        return dict(row)

    def update_proposal(self, proposal_id: int, expected: str, state: str) -> bool:
        if (expected, state) not in {('proposed', 'applied'), ('applied', 'undone')}:
            raise ValueError('Invalid proposal transition')
        with self.db:
            cur = self.db.execute('UPDATE proposals SET status=? WHERE id=? AND status=?',
                                  (state, proposal_id, expected))
            if cur.rowcount and state == 'undone':
                # A reverted patch must no longer be presented as an active successful procedure.
                self.db.execute("UPDATE experiences SET status='rejected' WHERE proposal_id=?",
                                (proposal_id,))
        return bool(cur.rowcount)

    def record_test(self, proposal_id: int, command: str, code: int,
                    output: str, files_sha256: str, lesson: str) -> int:
        raw_hash = hashlib.sha256(output.encode('utf-8')).hexdigest()
        with self.db:
            cur = self.db.execute('''INSERT INTO test_runs
                (proposal_id,command,returncode,output_excerpt,output_sha256,files_sha256,created_at)
                VALUES (?,?,?,?,?,?,?)''', (proposal_id, command, code, output[-8000:],
                                            raw_hash, files_sha256, utc_now()))
            task = self.get_proposal(proposal_id)['task']
            if code != 0:
                # Later failure invalidates previously promoted test-backed advice.
                self.db.execute("UPDATE experiences SET status='rejected' WHERE proposal_id=? AND status='approved'",
                                (proposal_id,))
            self.db.execute('''INSERT INTO experiences
                (proposal_id,test_run_id,task,outcome,lesson,status,evidence_sha256,created_at)
                VALUES (?,?,?,?,?,'pending',?,?)''',
                (proposal_id, cur.lastrowid, task, 'test_pass' if code == 0 else 'test_fail',
                 lesson, raw_hash, utc_now()))
        return int(cur.lastrowid)

    def forget_runtime(self, table: str, item_id: int) -> bool:
        if table not in {'messages', 'feedback', 'train_pairs', 'proposals', 'test_runs', 'experiences'}:
            raise ValueError('Unsupported deletion table')
        with self.db:
            # Deleting message -> feedback -> train pairs via ON DELETE CASCADE.
            # Derived personal memories require explicit source cleanup.
            if table == "messages":
                self._forget_message_memories("id=?", item_id)
            cur = self.db.execute(f'DELETE FROM {table} WHERE id=?', (item_id,))
            if cur.rowcount:
                self._event('deleted', table, item_id)
        return bool(cur.rowcount)

    def delete_mode_session(self, session: str, mode: str) -> int:
        """Remove one chat mode, including source-linked owner memories.

        Does not touch the same session name in the other chat mode.
        This operation may be called under a caller-held SQLite write
        transaction after a reviewed session digest was checked.
        """
        if (type(session) is not str or not session.strip()
                or type(mode) is not str or mode not in {"agent", "twin"}):
            raise ValueError("Choose a valid named Agent or Twin conversation")
        from contextlib import nullcontext
        # A caller may already hold BEGIN IMMEDIATE after reviewing a pinned
        # complete-session digest. Never commit that outer transaction early.
        context = nullcontext() if self.db.in_transaction else self.db
        with context:
            self._forget_message_memories("session=? AND mode=?", (session, mode))
            cur = self.db.execute(
                "DELETE FROM messages WHERE session=? AND mode=?", (session, mode))
            if cur.rowcount:
                self._event("session-mode-deleted", "messages", None)
        return int(cur.rowcount)

    def delete_session(self, session: str) -> int:
        with self.db:
            self._forget_message_memories("session=?", session)
            cur = self.db.execute('DELETE FROM messages WHERE session=?', (session,))
            if cur.rowcount:
                self._event('session-deleted', 'messages', None)
        return cur.rowcount
