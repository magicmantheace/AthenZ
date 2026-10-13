"""Opt-in, private supervised coding proposal scheduler.

A queued job can ONLY prepare the next model proposal for an existing,
owner-scoped SequenceController. No apply, tests, Git write/push, feedback
approval, training or model deployment. Nothing starts automatically.

The owner must explicitly arm *each* stage and invoke a foreground tick/serve.
A durable lease makes process crashes stop safely instead of replaying a model
call; recover requires a human and never invokes the model.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
import re
import time
import uuid
from pathlib import Path

from .chat import OllamaClient
from .adapters import ALIAS
from .experience import ExperienceStore
from .sequencer import SequenceController
from .store import utc_now
from .worker import Worker

KEY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')


class SchedulerError(ValueError):
    """A scheduled action did not meet its owner-authorized boundaries."""


def _scope(item: dict, seq: dict) -> str:
    """Pin immutable owner authority; stage index/approved edits may advance."""
    obj = {'task_key': item['task_key'], 'task': item['task'],
           'repo': item['state']['repo'], 'workspace': item['state']['workspace'],
           'base_sha': item['state']['base_sha'], 'stages': seq['stages']}
    raw = json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


class ProposalScheduler:
    """Transactional local queue; uses separate store handles for each method.

    SQLite BEGIN IMMEDIATE serializes multiple local scheduler processes. An
    interrupted 'running' lease is never reclaimed without an explicit recover.
    """
    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home is not None else None
        with self._open() as store:
            # This is private operational metadata, not a source repo migration.
            store.db.execute('''CREATE TABLE IF NOT EXISTS proposal_schedule (
                task_key TEXT PRIMARY KEY,
                scope_sha256 TEXT NOT NULL,
                model_name TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('paused','armed','running','review')),
                lease TEXT,
                last_result TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )''')
            store.db.commit()

    @contextmanager
    def _open(self):
        store = ExperienceStore(self.home)
        try:
            yield store
        finally:
            store.close()

    @staticmethod
    def _key(key: str) -> str:
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise SchedulerError('Task key must be 1–64 safe letters, numbers, dashes or underscores')
        return key

    @staticmethod
    def _load(store: ExperienceStore, key: str) -> tuple[SequenceController, dict, dict]:
        ctl = SequenceController(Worker(store))
        item, seq = ctl._load(key)
        return ctl, item, seq

    def get(self, key: str) -> dict | None:
        self._key(key)
        with self._open() as store:
            row = store.db.execute('SELECT * FROM proposal_schedule WHERE task_key=?', (key,)).fetchone()
            return dict(row) if row else None

    def list(self) -> list[dict]:
        with self._open() as store:
            return [dict(r) for r in store.db.execute(
                'SELECT * FROM proposal_schedule ORDER BY updated_at DESC LIMIT 100')]

    def register(self, key: str, *, model: str, confirmed: bool = False) -> dict:
        if not confirmed:
            raise SchedulerError('Explicit owner confirmation required to queue a proposal')
        self._key(key)
        # OllamaClient performs local endpoint and model-name validation.
        if not isinstance(model, str) or not ALIAS.fullmatch(model):
            raise SchedulerError('Specify a safe local Ollama model tag')
        OllamaClient(model=model)
        with self._open() as store:
            ctl, item, seq = self._load(store, key)
            if seq['phase'] != 'ready':
                raise SchedulerError('Only a ready sequence stage may be queued')
            ctl._integrity(item, seq)
            expected = _scope(item, seq)
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                if store.db.execute('SELECT 1 FROM proposal_schedule WHERE task_key=?', (key,)).fetchone():
                    raise SchedulerError('Job already exists; pause, inspect or remove before changing authority')
                store.db.execute('''INSERT INTO proposal_schedule
                    (task_key,scope_sha256,model_name,state,lease,created_at,updated_at)
                    VALUES (?,?,?,'paused',NULL,?,?)''', (key, expected, model, utc_now(), utc_now()))
        return self.get(key)

    def arm(self, key: str, *, confirmed: bool = False) -> dict:
        if not confirmed:
            raise SchedulerError('Explicit owner approval required to arm each proposal stage')
        self._key(key)
        with self._open() as store:
            ctl, item, seq = self._load(store, key)
            if seq['phase'] != 'ready':
                raise SchedulerError('Stage must be ready; review, apply and advance manually first')
            ctl._integrity(item, seq)
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                row = store.db.execute('SELECT * FROM proposal_schedule WHERE task_key=?', (key,)).fetchone()
                if not row or row['state'] not in ('paused', 'review') or row['lease'] is not None:
                    raise SchedulerError('Job is missing, already armed or has an unreconciled in-flight lease')
                if _scope(item, seq) != row['scope_sha256']:
                    raise SchedulerError('Owner-authorized repository, task or stage scope changed')
                store.db.execute("UPDATE proposal_schedule SET state='armed',last_result='',updated_at=? WHERE task_key=?",
                                 (utc_now(), key))
        return self.get(key)

    def pause(self, key: str) -> dict:
        self._key(key)
        with self._open() as store:
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                row = store.db.execute('SELECT state FROM proposal_schedule WHERE task_key=?', (key,)).fetchone()
                if not row:
                    raise SchedulerError('No such scheduled task')
                # Pausing an in-flight inference does not abort it: the lease
                # persists, and completion cannot re-arm this job.
                store.db.execute("UPDATE proposal_schedule SET state='paused',updated_at=? WHERE task_key=?",
                                 (utc_now(), key))
        return self.get(key)

    def remove(self, key: str, *, confirmed: bool = False) -> bool:
        """Forget a paused/reviewed queue entry; never delete its worktree."""
        if not confirmed:
            raise SchedulerError('Explicit owner confirmation required to remove a queue entry')
        self._key(key)
        with self._open() as store:
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                row = store.db.execute('SELECT state,lease FROM proposal_schedule WHERE task_key=?', (key,)).fetchone()
                if not row:
                    return False
                if row['state'] not in ('paused', 'review') or row['lease']:
                    raise SchedulerError('Pause and reconcile active inference before removing a job')
                store.db.execute('DELETE FROM proposal_schedule WHERE task_key=?', (key,))
        return True

    def recover(self, key: str, *, confirmed: bool = False) -> dict:
        """Owner-reconcile interrupted work, never replay inference."""
        if not confirmed:
            raise SchedulerError('Confirm manual reconciliation of the interrupted job')
        self._key(key)
        with self._open() as store:
            # Check authorization before sequence recovery can touch the
            # worktree (including completing an interrupted rollback).
            prior = store.db.execute(
                'SELECT * FROM proposal_schedule WHERE task_key=?', (key,)).fetchone()
            if not prior or prior['state'] not in ('running', 'paused') or not prior['lease']:
                raise SchedulerError('No interrupted job needs manual reconciliation')
            original_lease = prior['lease']
            ctl, item, seq = self._load(store, key)
            if _scope(item, seq) != prior['scope_sha256']:
                raise SchedulerError('Scheduled task authority changed')
            ctl.recover(key)  # checks workspace and completes pending rollback only
            ctl, item, seq = self._load(store, key)
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                row = store.db.execute('SELECT * FROM proposal_schedule WHERE task_key=?', (key,)).fetchone()
                if (not row or row['state'] not in ('running', 'paused')
                        or row['lease'] != original_lease):
                    raise SchedulerError('Interrupted lease changed during recovery; reload job')
                if _scope(item, seq) != row['scope_sha256']:
                    raise SchedulerError('Scheduled task authority changed')
                target = 'review' if seq['phase'] == 'awaiting_review' else 'paused'
                store.db.execute('''UPDATE proposal_schedule SET state=?,lease=NULL,
                    last_result='owner-reconciled: no automatic retry',updated_at=? WHERE task_key=?''',
                    (target, utc_now(), key))
        return self.get(key)

    def run_once(self, *, confirmed: bool = False, model_factory=None) -> dict:
        """Claim at most one ARMED proposal, then stop for independent review."""
        if not confirmed:
            raise SchedulerError('Foreground run requires explicit --confirm')
        with self._open() as store:
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                row = store.db.execute("SELECT * FROM proposal_schedule WHERE state='armed' ORDER BY updated_at,task_key LIMIT 1").fetchone()
                if row is None:
                    return {'status': 'idle', 'proposals': 0}
                key = row['task_key']
                lease = uuid.uuid4().hex
                store.db.execute("UPDATE proposal_schedule SET state='running',lease=?,updated_at=? WHERE task_key=? AND state='armed'",
                                 (lease, utc_now(), key))

            # Every side effect is outside the DB lease transaction, so other
            # processes can pause while local inference is in flight.
            try:
                ctl, item, seq = self._load(store, key)
                if seq['phase'] != 'ready' or _scope(item, seq) != row['scope_sha256']:
                    raise SchedulerError('Stage or originally authorized task scope changed')
                ctl._integrity(item, seq)
                model = model_factory(row['model_name']) if model_factory else OllamaClient(model=row['model_name'])

                class LeasedModel:
                    # If a pause/revocation occurs during model construction,
                    # refuse BEFORE transmitting any source context to Ollama.
                    # The post-inference SQLite writer fence independently
                    # blocks persistence if permission changes after sending.
                    def generate(self, *args, **kwargs):
                        status = store.db.execute(
                            'SELECT state,lease FROM proposal_schedule WHERE task_key=?',
                            (key,)).fetchone()
                        if (status is None or status['state'] != 'running'
                                or status['lease'] != lease):
                            raise SchedulerError('Model request was paused or revoked before generation')
                        return model.generate(*args, **kwargs)

                def fence() -> None:
                    # Executed under the proposal's SQLite IMMEDIATE writer
                    # transaction, never while network inference is pending.
                    # A concurrent pause that commits first invalidates the
                    # lease, and its response is discarded without persistence.
                    current = store.db.execute(
                        'SELECT state,lease,scope_sha256 FROM proposal_schedule WHERE task_key=?',
                        (key,)).fetchone()
                    if (current is None or current['state'] != 'running'
                            or current['lease'] != lease
                            or current['scope_sha256'] != row['scope_sha256']):
                        raise SchedulerError('Proposal authorization was paused or revoked')
                    verified_ctl, verified_item, verified_seq = self._load(store, key)
                    if (verified_seq['phase'] != 'ready' or
                            _scope(verified_item, verified_seq) != row['scope_sha256']):
                        raise SchedulerError('Authorized stage changed while preparing a proposal')
                    verified_ctl._integrity(verified_item, verified_seq)
                result = ctl.prepare(key, LeasedModel(), before_persist=fence)
                outcome, note = 'review', 'proposal awaits owner SHA-256 review'
            except Exception as exc:
                # Local model/runner exceptions can embed paths, model output,
                # private prompts or external error messages. Never forward
                # them into status JSON, SQLite notes or CLI/UI output.
                # Failed proposal/checkpoint transactions roll back together.
                reason = ('authorization-or-scope-revoked'
                          if isinstance(exc, SchedulerError)
                          else 'local-proposal-failed')
                outcome, note = 'paused', 'refused: ' + reason
                result = {'status': 'refused', 'task_key': key, 'error': reason}
            with store.db:
                store.db.execute('BEGIN IMMEDIATE')
                actual = store.db.execute('SELECT state,lease FROM proposal_schedule WHERE task_key=?', (key,)).fetchone()
                if actual and actual['lease'] == lease:
                    if actual['state'] == 'running':
                        store.db.execute('''UPDATE proposal_schedule SET state=?,lease=NULL,
                            last_result=?,updated_at=? WHERE task_key=?''',
                            (outcome, note, utc_now(), key))
                    elif actual['state'] == 'paused':
                        # A pause after proposal persistence still wins the
                        # visible queue state. Review remains owner-controlled.
                        outcome = 'paused'
                        store.db.execute('''UPDATE proposal_schedule SET lease=NULL,
                            last_result=?,updated_at=? WHERE task_key=?''',
                            ('owner paused; inspect stage before re-arming', utc_now(), key))
            # Never auto-approve, apply, advance, perform host tests or push.
            return {'status': outcome, 'task_key': key, 'result': result}

    def serve(self, *, confirmed: bool = False, ticks: int = 1, interval: int = 30,
              on_tick=None, model_factory=None) -> list[dict]:
        """Bounded foreground poll. Not a daemon, not persistent on reboot."""
        if not confirmed or type(ticks) is not int or not 1 <= ticks <= 120 or \
                type(interval) is not int or not 5 <= interval <= 3600:
            raise SchedulerError('Confirm 1–120 foreground checks at intervals of 5–3600 seconds')
        events = []
        for i in range(ticks):
            event = self.run_once(confirmed=True, model_factory=model_factory)
            events.append(event)
            if on_tick:
                on_tick(event)
            if i + 1 < ticks:
                time.sleep(interval)
        return events
