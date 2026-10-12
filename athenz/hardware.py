"""Explicit local NVIDIA memory probe; never trains, downloads or exports IDs.

Only reports sanitized adapter counts and approximate VRAM. Detection is not
CUDA/PyTorch/WSL2 capability certification or proof QLoRA fits the GPU.
"""
from __future__ import annotations

import re
import shutil
import subprocess


class HardwareProbeError(ValueError):
    """Invalid permission or unavailable safe local GPU inventory."""


def gpu_report(*, confirmed: bool = False, timeout: int = 8) -> dict:
    """Query nvidia-smi (read-only) only after a human authorizes the probe."""
    if not confirmed:
        raise HardwareProbeError('Explicit --confirm required before probing hardware')
    if type(timeout) is not int or not 1 <= timeout <= 15:
        raise HardwareProbeError('Hardware probe timeout must be 1..15 seconds')
    base = {'schema': 1, 'method': 'local-nvidia-smi-vram-only',
            'gpu_detected': False, 'gpu_count': 0, 'memory_mib': [],
            'training_validated': False, 'cuda_validated': False,
            'external_requests': False, 'identifiers_collected': False}
    executable = shutil.which('nvidia-smi')
    if not executable:
        return {**base, 'status': 'nvidia-smi-not-found'}
    try:
        result = subprocess.run(
            [executable, '--query-gpu=memory.total', '--format=csv,noheader,nounits'],
            check=False, capture_output=True, text=True, timeout=timeout,
            shell=False, errors='replace')
    except (OSError, subprocess.TimeoutExpired):
        return {**base, 'status': 'local-query-unavailable'}
    if result.returncode:
        return {**base, 'status': 'local-query-unavailable'}
    output = result.stdout
    if len(output) > 512:
        return {**base, 'status': 'malformed-inventory'}
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not 1 <= len(lines) <= 8 or not all(re.fullmatch(r'[0-9]{3,8}', s) for s in lines):
        return {**base, 'status': 'malformed-inventory'}
    sizes = [int(line) for line in lines]
    if any(not 256 <= mib <= 262144 for mib in sizes):
        return {**base, 'status': 'malformed-inventory'}
    return {**base, 'status': 'local-vram-observed', 'gpu_detected': True,
            'gpu_count': len(sizes), 'memory_mib': sizes}
