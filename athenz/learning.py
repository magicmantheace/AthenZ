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
from .store import IdentityStore, STATES, utc_now
from .style_overlap import strongly_overlaps


def _writing_split_key(text: str) -> str:
    """Conservative normalized exact-duplicate check, not semantic overlap."""
    return ' '.join(re.findall(
        r'\w+', unicodedata.normalize('NFKC', text).casefold()))


class LearningStore(IdentityStore):
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
            # Deleting message -> feedback -> training pairs via ON DELETE CASCADE.
            # Deleting proposal -> tests -> experiences via ON DELETE CASCADE.
            cur = self.db.execute(f'DELETE FROM {table} WHERE id=?', (item_id,))
            if cur.rowcount:
                self._event('deleted', table, item_id)
        return bool(cur.rowcount)

    def delete_session(self, session: str) -> int:
        with self.db:
            cur = self.db.execute('DELETE FROM messages WHERE session=?', (session,))
            if cur.rowcount:
                self._event('session-deleted', 'messages', None)
        return cur.rowcount
