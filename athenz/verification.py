"""Owner-invoked complete-task verification in a restricted, pinned Docker image.

The result is LOCAL observation with tamper-evident hashes, not independent remote
attestation, and a container is not a perfect security boundary. Never run source
code from the worktree directly on the host. The Docker test receives a fresh
snapshot that contains only tracked, regular, non-sensitive files.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import uuid

from .coding import protected_repository_path
from .worker import IMAGE, WorktreeError, _git

MAX_SNAPSHOT_BYTES = 64 * 1024 * 1024
MAX_SINGLE_FILE = 16 * 1024 * 1024


def _verified_regular_bytes(path: Path, *, limit: int = MAX_SINGLE_FILE) -> bytes:
    """Read one local file without following the final symlink, and fence races.

    Source trees are still owner-trusted inputs; this detects ordinary file
    replacement/mutation while staging, not a hostile same-user process that
    can interfere with directory ancestors.
    """
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        with os.fdopen(os.open(path, flags), 'rb') as stream:
            opened = os.fstat(stream.fileno())
            named = path.lstat()
            if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1
                    or not stat.S_ISREG(named.st_mode) or named.st_nlink != 1
                    or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
                    or opened.st_size > limit):
                raise WorktreeError('Tracked hard-linked, irregular or oversized file cannot enter Docker snapshot')
            payload = stream.read(limit + 1)
            final = os.fstat(stream.fileno())
            if (len(payload) != opened.st_size or len(payload) > limit
                    or (final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns)
                       != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)):
                raise WorktreeError('Source file changed during Docker snapshot capture')
            return payload
    except OSError:
        raise WorktreeError('Unable to safely read Docker snapshot source') from None


def snapshot_files(repo: Path, dest: Path) -> dict:
    """Copy tracked tree into new location, then attest copied bytes.

    No symlinks, Git metadata, credentials, submodules, or repository extras.
    The same-user host can still modify a snapshot during a Docker run;
    this is intended for explicitly trusted local checkouts.
    """
    listing = _git(repo, 'ls-files', '-z', '--cached', '--full-name')
    names = [n for n in listing.split('\0') if n]
    if not names or len(names) > 2000 or len(names) != len(set(names)):
        raise WorktreeError('Empty, oversized or duplicate tracked-file set')
    total = 0
    summary = hashlib.sha256()
    for rel in sorted(names):
        pure = PurePosixPath(rel)
        if (pure.is_absolute() or '..' in pure.parts or '\\' in rel
                or len(rel) > 1024 or any(ord(ch) < 32 or ord(ch) == 127 for ch in rel)
                or protected_repository_path(pure.parts)):
            raise WorktreeError('Sensitive, control-character or unsafe tracked path')
        origin = repo
        target = dest
        for part in pure.parts:
            origin = origin / part
            target = target / part
            if origin.is_symlink():
                raise WorktreeError('Tracked symlink not permitted in test snapshot')
        if not origin.is_file():
            raise WorktreeError('Tracked path is not a regular file: ' + rel)
        payload = _verified_regular_bytes(origin)
        size = len(payload)
        if total + size > MAX_SNAPSHOT_BYTES:
            raise WorktreeError('Tracked source exceeds sandbox snapshot size limit')
        total += size
        target.parent.mkdir(parents=True, exist_ok=True)
        target.parent.chmod(0o755)  # readonly container user must traverse copy
        target.write_bytes(payload)
        target.chmod(0o444)
        digest = hashlib.sha256(payload).hexdigest()
        summary.update(rel.encode('utf-8') + b'\0' + digest.encode('ascii') + b'\n')
    return {'snapshot_sha256': summary.hexdigest(), 'tracked_files': len(names),
            'snapshot_bytes': total}



def fingerprint_snapshot(snapshot: Path) -> dict:
    """Remeasure a copied test tree; reject added files, links and changed bytes.

    This detects ordinary file modification during a run. It is *not* a
    cryptographic attestation against an adversary controlling the host.
    """
    total = 0
    summary = hashlib.sha256()
    count = 0
    for path in sorted(snapshot.rglob('*'), key=lambda p: p.relative_to(snapshot).as_posix()):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise WorktreeError('Snapshot contains a symlink or non-regular file')
        rel = path.relative_to(snapshot).as_posix()
        count += 1
        payload = _verified_regular_bytes(path)
        if (count > 2000 or len(payload) + total > MAX_SNAPSHOT_BYTES
                or len(rel) > 1024 or any(ord(ch) < 32 or ord(ch) == 127 for ch in rel)):
            raise WorktreeError('Snapshot exceeds file, path or total-size limit')
        total += len(payload)
        summary.update(rel.encode('utf-8') + b'\0'
                       + hashlib.sha256(payload).hexdigest().encode('ascii') + b'\n')
    return {'snapshot_sha256': summary.hexdigest(), 'tracked_files': count,
            'snapshot_bytes': total}


def validate_mount_source(path: Path) -> None:
    """Docker --mount uses comma-separated options even when argv is not shelled."""
    raw = str(path)
    if any(c in raw for c in (',', '\n', '\r', '\x00')):
        raise WorktreeError('Unsafe Docker bind-mount source path')

def isolated_unittest(repo: Path, *, image: str, home: Path, timeout: int = 120) -> dict:
    """Execute a fixed unittest command on a copied tree; no host fallback."""
    if not IMAGE.fullmatch(image):
        raise ValueError('Image must be an explicit trusted sha256 digest pin')
    if type(timeout) is not int or not 10 <= timeout <= 180:
        raise ValueError('Timeout must be 10..180 seconds')
    if not shutil.which('docker'):
        raise WorktreeError('Docker is unavailable; refusing unisolated tests')
    base = home.resolve() / 'snapshots'
    validate_mount_source(base)
    if base.is_symlink():
        raise WorktreeError('Snapshot directory must not be a symlink')
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    if base.resolve() != base:
        raise WorktreeError('Unsafe private snapshot directory')
    with tempfile.TemporaryDirectory(prefix='run-', dir=base) as folder:
        snapshot = Path(folder)
        validate_mount_source(snapshot)
        metadata = snapshot_files(repo, snapshot)
        if fingerprint_snapshot(snapshot) != metadata:
            raise WorktreeError('Snapshot changed during creation; refusing execution')
        snapshot.chmod(0o755)  # source snapshot remains under private home
        container = 'athenz-full-' + uuid.uuid4().hex[:20]
        argv = ['docker', 'run', '--name', container, '--rm', '--pull', 'never',
                '--network', 'none', '--ipc', 'none', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--read-only', '--pids-limit', '64',
                '--memory', '512m', '--cpus', '1', '--user', '65534:65534',
                '--mount', f'type=bind,src={snapshot},dst=/src,readonly',
                '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
                '--workdir', '/src', '--env', 'PYTHONDONTWRITEBYTECODE=1',
                image, 'python', '-m', 'unittest', 'discover', '-s', 'tests', '-v']
        try:
            result = subprocess.run(argv, capture_output=True, text=True,
                                    timeout=timeout, check=False, errors='replace')
            code = result.returncode
            output = result.stdout + '\n' + result.stderr
            cleanup = 'docker --rm (normal exit)'
        except subprocess.TimeoutExpired:
            code = 124
            try:
                removal = subprocess.run(['docker', 'rm', '-f', container], timeout=20,
                                         capture_output=True, text=True, check=False)
                cleanup = 'forced removal confirmed' if removal.returncode == 0 else 'cleanup UNCONFIRMED'
            except (OSError, subprocess.TimeoutExpired):
                cleanup = 'cleanup UNCONFIRMED'
            output = f'Test timed out after {timeout}s; {cleanup}; container {container}'
        # Re-hash the snapshot AND independently resnapshot the current
        # source checkout. A green test of old copied bytes cannot verify
        # a source tree the owner (or another process) changed mid-run.
        source_stable = False
        try:
            if fingerprint_snapshot(snapshot) != metadata:
                raise WorktreeError('Snapshot contents changed during execution')
            with tempfile.TemporaryDirectory(prefix='recheck-', dir=base) as folder:
                if snapshot_files(repo, Path(folder)) != metadata:
                    raise WorktreeError('Source checkout changed during container execution')
            source_stable = True
        except (WorktreeError, OSError):
            code = 125
            output = 'Snapshot/source integrity FAILED after container execution'
        return {**metadata, 'image': image, 'returncode': code,
                'source_snapshot_rechecked': source_stable,
                'output': output[-8000:], 'output_sha256': hashlib.sha256(output.encode('utf-8')).hexdigest(),
                'cleanup': cleanup, 'runner': 'docker-local-observation',
                'container': container if cleanup == 'cleanup UNCONFIRMED' else None}
