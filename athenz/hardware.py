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

def cuda_compute_report(*, confirmed: bool = False) -> dict:
    """Opt-in minimal local CUDA operation; never reads model/profile files.

    Torch is imported only after an explicit owner confirmation. The smoke
    performs a small GPU tensor computation, transfers one scalar to the
    host, then discards it. Results contain no GPU name, ID, raw exception or
    private context. It is not a VRAM capacity, QLoRA, or performance test.
    """
    if not confirmed:
        raise HardwareProbeError('Explicit --confirm required for CUDA compute probe')
    base = {'schema': 1, 'method': 'local-pytorch-cuda-synthetic-compute',
            'status': 'cuda-unavailable', 'cuda_runtime_available': False,
            'cuda_compute_observed': False, 'training_validated': False,
            'model_inference_validated': False, 'private_data_collected': False,
            'downloaded_models': False, 'gpu_identity_collected': False}
    try:
        import torch  # optional; never required for routine startup
    except Exception:
        # Optional PyTorch may fail loading CUDA/native DLLs with diagnostics
        # containing local paths. Always return a sanitized fixed status.
        return {**base, 'status': 'pytorch-unavailable'}
    try:
        if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
            return base
    except Exception:
        return base
    try:
        # Only one small public constant tensor. Torch may initialize a CUDA
        # context; do not perform this automatically or at app startup.
        first = torch.ones((256,), dtype=torch.float32, device='cuda:0')
        answer = (first * 2).sum().item()
        torch.cuda.synchronize(device=0)
        if answer != 512:
            return {**base, 'status': 'cuda-compute-failed',
                    'cuda_runtime_available': True}
    except Exception:
        # Driver errors may include local paths, device identifiers or private
        # diagnostics; never surface them in the public-safe report.
        return {**base, 'status': 'cuda-compute-failed',
                'cuda_runtime_available': True}
    return {**base, 'status': 'cuda-small-compute-observed',
            'cuda_runtime_available': True, 'cuda_compute_observed': True}
