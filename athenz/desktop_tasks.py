"""Foreground desktop task operations: narrow wrappers around reviewed sequences.

The only model call is an explicitly user-invoked *proposal*. No implicit
apply, unattended loop, host code execution, training or remote Git action.
A fresh SQLite connection is used for each call (safe for Tk worker threads).
"""
from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Callable

from .chat import OllamaClient
from .experience import ExperienceStore
from .sequencer import SequenceController
from .worker import Worker
from .scheduler import ProposalScheduler

KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class TaskUIError(ValueError):
    """Owner input did not meet the desktop task workflow requirements."""


def parse_stages(raw: str) -> list[list[str]]:
    """Parse owner-provided `file.py,file2.py; next.py` stage boundaries."""
    if not isinstance(raw, str) or not raw.strip():
        raise TaskUIError('Enter one to five stages, separated by semicolons')
    stages = [[part.strip() for part in s.split(',')] for s in raw.split(';')]
    if (not 1 <= len(stages) <= 5 or any(not 1 <= len(s) <= 4 or
         any(not name or not name.endswith('.py') for name in s) or
         len(s) != len(set(s)) for s in stages)):
        raise TaskUIError('Each of 1–5 stages must name 1–4 distinct existing Python files')
    return stages


class DesktopTasks:
    def __init__(self, home: Path | None = None):
        self.home = Path(home) if home is not None else None

    def _call(self, function: Callable[[SequenceController], object]):
        store = ExperienceStore(self.home)
        try:
            return function(SequenceController(Worker(store)))
        finally:
            store.close()

    @staticmethod
    def _key(key: str) -> str:
        if not isinstance(key, str) or not KEY.fullmatch(key):
            raise TaskUIError('Task key must be 1–64 letters, numbers, underscores or dashes')
        return key

    def list_tasks(self, limit: int = 100) -> list[dict]:
        if not isinstance(limit, int) or not 1 <= limit <= 300:
            raise TaskUIError('Invalid task list limit')
        def read(ctl):
            return [dict(task_key=r['task_key'], task=r['task'], status=r['status'],
                         revision=r['revision'], type=('sequence' if isinstance(json.loads(r['state_json']).get('sequence'), dict) else 'other'))
                    for r in ctl.store.db.execute(
                        'SELECT task_key,task,status,revision,state_json FROM checkpoints '
                        'ORDER BY updated_at DESC,id DESC LIMIT ?', (limit,))]
        rows = self._call(read)
        queues = {j['task_key']: j['state'] for j in ProposalScheduler(self.home).list()}
        for row in rows:
            row['scheduler'] = queues.get(row['task_key'], 'off')
        return rows

    def create(self, key: str, repo: Path | str, task: str, stages: list[list[str]], *,
               confirmed: bool = False) -> dict:
        if not confirmed:
            raise TaskUIError('Confirm creation of a disposable worktree first')
        self._key(key)
        if not isinstance(task, str) or not task.strip() or len(task) > 500:
            raise TaskUIError('Describe a coding task in 1–500 characters')
        if not isinstance(stages, list) or not 1 <= len(stages) <= 5:
            raise TaskUIError('Select 1–5 file-scope stages')
        return self._call(lambda ctl: ctl.start(key, Path(repo), task, stages))

    def detail(self, key: str) -> dict:
        self._key(key)
        def read(ctl):
            item, seq = ctl._load(key)
            return {**ctl.status(key), 'task': item['task'],
                    'repository': item['state']['repo'],
                    'workspace': item['state']['workspace'],
                    'stages': seq['stages'],
                    'review_bundle': seq.get('final_review')}
        data = self._call(read)
        data['scheduler'] = ProposalScheduler(self.home).get(key)
        return data

    def prepare(self, key: str, *, model=None) -> dict:
        self._key(key)
        return self._call(lambda ctl: ctl.prepare(key, model if model is not None else OllamaClient()))

    def review(self, key: str) -> dict:
        self._key(key)
        return self._call(lambda ctl: ctl.review(key))

    def apply(self, key: str, digest: str, *, confirmed: bool = False) -> dict:
        if not confirmed:
            raise TaskUIError('Explicit owner confirmation is required before changing files')
        self._key(key)
        if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            raise TaskUIError('Enter the exact 64-character review SHA-256')
        return self._call(lambda ctl: {'changed_files': ctl.apply(key, digest)})

    def syntax(self, key: str) -> dict:
        self._key(key)
        return self._call(lambda ctl: ctl.syntax(key))

    def advance(self, key: str, *, confirmed: bool = False) -> dict:
        if not confirmed:
            raise TaskUIError('Confirm accepting the syntax-checked stage')
        self._key(key)
        return self._call(lambda ctl: ctl.advance(key))

    def recover(self, key: str) -> dict:
        self._key(key)
        return self._call(lambda ctl: ctl.recover(key))

    def test(self, key: str, image: str, *, confirmed: bool = False, timeout: int = 120) -> dict:
        if not confirmed:
            raise TaskUIError('Explicit confirmation required for container code execution')
        self._key(key)
        # Sequence verifies phase and the pinned image before attempting Docker.
        return self._call(lambda ctl: ctl.verify_container(key, image=image, timeout=timeout))

    def export(self, key: str, *, confirmed: bool = False) -> dict:
        if not confirmed:
            raise TaskUIError('Explicit confirmation required to export a private code patch')
        self._key(key)
        return self._call(lambda ctl: ctl.export(key))

    def cancel(self, key: str, *, discard_changes: bool = False, confirmed: bool = False) -> dict:
        if not confirmed:
            raise TaskUIError('Explicit confirmation required to cancel a task')
        self._key(key)
        return self._call(lambda ctl: (ctl.cancel(key, discard_changes=discard_changes) or
                                       {'status': 'cancelled', 'discarded': discard_changes}))

    # Scheduler is OFF by default. Only creates model proposals. Never applies.
    def schedule_add(self, key: str, model: str, *, confirmed: bool = False) -> dict:
        return ProposalScheduler(self.home).register(self._key(key), model=model, confirmed=confirmed)

    def schedule_arm(self, key: str, *, confirmed: bool = False) -> dict:
        return ProposalScheduler(self.home).arm(self._key(key), confirmed=confirmed)

    def schedule_pause(self, key: str) -> dict:
        return ProposalScheduler(self.home).pause(self._key(key))

    def schedule_cancel(self, key: str, *, confirmed: bool = False) -> dict:
        return ProposalScheduler(self.home).cancel(self._key(key), confirmed=confirmed)

    def schedule_recover(self, key: str, *, confirmed: bool = False) -> dict:
        return ProposalScheduler(self.home).recover(self._key(key), confirmed=confirmed)

    def schedule_remove(self, key: str, *, confirmed: bool = False) -> dict:
        return {'removed': ProposalScheduler(self.home).remove(self._key(key), confirmed=confirmed)}

    def schedule_tick(self, *, confirmed: bool = False) -> dict:
        # Desktop button runs one foreground-requested tick only.
        return ProposalScheduler(self.home).run_once(confirmed=confirmed)
