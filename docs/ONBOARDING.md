# First-run guidance (experimental v0.6)

The **Setup** tab opens with a read-only Getting started guide. Click **Getting started** at any time to see it again. It explains local Ollama installation, Agent/Twin differences, reviewed memory, the off-by-default proposal scheduler, and manual backup and readiness checks.

There is no background setup assistant, telemetry, sign-up, model download, license acceptance, cloud sync or automatic memory training. Viewing the guide does **not** grant permissions to start the scheduler, run a model, access hardware, write a training record, apply a patch or contact Ollama.

The text-only and JSON variants can be printed offline without starting the desktop or private database:

```sh
athenz-onboarding
athenz-onboarding --json
```

To take a readiness action, use the separate **Check prerequisites**, **Probe Ollama (loopback only)** or **Probe NVIDIA VRAM** Setup buttons. The latter requires a separate confirmation. Their results are observations, not proof that CUDA, WSL2 Docker, or fine-tuning works.

AthenZ profile archives remain **unencrypted**, and include private content. Do not put the archives in source control. The Windows portable ZIP is also unsigned: its SHA-256 file checks corruption, not publisher authenticity. Native Windows accessibility, HiDPI and RTX 3060 acceptance remain unverified on the owner's device.
