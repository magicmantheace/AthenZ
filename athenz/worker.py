"""Supervised, restart-safe Git worktree coding sessions.

A Git worktree isolates file edits from the owner checkout; it is *not* an OS
security sandbox. This module does not execute repository programs on the host.
All model-generated edits require explicit apply; tests requiring execution can
only run via an opt-in, locked-down container runner.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from .coding import allowed_file, change_status, digest, propose
from .experience import ExperienceStore

KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
IMAGE = re.compile(r"[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}\Z")


class WorktreeError(RuntimeError):
    """Rejected operation or unsafe workspace state."""


def _git(repo: Path, *args: str) -> str:
    # No shell; no model-controlled Git flags, and no prompts/remote operations.
    cmd = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'protocol.file.allow=never',
           '-C', str(repo), *args]
    process = subprocess.run(cmd, text=True, capture_output=True, check=False,
                             timeout=45, env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    if process.returncode:
        raise WorktreeError((process.stderr or process.stdout).strip()[-600:])
    return process.stdout.strip()


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
        if f'worktree {path}\n' not in listing + '\n':
            raise WorktreeError('Workspace is not registered under the authorized repository')
        if _git(path, 'rev-parse', '--verify', 'HEAD') != state['base_sha']:
            raise WorktreeError('Workspace HEAD unexpectedly changed')
        return item

    def propose(self, key: str, model, selected_files: list[str]) -> int:
        item = self.resume(key)
        if item['status'] not in {'paused', 'running'} or item['state']['proposal_id'] is not None:
            raise WorktreeError('Task has an outstanding proposal or is finished')
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
            if digest(path.read_text('utf-8')) != change['after_sha256']:
                raise WorktreeError('File has changed since proposal; re-review it')
            try:
                ast.parse(path.read_text('utf-8'), filename=change['path'])
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
        if not shutil.which('docker'):
            raise WorktreeError('Container runner unavailable; refusing host fallback')
        workspace = Path(item['state']['workspace'])
        changes = json.loads(self.store.get_proposal(pid)['changes_json'])
        for change in changes:
            if digest(allowed_file(workspace, change['path']).read_text('utf-8')) != change['after_sha256']:
                raise WorktreeError('Changed file no longer matches reviewed proposal')
        argv = ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--read-only', '--pids-limit', '64',
                '--memory', '512m', '--cpus', '1', '--user', '65534:65534',
                '--mount', f'type=bind,src={workspace},dst=/src,readonly',
                '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
                '--workdir', '/src', '--env', 'PYTHONDONTWRITEBYTECODE=1',
                image, 'python', '-m', 'unittest', 'discover', '-s', 'tests', '-v']
        try:
            result = subprocess.run(argv, capture_output=True, text=True, check=False,
                                    timeout=max(10, min(timeout, 180)))
            returncode = result.returncode
            output = (result.stdout + '\n' + result.stderr)[-8000:]
        except subprocess.TimeoutExpired:
            returncode, output = 124, 'Container test timed out; execution stopped'
        fingerprint = digest(''.join(x['path'] + x['after_sha256'] for x in changes))
        test_id = self.store.record_test(pid, 'docker:isolated unittest', returncode,
                                         output, fingerprint,
                                         'Container unit tests completed; inspect evidence')
        return {'returncode': returncode, 'test_run_id': test_id, 'output': output}

    def cleanup(self, key: str, *, discard_changes: bool = False) -> None:
        item = self.resume(key)
        state = item['state']
        workspace = Path(state['workspace'])
        # No default data-loss path: dirty trees require an explicit discard flag.
        if _git(workspace, 'status', '--porcelain=v1') and not discard_changes:
            raise WorktreeError('Workspace contains edits; require explicit discard_changes')
        _git(Path(state['repo']), 'worktree', 'remove',
             *(['--force'] if discard_changes else []), str(workspace))
        # Discarding an isolated patch must revoke its procedural lessons.
        pid = state['proposal_id']
        if pid is not None and self.store.get_proposal(pid)['status'] == 'applied':
            self.store.update_proposal(pid, 'applied', 'undone')
        # Checkpoint retained for audit, but no longer resumable.
        self.store.checkpoint(key, item['task'], state, status='complete',
                              expected_revision=item['revision'])
