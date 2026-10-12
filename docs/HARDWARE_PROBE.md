# Optional local NVIDIA VRAM probe (v0.6 preflight)

Only after explicit owner confirmation, the `athenz-doctor` CLI may ask a local
`nvidia-smi` installation for **total VRAM in MiB**. It does not request device
names, UUIDs, serial numbers, private paths, installed models, or personal data.
The raw process stdout/stderr is never included in the result or logs. No GPU
probe is performed at application startup or by the default doctor command.

```powershell
athenz-doctor --probe-gpu --confirm
```

Output includes whether `nvidia-smi` was available, sanitized adapter count and
VRAM totals, and a clear **CUDA/training not validated** message. An absent or
unresponsive NVIDIA probe is a nonfatal readiness hint; it is not proof CUDA is
unavailable under Windows or WSL2.

This is a *local inventory observation*, not a proof that the PyTorch CUDA
runtime, quantization dependencies, Docker GPU passthrough, Ollama, or the
RTX 3060 QLoRA backend works. Actual model training, VRAM headroom and Windows
11/WSL2 behavior still require a supervised hardware test. Nothing is
installed, downloaded, trained, exported or sent over a network by this probe.
