"""Privacy-preserving local installation checks; never auto-installs or executes code.

Everything is opt-in except inexpensive local Python/Tk/Git capability checks.
No personal data, environment variable values, paths, or model responses are logged.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

from .desktop import bootstrap_private_home
from .experience import ExperienceStore


def _check(name: str, ok: bool, note: str) -> dict:
    return {'name': name, 'ok': bool(ok), 'note': note}


def desktop_self_test() -> None:
    """Pure local, throwaway profile smoke for frozen/portable Windows builds.

    Must not create any file in the source checkout or connect to Ollama. This
    intentionally does not create a window or exercise GPU inference.
    """
    import tkinter
    if not tkinter.Tcl().eval('info patchlevel'):
        raise RuntimeError('Tcl runtime failed to initialize')
    from .desktop_tasks import DesktopTasks
    from .scheduler import ProposalScheduler
    with tempfile.TemporaryDirectory(prefix='athenz-smoke-') as scratch:
        home = Path(scratch) / 'home'
        bootstrap_private_home(home)
        if DesktopTasks(home).list_tasks() != [] or ProposalScheduler(home).list() != []:
            raise RuntimeError('Fresh profile unexpectedly has active coding tasks')
        store = ExperienceStore(home)
        try:
            if store.db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Private SQLite smoke verification failed')
        finally:
            store.close()


def installation_report(*, probe_ollama: bool = False, probe_gpu: bool = False,
                        probe_cuda: bool = False, confirmed: bool = False) -> dict:
    """Limited readiness hints, no stored secrets and no remote requests."""
    checks = [_check('python', sys.version_info >= (3, 11), 'Python 3.11+ is required')]
    try:
        import tkinter
        runtime = tkinter.Tcl()  # no native window/display required
        ok = bool(runtime.eval('info patchlevel'))
        checks.append(_check('tk', ok, 'Tcl/Tk runtime importable'))
    except Exception:
        checks.append(_check('tk', False, 'Tcl/Tk runtime unavailable'))
    checks.append(_check('git', shutil.which('git') is not None,
                         'Git required only for coding tasks'))
    checks.append(_check('docker', shutil.which('docker') is not None,
                         'Docker optional; actual sandbox operation unverified'))
    if probe_gpu:
        from .hardware import gpu_report
        result = gpu_report(confirmed=confirmed)
        note = ('Observed ' + str(result['gpu_count']) + ' local NVIDIA GPU(s), '
                + ', '.join(str(mib) + ' MiB' for mib in result['memory_mib'])
                + '; CUDA/training NOT validated') if result['gpu_detected'] else (
                'Local NVIDIA memory probe unavailable; CUDA/training NOT validated')
        checks.append(_check('nvidia-vram', result['gpu_detected'], note))
    if probe_cuda:
        from .hardware import cuda_compute_report
        outcome = cuda_compute_report(confirmed=confirmed)
        checks.append(_check('cuda-small-compute',
            outcome['cuda_compute_observed'],
            'Synthetic PyTorch CUDA computation observed; QLoRA/model training NOT validated'
            if outcome['cuda_compute_observed'] else
            'Local CUDA compute probe unavailable/failed; QLoRA/model training NOT validated'))
    if probe_ollama:
        try:
            from .chat import OllamaClient, safe_local_open
            from urllib.request import Request
            client = OllamaClient()
            # GET /api/version cannot transmit conversation context. Redirects
            # and proxy routing are rejected by the existing safe loopback open.
            with safe_local_open(Request(client.endpoint + '/api/version'), timeout=3) as reply:
                data = json.load(reply)
            checks.append(_check('ollama', isinstance(data, dict) and
                                 isinstance(data.get('version'), str),
                                 'Local Ollama version endpoint responded'))
        except Exception:
            # Deliberately do not include exception text: urllib errors may
            # embed sensitive paths, credentials or a redirected target URL.
            checks.append(_check('ollama', False, 'Local Ollama was not reachable'))
    return {'schema': 1, 'checks': checks, 'private_data_collected': False,
            'hardware_validated': False, 'startup_authorized': False}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description='Privacy-preserving AthenZ local installation checks')
    p.add_argument('--probe-ollama', action='store_true', help='Explicitly query only local /api/version')
    p.add_argument('--probe-gpu', action='store_true', help='Ask local nvidia-smi for memory totals only')
    p.add_argument('--probe-cuda', action='store_true',
                   help='Authorize a tiny local PyTorch CUDA computation (optional installed Torch)')
    p.add_argument('--confirm', action='store_true', help='Required for optional local GPU probe')
    args = p.parse_args(argv)
    print(json.dumps(installation_report(probe_ollama=args.probe_ollama,
                                         probe_gpu=args.probe_gpu,
                                         probe_cuda=args.probe_cuda,
                                         confirmed=args.confirm), indent=2))


if __name__ == '__main__':
    main()
