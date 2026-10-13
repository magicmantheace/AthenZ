"""Supervised, restart-safe Git worktree coding sessions.

A Git worktree isolates file edits from the owner checkout; it is *not* an OS
security sandbox. This module does not execute repository programs on the host.
All model-generated edits require explicit apply; tests requiring execution can
only run via an opt-in, locked-down container runner.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import uuid
from pathlib import Path

from .coding import allowed_file, change_status, digest, propose, read_exact
from .experience import ExperienceStore

KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
IMAGE = re.compile(r"[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}\Z")


class WorktreeError(RuntimeError):
    """Rejected operation or unsafe workspace state."""


def _git(repo: Path, *args: str) -> str:
    # No shell; no model-controlled Git flags, and no prompts/remote operations.
    cmd = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'protocol.file.allow=never',
           '-C', str(repo), *args]
    try:
        process = subprocess.run(cmd, text=True, capture_output=True, check=False,
                                 timeout=45, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    except (OSError, subprocess.TimeoutExpired):
        raise WorktreeError('Local Git command unavailable or timed out') from None
    if process.returncode:
        # Git stderr/stdout can embed a selected owner's path, credentials in
        # remote configuration, private worktree filenames or hook diagnostics.
        # Never return process output in UI/CLI errors.
        raise WorktreeError('Local Git operation failed; inspect the trusted repository manually')
    return process.stdout.rstrip('\n')


class Worker:
    def __init__(self, store: ExperienceStore):
        self.store = store
        self.root = store.home.resolve() / 'worktrees'
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or self.root.resolve() != self.root:
            raise WorktreeError('Unsafe worktree root')

    def begin(self, key: str, repository: str | Path, task: str) -> dict:
        """Create a detached checkout of an explicitly selected *clean* repository."""
        if not KEY.fullmatch(key) or not task.strip() or len(task) > 500:
            raise ValueError('Invalid task key or task')
        if self.store.get_checkpoint(key) is not None:
            raise WorktreeError('Checkpoint already exists; resume it instead')
        input_path = Path(repository).expanduser().absolute()
        if input_path.is_symlink() or not input_path.is_dir():
            raise WorktreeError('Repository must be an existing non-symlink directory')
        repo = input_path.resolve(strict=True)
        if Path(_git(repo, 'rev-parse', '--show-toplevel')).resolve() != repo:
            raise WorktreeError('Select the Git repository root, not a subdirectory')
        if _git(repo, 'status', '--porcelain=v1'):
            raise WorktreeError('Original checkout must be clean')
        sha = _git(repo, 'rev-parse', '--verify', 'HEAD^{commit}')
        if not re.fullmatch('[0-9a-f]{40,64}', sha):
            raise WorktreeError('Invalid base commit')
        workspace = self.root / f'{key}-{uuid.uuid4().hex[:12]}'
        # Git operations are not an adversarial-code sandbox: checkout filters
        # configured in an already trusted local repository could execute.
        try:
            _git(repo, 'worktree', 'add', '--detach', str(workspace), sha)
            state = {'repo': str(repo), 'workspace': str(workspace),
                     'base_sha': sha, 'proposal_id': None, 'attempts': 0}
            self.store.checkpoint(key, task, state, status='paused')
        except BaseException:
            if workspace.exists():
                try:
                    _git(repo, 'worktree', 'remove', '--force', str(workspace))
                except (WorktreeError, OSError):
                    pass
            raise
        return self.resume(key)

    def resume(self, key: str) -> dict:
        item = self.store.get_checkpoint(key)
        if item is None:
            raise WorktreeError('Unknown task checkpoint')
        state = item['state']
        if not {'repo', 'workspace', 'base_sha', 'proposal_id', 'attempts'} <= state.keys():
            raise WorktreeError('Not a worker checkpoint')
        path = Path(state['workspace'])
        repo = Path(state['repo'])
        if (path.is_symlink() or not path.is_dir()
                or path.parent != self.root or not path.name.startswith(key + '-')
                or repo.is_symlink() or not repo.is_dir()):
            raise WorktreeError('Worktree has moved or is no longer valid')
        if Path(_git(path, 'rev-parse', '--show-toplevel')).resolve() != path:
            raise WorktreeError('Worktree path no longer matches Git checkout')
        listing = _git(repo, 'worktree', 'list', '--porcelain')
        # Git for Windows emits slash-separated paths, while pathlib prints
        # backslashes. Compare resolved native paths, never their raw spelling.
        expected = os.path.normcase(str(path.resolve(strict=True)))
        registered = []
        for line in listing.splitlines():
            if line.startswith('worktree '):
                candidate = Path(line[len('worktree '):]).resolve(strict=False)
                registered.append(os.path.normcase(str(candidate)))
        if expected not in registered:
            raise WorktreeError('Workspace is not registered under the authorized repository')
        if _git(path, 'rev-parse', '--verify', 'HEAD') != state['base_sha']:
            raise WorktreeError('Workspace HEAD unexpectedly changed')
        return item

    def propose(self, key: str, model, selected_files: list[str]) -> int:
        item = self.resume(key)
        if item['status'] not in {'paused', 'running'} or item['state']['proposal_id'] is not None:
            raise WorktreeError('Task has an outstanding proposal or is finished')
        if _git(Path(item['state']['workspace']), 'status', '--porcelain=v1'):
            raise WorktreeError('Worktree has unexpected changes; review or discard before new proposal')
        pid = propose(self.store, model, item['state']['workspace'], item['task'], selected_files)
        state = dict(item['state'])
        state['proposal_id'] = pid
        self.store.checkpoint(key, item['task'], state, status='paused',
                              expected_revision=item['revision'])
        return pid

    def apply(self, key: str) -> int:
        item = self.resume(key)
        pid = item['state']['proposal_id']
        if pid is None:
            raise WorktreeError('No reviewed proposal to apply')
        return change_status(self.store, pid)

    def retry(self, key: str, *, max_retries: int = 3) -> int:
        """Manually restart proposal selection, with a bounded retry budget.

        Applied proposals are first reverted using fingerprint-checked undo.
        Unapplied proposals are deleted, preventing later stale application.
        """
        item = self.resume(key)
        state = dict(item['state'])
        if item['status'] not in {'paused', 'running'} or state['proposal_id'] is None:
            raise WorktreeError('A proposal is required before retrying')
        if not 1 <= max_retries <= 3 or state['attempts'] >= max_retries:
            raise WorktreeError('Retry budget exhausted')
        pid = state['proposal_id']
        try:
            proposal = self.store.get_proposal(pid)
        except ValueError:
            proposal = None  # Unapplied proposal may have been purged before a crash.
        if proposal is not None and proposal['status'] == 'applied':
            change_status(self.store, pid, undo=True)
        elif proposal is not None and proposal['status'] == 'proposed':
            self.store.forget_runtime('proposals', pid)
        elif proposal is not None and proposal['status'] != 'undone':
            raise WorktreeError('Unexpected proposal status')
        # Allow crash recovery when the previous undo succeeded but the
        # checkpoint write was interrupted.
        # Avoid generating a new proposal on top of edits not owned by AthenZ.
        if _git(Path(state['workspace']), 'status', '--porcelain=v1'):
            raise WorktreeError('Unexpected changes remain after undo; review workspace manually')
        state['proposal_id'] = None
        # Prior review artifacts remain on disk for audit, but cannot be
        # represented as the active proposal after a retry.
        state.pop('review_bundle', None)
        state['attempts'] += 1
        self.store.checkpoint(key, item['task'], state, status='paused',
                              expected_revision=item['revision'])
        return state['attempts']

    def syntax_check(self, key: str) -> dict:
        """Parse patched Python files without importing or executing their code."""
        item = self.resume(key)
        pid = item['state']['proposal_id']
        if pid is None or self.store.get_proposal(pid)['status'] != 'applied':
            raise WorktreeError('Apply the proposal first')
        workspace = Path(item['state']['workspace'])
        changes = json.loads(self.store.get_proposal(pid)['changes_json'])
        if not all(change['path'].endswith('.py') for change in changes):
            raise ValueError('Syntax check supports Python files only')
        output = []
        for change in changes:
            path = allowed_file(workspace, change['path'])
            if digest(read_exact(path)) != change['after_sha256']:
                raise WorktreeError('File has changed since proposal; re-review it')
            try:
                ast.parse(read_exact(path), filename=change['path'])
                output.append(change['path'] + ': parsed')
            except SyntaxError as exc:
                output.append(f'{change["path"]}: line {exc.lineno}: invalid syntax')
        failed = any('invalid syntax' in line for line in output)
        fingerprint = digest(''.join(x['path'] + x['after_sha256'] for x in changes))
        result = '\n'.join(output)
        test_id = self.store.record_test(pid, 'athenz:ast.parse (no execution)',
                                         1 if failed else 0, result, fingerprint,
                                         'Python syntax was parsed without executing source')
        return {'returncode': 1 if failed else 0, 'test_run_id': test_id, 'output': result}

    def diff(self, key: str) -> str:
        item = self.resume(key)
        path = Path(item['state']['workspace'])
        return _git(path, 'diff', '--no-ext-diff', '--no-textconv', '--')

    def container_tests(self, key: str, *, image: str, kind: str = 'unittest',
                        timeout: int = 120) -> dict:
        """Run a fixed command in an opt-in container; never run arbitrary host tests.

        Image must be an explicitly chosen digest-pinned Python image. Requires
        Docker installed and appropriately secured by the owner.
        """
        item = self.resume(key)
        pid = item['state']['proposal_id']
        if pid is None or self.store.get_proposal(pid)['status'] != 'applied':
            raise WorktreeError('Apply the proposal first')
        if kind != 'unittest' or not IMAGE.fullmatch(image):
            raise ValueError('Only unittest and a digest-pinned image are supported')
        if type(timeout) is not int or not 10 <= timeout <= 180:
            raise ValueError('Container timeout must be an integer from 10..180 seconds')
        if not shutil.which('docker'):
            raise WorktreeError('Container runner unavailable; refusing host fallback')
        workspace = Path(item['state']['workspace'])
        # Docker --mount splits on commas despite argv not going through a
        # shell. A workspace selected in an unusual path must not be allowed
        # to add mount options or another bind source.
        from .verification import validate_mount_source
        validate_mount_source(workspace)
        changes = json.loads(self.store.get_proposal(pid)['changes_json'])
        for change in changes:
            if digest(read_exact(allowed_file(workspace, change['path']))) != change['after_sha256']:
                raise WorktreeError('Changed file no longer matches reviewed proposal')
        # Never bind the live worktree (which contains Git metadata and can
        # contain unrelated, untracked private files) into a test container.
        # Use the same bounded, secret-filtered tracked-file snapshot runner as
        # full-task verification. It checks the copied tree both before and
        # after execution, and handles forced Docker cleanup on timeout.
        from .verification import isolated_unittest
        observed = isolated_unittest(workspace, image=image,
                                     home=self.store.home, timeout=timeout)
        # Even with a stable copied tree, an owner could pause, revert or
        # supersede this proposal while the Docker client is running.
        # Never record a passed test on a superseded checkpoint/proposal.
        latest = self.resume(key)
        if (latest['revision'] != item['revision']
                or latest['state']['proposal_id'] != pid
                or self.store.get_proposal(pid)['status'] != 'applied'):
            raise WorktreeError('Task or proposal changed during container validation')
        returncode = observed['returncode']
        output = observed['output']
        fingerprint = digest(''.join(x['path'] + x['after_sha256'] for x in changes))
        test_id = self.store.record_test(pid, 'docker:isolated unittest', returncode,
                                         output, fingerprint,
                                         'Container unit tests completed; inspect evidence')
        return {'returncode': returncode, 'test_run_id': test_id, 'output': output,
                'source_snapshot_sha256': observed['snapshot_sha256'],
                'source_snapshot_rechecked': observed['source_snapshot_rechecked'],
                'runner': observed['runner']}

    def cleanup(self, key: str, *, discard_changes: bool = False,
                disposition: str = 'released') -> None:
        if disposition not in {'released', 'cancelled'}:
            raise ValueError('Invalid cleanup disposition')
        item = self.resume(key)
        state = dict(item['state'])
        workspace = Path(state['workspace'])
        # No default data-loss path: dirty trees require an explicit discard flag.
        if _git(workspace, 'status', '--porcelain=v1') and not discard_changes:
            raise WorktreeError('Workspace contains edits; require explicit discard_changes')
        _git(Path(state['repo']), 'worktree', 'remove',
             *(['--force'] if discard_changes else []), str(workspace))
        # Discarding an isolated patch must revoke its procedural lessons.
        pid = state['proposal_id']
        if pid is not None:
            proposal = self.store.get_proposal(pid)
            if proposal['status'] == 'applied':
                self.store.update_proposal(pid, 'applied', 'undone')
            elif proposal['status'] == 'proposed':
                self.store.forget_runtime('proposals', pid)
        # Checkpoint retained for audit, but no longer resumable.
        state['disposition'] = disposition
        self.store.checkpoint(key, item['task'], state, status='complete',
                              expected_revision=item['revision'])

    def export_review(self, key: str) -> dict:
        """Create an immutable, PRIVATE handoff patch for an applied, reviewed change.

        This writes only to ATHENZ_HOME/reviews. It does not commit, push,
        or imply that static parsing is sufficient behavioral verification.
        Reject unrelated or untracked edits rather than accidentally exporting
        arbitrary workspace content.
        """
        item = self.resume(key)
        pid = item['state']['proposal_id']
        if item['status'] != 'paused' or pid is None:
            raise WorktreeError('Task has no reviewable proposed patch')
        proposal = self.store.get_proposal(pid)
        workspace = Path(item['state']['workspace'])
        if proposal['status'] != 'applied' or Path(proposal['repo']) != workspace:
            raise WorktreeError('Proposal must be applied in its assigned worktree')
        changes = json.loads(proposal['changes_json'])
        expected = {c['path'] for c in changes}
        if not expected or len(expected) != len(changes):
            raise WorktreeError('Invalid reviewed change set')
        for c in changes:
            if digest(read_exact(allowed_file(workspace, c['path']))) != c['after_sha256']:
                raise WorktreeError('Source no longer matches reviewed changes')
        # NUL-delimited Git porcelain avoids assuming filename quoting rules.
        status = _git(workspace, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
        entries = [part for part in status.split('\0') if part]
        if len(entries) != len(expected) or any(
                len(e) < 4 or e[:3] != ' M ' or e[3:] not in expected
                for e in entries) or {e[3:] for e in entries} != expected:
            raise WorktreeError('Unexpected files or stages in workspace; review manually')
        # Only the reviewed paths can enter the patch. No external diff driver.
        patch = _git(workspace, 'diff', '--no-ext-diff', '--no-textconv',
                     '--binary', '--', *sorted(expected)) + '\n'
        if not patch.strip() or len(patch.encode('utf-8')) > 512_000:
            raise WorktreeError('Patch is empty or too large for a review bundle')
        patch_sha = hashlib.sha256(patch.encode('utf-8')).hexdigest()
        files_sha = digest(''.join(c['path'] + c['after_sha256'] for c in changes))
        latest = self.store.db.execute("""SELECT id,command,returncode,files_sha256
            FROM test_runs WHERE proposal_id=? ORDER BY id DESC LIMIT 1""", (pid,)).fetchone()
        verification = 'not-verified'
        test_id = None
        if latest and latest['files_sha256'] == files_sha and latest['returncode'] == 0:
            test_id = int(latest['id'])
            if latest['command'] == 'athenz:ast.parse (no execution)':
                verification = 'syntax-only'
            elif latest['command'] == 'docker:isolated unittest':
                verification = 'container-tests-observed'
        reviews = self.store.home.resolve() / 'reviews'
        if reviews.is_symlink():
            raise WorktreeError('Private review folder cannot be a symlink')
        reviews.mkdir(mode=0o700, parents=True, exist_ok=True)
        if reviews.is_symlink() or reviews.resolve() != reviews:
            raise WorktreeError('Unsafe private review folder')
        name = f'{key}-{pid}-{patch_sha[:16]}.patch'
        dest = reviews / name
        # O_EXCL prevents overwriting earlier evidence; O_NOFOLLOW adds
        # filesystem protection where it is available.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        try:
            fd = os.open(dest, flags, 0o600)
        except FileExistsError as exc:
            raise WorktreeError('Review bundle already exists; no overwrite allowed') from exc
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(patch.encode('utf-8'))
                handle.flush()
                os.fsync(handle.fileno())
            if stat.S_ISLNK(dest.lstat().st_mode):
                raise WorktreeError('Unexpected review bundle symlink')
            review = {'path': str(dest), 'sha256': patch_sha,
                      'files': sorted(expected), 'base_sha': item['state']['base_sha'],
                      'verification': verification, 'test_run_id': test_id,
                      'proposal_id': pid}
            state = dict(item['state'])
            state['review_bundle'] = review
            self.store.checkpoint(key, item['task'], state, status='paused',
                                  expected_revision=item['revision'])
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        return review
