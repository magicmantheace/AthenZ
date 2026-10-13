"""Sequential, independently reviewed code patches inside one private Git worktree.

This is a foreground controller, not an autonomous executor or OS sandbox.
Every stage has an owner-fixed file scope and fresh SHA-256 approval. The
checkpoint pins the complete expected tree before any subsequent model call.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from pathlib import Path

from .coding import allowed_file, change_status, digest, diff_for, propose, read_exact
from .controller import proposal_digest
from .worker import Worker, WorktreeError, _git
from .verification import isolated_unittest, snapshot_files


class SequenceError(WorktreeError):
    """A task phase, approval, or workspace integrity check failed."""


class SequenceController:
    MAX_STAGES = 5
    MAX_FAILURES = 3

    def __init__(self, worker: Worker):
        self.worker = worker
        self.store = worker.store

    def _load(self, key: str) -> tuple[dict, dict]:
        item = self.worker.resume(key)
        sequence = item['state'].get('sequence')
        if not isinstance(sequence, dict) or sequence.get('phase') not in {
            'ready', 'awaiting_review', 'applied', 'validated',
            'rollback_pending', 'blocked', 'complete', 'exported',
        }:
            raise SequenceError('No sequential task plan exists for this worktree')
        return item, sequence

    def _save(self, key: str, item: dict, seq: dict) -> None:
        state = dict(item['state'])
        state['sequence'] = seq
        self.store.checkpoint(key, item['task'], state, status='paused',
                              expected_revision=item['revision'])

    @staticmethod
    def _hashes(seq: dict, current: dict | None = None) -> dict[str, str]:
        hashes = dict(seq['expected'])
        if current:
            for c in current['changes']:
                hashes[c['path']] = c['after_sha256']
        return hashes

    def _integrity(self, item: dict, seq: dict, *, current: dict | None = None) -> None:
        """Reject edits, untracked files, staging, and unapproved scope expansion."""
        workspace = Path(item['state']['workspace'])
        expected = self._hashes(seq, current)
        actual_changed = set()
        for rel, sha in expected.items():
            path = allowed_file(workspace, rel)
            if digest(read_exact(path)) != sha:
                raise SequenceError(f'Workspace content differs from reviewed state: {rel}')
            if sha != seq['baseline'][rel]:
                actual_changed.add(rel)
        raw = _git(workspace, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
        entries = [e for e in raw.split('\0') if e]
        # Never allow staged/untracked/renamed files, even inside authorized scope.
        if any(len(e) < 4 or e[:3] != ' M ' for e in entries):
            raise SequenceError('Unapproved, staged or untracked workspace changes')
        if {e[3:] for e in entries} != actual_changed or len(entries) != len(actual_changed):
            raise SequenceError('Unexpected Git working tree state')

    def start(self, key: str, repository: str | Path, task: str, stages: list[list[str]],
              *, max_failures: int = 2) -> dict:
        if not 1 <= len(stages) <= self.MAX_STAGES or not 1 <= max_failures <= self.MAX_FAILURES:
            raise ValueError('Select 1–5 stages and a retry budget of 1–3')
        if any(not isinstance(stage, list) or not 1 <= len(stage) <= 4 or
               any(not isinstance(p, str) or not p.endswith('.py') for p in stage) or
               len(stage) != len(set(stage)) for stage in stages):
            raise ValueError('Each stage needs 1–4 distinct existing Python files')
        item = self.worker.begin(key, repository, task)
        workspace = Path(item['state']['workspace'])
        try:
            scope = sorted({p for stage in stages for p in stage})
            baseline = {p: digest(read_exact(allowed_file(workspace, p))) for p in scope}
            seq = {'phase': 'ready', 'stages': stages, 'index': 0, 'current': None,
                   'baseline': baseline, 'expected': dict(baseline),
                   'approved': [], 'failures': 0, 'max_failures': max_failures,
                   'last_error': '', 'final_review': None}
            self._save(key, item, seq)
        except BaseException:
            self.worker.cleanup(key, discard_changes=True, disposition='cancelled')
            raise
        return self.status(key)

    def _proposal(self, seq: dict) -> dict:
        if seq['current'] is None:
            raise SequenceError('No active reviewed proposal')
        proposal = self.store.get_proposal(seq['current'])
        return {'id': proposal['id'], 'status': proposal['status'],
                'changes': json.loads(proposal['changes_json']),
                'sha256': proposal_digest(proposal['changes_json'])}

    def prepare(self, key: str, model, *, before_persist=None) -> dict:
        item, seq = self._load(key)
        if seq['phase'] != 'ready' or seq['index'] >= len(seq['stages']):
            raise SequenceError('Current stage is not ready for a proposal')
        self._integrity(item, seq)

        def check_authority() -> None:
            # Caller holds BEGIN IMMEDIATE: a sequence modification, revised
            # task, or worktree edit during inference invalidates this result.
            if before_persist is not None:
                before_persist()
            latest_item, latest_seq = self._load(key)
            if (latest_item['revision'] != item['revision']
                    or latest_seq['phase'] != 'ready'):
                raise SequenceError('Sequence checkpoint changed while preparing proposal')
            self._integrity(latest_item, latest_seq)

        if seq['current'] is not None:
            row = self._proposal(seq)
            if row['status'] != 'proposed':
                raise SequenceError('Outstanding proposal needs review or rollback')
            # Legacy recovery of an already-stored proposal also needs the
            # currently authorized lease, when invoked by the scheduler.
            with self.store.db:
                self.store.db.execute('BEGIN IMMEDIATE')
                check_authority()
                self._save(key, item, {**seq, 'phase': 'awaiting_review'})
            return self.review(key)

        files = seq['stages'][seq['index']]
        # Only these owner-selected files are readable by the model. The
        # model cannot change file scope by returning extra paths.
        prompt = (f"{item['task']} (stage {seq['index'] + 1}/{len(seq['stages'])}). "
                  f"Prior syntax error: {seq['last_error'][:500]}")

        def persist_checkpoint(pid: int) -> None:
            # Executed in coding.propose's SQLite IMMEDIATE transaction.
            # A failed checkpoint rolls back its proposal insert as well.
            self._save(key, item, {**seq, 'current': pid,
                                   'phase': 'awaiting_review'})

        propose(self.store, model, item['state']['workspace'], prompt, files,
                before_persist=check_authority, after_persist=persist_checkpoint)
        return self.review(key)

    def review(self, key: str) -> dict:
        item, seq = self._load(key)
        if seq['phase'] not in {'awaiting_review', 'applied', 'validated', 'blocked'}:
            raise SequenceError('No stage currently awaiting review')
        row = self._proposal(seq)
        return {'stage': seq['index'] + 1, 'proposal_id': row['id'],
                'sha256': row['sha256'], 'phase': seq['phase'],
                'diff': diff_for(self.store, row['id'])}

    def apply(self, key: str, approval_sha256: str) -> int:
        item, seq = self._load(key)
        if seq['phase'] != 'awaiting_review':
            raise SequenceError('Proposal must be awaiting approval')
        row = self._proposal(seq)
        if not re.fullmatch(r'[0-9a-f]{64}', approval_sha256) or approval_sha256 != row['sha256']:
            raise SequenceError('Owner approval does not match proposed patch')
        # Recover a crash after apply but before checkpoint persistence.
        if row['status'] == 'proposed':
            self._integrity(item, seq)
            changed = change_status(self.store, row['id'])
        elif row['status'] == 'applied':
            changed = len(row['changes'])
        else:
            raise SequenceError('Proposal was reverted or removed')
        self._integrity(item, seq, current=row)
        item, seq = self._load(key)
        seq = dict(seq)
        seq['phase'] = 'applied'
        self._save(key, item, seq)
        return changed

    def _complete_rollback(self, key: str) -> dict:
        item, seq = self._load(key)
        if seq['phase'] != 'rollback_pending':
            raise SequenceError('No rollback pending')
        row = self._proposal(seq)
        if row['status'] == 'applied':
            self._integrity(item, seq, current=row)
            change_status(self.store, row['id'], undo=True)
        elif row['status'] != 'undone':
            raise SequenceError('Proposal cannot be rolled back')
        self._integrity(item, seq)
        item, seq = self._load(key)
        seq = dict(seq)
        seq['current'] = None
        seq['phase'] = 'blocked' if seq['failures'] >= seq['max_failures'] else 'ready'
        self._save(key, item, seq)
        return self.status(key)

    def recover(self, key: str) -> dict:
        item, seq = self._load(key)
        if seq['phase'] == 'rollback_pending':
            return self._complete_rollback(key)
        self._integrity(item, seq, current=self._proposal(seq)
                        if seq['phase'] in {'applied', 'validated'} else None)
        return self.status(key)

    def syntax(self, key: str) -> dict:
        item, seq = self._load(key)
        if seq['phase'] == 'rollback_pending':
            return self._complete_rollback(key)
        if seq['phase'] not in {'applied', 'validated'}:
            raise SequenceError('Apply a reviewed patch before syntax validation')
        row = self._proposal(seq)
        if row['status'] != 'applied':
            raise SequenceError('Patch no longer applied')
        self._integrity(item, seq, current=row)
        workspace = Path(item['state']['workspace'])
        lines = []
        for rel in sorted(seq['baseline']):
            try:
                ast.parse(read_exact(allowed_file(workspace, rel)), filename=rel)
                lines.append(f'{rel}: parsed')
            except SyntaxError as exc:
                lines.append(f'{rel}: line {exc.lineno}: invalid syntax')
        failed = any('invalid syntax' in line for line in lines)
        files_hash = digest(''.join(p + h for p, h in sorted(self._hashes(seq, row).items())))
        observed = '\n'.join(lines)
        test_id = self.store.record_test(row['id'], 'athenz:ast.parse (no execution)',
                                         1 if failed else 0, observed, files_hash,
                                         'All authorized Python files parsed without execution')
        item, seq = self._load(key)
        seq = dict(seq)
        seq['syntax_test_id'] = test_id
        if failed:
            seq['last_error'] = observed[-500:]
            seq['failures'] += 1
            seq['phase'] = 'rollback_pending'
            self._save(key, item, seq)
            outcome = self._complete_rollback(key)
            return {'passed': False, 'test_run_id': test_id, 'phase': outcome['phase'], 'output': observed}
        seq['phase'] = 'validated'
        self._save(key, item, seq)
        return {'passed': True, 'test_run_id': test_id, 'phase': 'validated', 'output': observed}

    def advance(self, key: str) -> dict:
        item, seq = self._load(key)
        if seq['phase'] != 'validated':
            raise SequenceError('Successful syntax validation required before advancing')
        row = self._proposal(seq)
        if row['status'] != 'applied':
            raise SequenceError('Verified proposal was reverted')
        self._integrity(item, seq, current=row)
        seq = dict(seq)
        seq['expected'] = self._hashes(seq, row)
        seq['approved'] = [*seq['approved'], {'stage': seq['index'], 'proposal_id': row['id'],
                       'sha256': row['sha256'], 'files': [c['path'] for c in row['changes']],
                       'test_run_id': seq.get('syntax_test_id')}]
        seq['index'] += 1
        seq['current'] = None
        seq['failures'] = 0
        seq['last_error'] = ''
        seq['phase'] = 'complete' if seq['index'] == len(seq['stages']) else 'ready'
        self._save(key, item, seq)
        return self.status(key)

    def verify_container(self, key: str, *, image: str, timeout: int = 120) -> dict:
        """Owner-approved full-task behavioral test; syntax-only is not proof.

        Verified bytes are copied into a private, disposable snapshot. The
        observed Docker outcome and hashes are retained in the private store,
        but never promoted as a learned lesson without additional review.
        """
        item, seq = self._load(key)
        if seq['phase'] != 'complete':
            raise SequenceError('Finish all approved stages before behavioral verification')
        self._integrity(item, seq)
        workspace = Path(item['state']['workspace'])
        result = isolated_unittest(workspace, image=image, home=self.store.home, timeout=timeout)
        # Do not let late results from a superseded owner task, rollback or
        # revised scope become independent test evidence. Both this check and
        # _save's revision CAS are required; local file hashes alone cannot
        # establish which checkpoint authorized the container run.
        latest_item, latest_seq = self._load(key)
        if (latest_item['revision'] != item['revision']
                or latest_seq != seq or latest_seq['phase'] != 'complete'):
            raise SequenceError('Sequence checkpoint changed during container verification')
        self._integrity(latest_item, latest_seq)
        proposal_id = seq['approved'][-1]['proposal_id']
        files_digest = result['snapshot_sha256']
        test_id = self.store.record_test(
            proposal_id, 'docker:sequence unittest (local observation)',
            result['returncode'], result['output'], files_digest,
            'Full sequence unittest result (owner review required)')
        row = self.store.db.execute('SELECT output_sha256 FROM test_runs WHERE id=?',
                                    (test_id,)).fetchone()
        item, seq = self._load(key)
        if item['revision'] != latest_item['revision'] or seq != latest_seq:
            raise SequenceError('Sequence checkpoint changed before evidence persistence')
        seq = dict(seq)
        seq['behavioral_evidence'] = {
            'test_run_id': test_id, 'runner': result['runner'], 'image': result['image'],
            'returncode': result['returncode'], 'snapshot_sha256': files_digest,
            'output_sha256': result['output_sha256'],
            'stored_excerpt_sha256': row['output_sha256'],
            'cleanup': result['cleanup'], 'tracked_files': result['tracked_files'],
            'snapshot_bytes': result['snapshot_bytes'],
        }
        self._save(key, item, seq)
        return {**result, 'test_run_id': test_id}

    def export(self, key: str) -> dict:
        item, seq = self._load(key)
        if seq['phase'] not in {'complete', 'exported'}:
            raise SequenceError('All reviewed stages must be validated before export')
        self._integrity(item, seq)
        workspace = Path(item['state']['workspace'])
        files = sorted(p for p, sha in seq['expected'].items() if sha != seq['baseline'][p])
        if not files:
            raise SequenceError('No cumulative changes remain to export')
        patch = _git(workspace, 'diff', '--no-ext-diff', '--no-textconv', '--binary', '--', *files) + '\n'
        if not patch.strip() or len(patch.encode('utf-8')) > 512_000:
            raise SequenceError('Combined review patch is empty or oversized')
        sha = hashlib.sha256(patch.encode('utf-8')).hexdigest()
        reviews = self.store.home.resolve() / 'reviews'
        if reviews.is_symlink():
            raise SequenceError('Review directory may not be a symlink')
        reviews.mkdir(mode=0o700, parents=True, exist_ok=True)
        if reviews.resolve() != reviews:
            raise SequenceError('Unsafe review directory')
        dest = reviews / f'{key}-combined-{sha[:20]}.patch'
        prev = seq.get('final_review')
        if prev:
            if (prev['sha256'] != sha or not dest.is_file() or dest.is_symlink()
                    or hashlib.sha256(dest.read_bytes()).hexdigest() != sha):
                raise SequenceError('Previously exported artifact changed')
            return prev
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        try:
            fd = os.open(dest, flags, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(patch.encode('utf-8'))
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if dest.is_symlink() or hashlib.sha256(dest.read_bytes()).hexdigest() != sha:
                raise SequenceError('Conflicting review artifact exists')
            # Crash recovery: immutable patch created before checkpoint update.
        evidence = seq.get('behavioral_evidence')
        if evidence is not None:
            # A test result is only meaningful for the exact final snapshot.
            # Compute on a disposable temp copy; never execute project code.
            import tempfile
            with tempfile.TemporaryDirectory(prefix='athenz-check-') as temp:
                snapshot = snapshot_files(workspace, Path(temp))
            if snapshot['snapshot_sha256'] != evidence['snapshot_sha256']:
                raise SequenceError('Behavioral evidence does not match final workspace')
            row = self.store.db.execute('SELECT * FROM test_runs WHERE id=?',
                                        (evidence['test_run_id'],)).fetchone()
            if row is None or row['files_sha256'] != evidence['snapshot_sha256'] \
                    or row['returncode'] != evidence['returncode'] \
                    or row['output_sha256'] != evidence['stored_excerpt_sha256']:
                raise SequenceError('Behavioral evidence record is missing or contradictory')
        level = ('container-tests-observed' if evidence and evidence['returncode'] == 0
                 else 'container-tests-failed' if evidence else 'syntax-only')
        output = {'path': str(dest), 'sha256': sha, 'files': files,
                  'base_sha': item['state']['base_sha'], 'stages': len(seq['approved']),
                  'verification': level, 'behavioral_evidence': evidence,
                  'test_run_ids': [e['test_run_id'] for e in seq['approved']]}
        seq = dict(seq)
        seq['final_review'] = output
        seq['phase'] = 'exported'
        self._save(key, item, seq)
        return output

    def cancel(self, key: str, *, discard_changes: bool = False) -> None:
        item, seq = self._load(key)
        if seq['phase'] == 'rollback_pending':
            self._complete_rollback(key)
            item, seq = self._load(key)
        # Worktree cleanup itself cannot distinguish earlier applied proposals.
        # All approved lessons from this discarded sequence must be revoked.
        # A refused non-destructive cancellation must not revoke lessons.
        # Check the dirty worktree before changing any evidence status.
        if not discard_changes and _git(Path(item['state']['workspace']),
                                        'status', '--porcelain=v1', '--untracked-files=all'):
            raise SequenceError('Workspace contains edits; --discard-changes required')
        # Revoke evidence *before* filesystem removal. A crash during removal
        # must not leave trusted lessons pointing to a discarded workspace.
        ids = [stage['proposal_id'] for stage in seq['approved']]
        if seq['current'] is not None:
            ids.append(seq['current'])
        with self.store.db:
            for pid in ids:
                self.store.db.execute("UPDATE experiences SET status='rejected' WHERE proposal_id=?", (pid,))
        self.worker.cleanup(key, discard_changes=discard_changes, disposition='cancelled')
        for pid in ids:
            row = self.store.get_proposal(pid)
            if row['status'] == 'applied':
                self.store.update_proposal(pid, 'applied', 'undone')

    def status(self, key: str) -> dict:
        item, seq = self._load(key)
        return {'key': key, 'phase': seq['phase'], 'stage': seq['index'] + 1,
                'total_stages': len(seq['stages']), 'approved_steps': len(seq['approved']),
                'failures': seq['failures'], 'max_failures': seq['max_failures'],
                'current_proposal_id': seq['current'], 'last_error': seq['last_error']}
