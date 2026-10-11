"""Approved LOCAL Git branch handoff; never pushes or changes the source HEAD.

Builds a commit tree from the pre-approved files through a temporary Git index.
Git read-tree/update-index/commit-tree/update-ref only; no checkout, merge,
model-specified Git command, repository hooks, or remote operation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from .coding import allowed_file, digest
from .sequencer import SequenceController, SequenceError


def _git_bytes(repo: Path, args: list[str], *, content: bytes | None = None,
               index: Path | None = None, allow_missing: bool = False) -> str | None:
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    if index is not None:
        env['GIT_INDEX_FILE'] = str(index)
    argv = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'protocol.file.allow=never',
            '-C', str(repo), *args]
    try:
        proc = subprocess.run(argv, input=content, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=False, timeout=45, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SequenceError('Local Git operation unavailable') from exc
    if proc.returncode:
        if allow_missing and args[0] == 'rev-parse':
            return None
        raise SequenceError('Local Git operation refused: ' +
                            proc.stderr.decode('utf-8', errors='replace')[-350:])
    return proc.stdout.decode('utf-8', errors='strict').strip()


def publish_local_branch(ctl: SequenceController, key: str, patch_sha256: str) -> dict:
    """Create an immutable local branch only for a reviewed, passing test snapshot.

    Caller must require an explicit --confirm and exact patch digest. No push.
    Existing equivalent branch is accepted to recover a crash before DB save.
    """
    item, seq = ctl._load(key)
    if seq['phase'] != 'exported' or not re.fullmatch('[a-f0-9]{64}', patch_sha256):
        raise SequenceError('Export reviewed patch before attempting local publication')
    ctl._integrity(item, seq)
    review = seq.get('final_review')
    if (not isinstance(review, dict) or review.get('sha256') != patch_sha256
            or review.get('verification') != 'container-tests-observed'):
        raise SequenceError('Matching owner-approved patch with passing container tests required')
    artifact = Path(review['path'])
    if (artifact.is_symlink() or not artifact.is_file()
            or hashlib.sha256(artifact.read_bytes()).hexdigest() != patch_sha256):
        raise SequenceError('Review bundle was removed or modified')
    workspace = Path(item['state']['workspace'])
    base = item['state']['base_sha']
    branch = f'athenz/{key}-{patch_sha256[:12]}'
    ref = 'refs/heads/' + branch
    affected = review['files']
    if not affected or len(affected) != len(set(affected)):
        raise SequenceError('Review scope is empty or repeated')
    # Generate a tree without staging worktree files. Hash exactly the reviewed
    # byte contents, bypassing repository clean/smudge filters and hooks.
    with tempfile.TemporaryDirectory(prefix='athenz-index-', dir=ctl.store.home) as folder:
        index = Path(folder) / 'index'  # must not exist before read-tree
        _git_bytes(workspace, ['read-tree', base], index=index)
        for rel in affected:
            target = allowed_file(workspace, rel)
            raw = target.read_bytes()
            if hashlib.sha256(raw).hexdigest() != seq['expected'][rel]:
                raise SequenceError('File no longer matches reviewed bytes')
            row = _git_bytes(workspace, ['ls-files', '--stage', '--', rel])
            rows = (row or '').splitlines()
            if len(rows) != 1 or '\t' not in rows[0]:
                raise SequenceError('Missing tracked file mode')
            mode, _, stage = rows[0].split('\t', 1)[0].split(' ')
            if mode not in ('100644', '100755') or stage != '0':
                raise SequenceError('Unsupported Git mode or submodule')
            oid = _git_bytes(workspace, ['hash-object', '-w', '--stdin'], content=raw)
            if not re.fullmatch('[0-9a-f]{40,64}', oid or ''):
                raise SequenceError('Invalid Git blob identifier')
            _git_bytes(workspace, ['update-index', '--add', '--cacheinfo', f'{mode},{oid},{rel}'], index=index)
        tree = _git_bytes(workspace, ['write-tree'], index=index)
    if not re.fullmatch('[0-9a-f]{40,64}', tree or ''):
        raise SequenceError('Invalid staged tree')
    existing = _git_bytes(workspace, ['rev-parse', '--verify', ref + '^{commit}'], allow_missing=True)
    if existing is None:
        message = f'AthenZ: reviewed task {key} ({patch_sha256[:12]})'
        commit = _git_bytes(workspace, ['commit-tree', tree, '-p', base, '-m', message])
        try:
            _git_bytes(workspace, ['update-ref', ref, commit, '0' * len(commit)])
        except SequenceError:
            # Someone may have created the ref concurrently; verify below.
            pass
        existing = _git_bytes(workspace, ['rev-parse', '--verify', ref + '^{commit}'])
    raw_commit = _git_bytes(workspace, ['cat-file', '-p', existing])
    if f'tree {tree}\n' not in raw_commit.split('\n\n', 1)[0] + '\n' or \
            f'parent {base}\n' not in raw_commit.split('\n\n', 1)[0] + '\n':
        raise SequenceError('Local branch collision: tree or base commit mismatch')
    published = {'branch': branch, 'commit': existing, 'tree': tree,
                 'base_sha': base, 'patch_sha256': patch_sha256,
                 'verification': review['verification'], 'remote_pushed': False}
    if seq.get('published'):
        if seq['published'] != published:
            raise SequenceError('Previously recorded publication differs')
        return published
    item, seq = ctl._load(key)
    seq = dict(seq)
    seq['published'] = published
    ctl._save(key, item, seq)
    return published
