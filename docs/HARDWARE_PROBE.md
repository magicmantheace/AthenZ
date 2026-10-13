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

## Optional CUDA runtime compute smoke (separate authorization)

After installing a trusted local CUDA-enabled PyTorch distribution (AthenZ
does not install it), the owner can test whether a tiny 256-element constant
tensor calculation runs successfully on CUDA device 0:

```powershell
athenz-doctor --probe-cuda --confirm
```

This is **not** part of routine startup, the default doctor report or the
`--probe-gpu` nvidia-smi inventory. The optional Torch import happens only
after explicit confirmation. It may initialize a CUDA runtime, allocate a
CUDA context and temporarily use GPU resources. Raw driver errors, GPU IDs,
paths, model contents and exception messages are never included in the result.
The report distinguishes missing PyTorch, unavailable CUDA, failed compute
and completed small synthetic CUDA computation. It neither downloads nor
trains any model, and cannot certify GPU memory headroom, WSL2 passthrough,
quantized QLoRA training or inference speed. Hardware acceptance must still
be performed by the owner on their intended machine.

Driver discovery and optional PyTorch import failures are also sanitized.
If CUDA availability itself raises an exception, AthenZ reports unavailable
instead of incorrectly marking the runtime available. A later failure during
an actual tensor operation is reported separately from discovery failure.
