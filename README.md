# AthenZ

Private, local-first digital twin and coding assistant. **Twin Mode** simulates
style and choices based on approved examples; **Agent Mode** provides independent
assistance without claiming to be the owner. Neither mode modifies model weights
without a separate future training and evaluation pipeline.

**Status: experimental v0.5 pre-release.** Human review is required for identity
claims and file changes. Task checkpoints, scoped patch proposals, reviewed
feedback, episodic memory and the review-gated foreground controller are
implemented. There is no unattended daemon, automatic cloud publishing, automatic
model promotion, or verified GPU fine-tuning on the target Windows/WSL2 system.

## Setup

```sh
python -m pip install -e .
athenz init
# Optional: install Ollama separately and pull a local model
ollama pull qwen3.5:2b
python -m athenz.chat --mode twin
python -m athenz.chat --mode agent
python -m unittest discover -s tests -v
```

The `athenz`, `athenz-worker`, `athenz-controller`, `athenz-sequence`, and
`athenz-training` command-line entries are
installed from `pyproject.toml`. Each mode uses locally stored, approval-gated
private identity and memory in `~/.athenz` or `ATHENZ_HOME`, never the Git repo.
The Ollama client accepts **only** explicit HTTP loopback endpoints.

## Supervised coding and learning

```sh
athenz-controller start mathfix /path/to/clean/trusted/repo 'Repair arithmetic'
athenz-controller plan mathfix calc.py util.py
athenz-controller prepare mathfix
athenz-controller review mathfix
athenz-controller apply mathfix --sha256 <displayed-sha256> --confirm
athenz-controller syntax mathfix
athenz-controller export mathfix --confirm
athenz-controller cancel mathfix --discard-changes
```

The planner cannot choose extra files, execute arbitrary code or bypass review.
A syntax failure can be retried automatically **only by undoing the isolated
changes and preparing a new proposal**. Each attempt requires fresh approval.
Passing syntax checks do **not** prove behavior. Actual project tests require
the `athenz-worker test` opt-in Docker runner with a trusted, digest-pinned image.
There is no host-side project test command or Git commit/push action.

Your reviewed feedback and independently checked results may inform future
prompt context. Model-weight updates are a separate future milestone.

See [ROADMAP.md](ROADMAP.md), [AGENTS.md](AGENTS.md),
[docs/LEARNING.md](docs/LEARNING.md), [docs/WORKER.md](docs/WORKER.md), and
[docs/CONTROLLER.md](docs/CONTROLLER.md). Encryption at rest, robust local
backup erasure, attested testing, and target-PC validation remain unfinished.

## v0.4 experimental sequential worktree tasks

`athenz-sequence` supports up to five owner-scoped, independently approved
Python patch stages in one disposable worktree. A fresh digest approval is
required per stage; previous approved edits remain intact while the active
stage is syntax-checked and retried. Once all stages pass **syntax-only**
checks, an immutable combined patch can be exported locally. No host project
execution, autonomous commit/push, or model-weight training occurs. See
[docs/SEQUENCE.md](docs/SEQUENCE.md) for examples, recovery and limitations.

### Complete-task test observation (experimental)

After all sequential stages are approved and advanced, use
`athenz-sequence test <key> --image python@sha256:<trusted-digest> --confirm`
to run fixed unittest discovery in a restricted Docker container against a
throwaway snapshot of the **combined final result**. The review export records
whether container tests were observed passing or failing and pins their
snapshot fingerprint. If Docker is unavailable, the operation fails closed.
This is not independent attestation and is still unverified on Windows/WSL2.

### Real Docker verifier hardening (v0.4)

Full-sequence test snapshots are fingerprinted before **and after** the
container run; unexpected changes cannot be reported as passing tests. Bind
source paths with Docker mount option separators are rejected. An opt-in
actual-Docker integration workflow tests real passing/failing fixtures on
GitHub-hosted Ubuntu; it does not establish Windows/WSL2 compatibility or
remote execution attestation. See [docs/SEQUENCE.md](docs/SEQUENCE.md).


## v0.5 offline QLoRA training (experimental)

`athenz-training prepare-qlora DATASET_SHA --base-model /local/qwen2.5-safetensors
--confirm` prepares a local, hash-bound run. `athenz-training run-qlora RUN_ID
--confirm` performs **opt-in** CUDA 4-bit LoRA training with separately
installed PyTorch/Transformers/PEFT/bitsandbytes. `--resume` is explicit.
An Ollama GGUF-only model is not a valid training base. No automatic model
selection or deployment is provided. The training runtime has **not** been
executed on the owner's RTX 3060. See [docs/TRAINING.md](docs/TRAINING.md).

## Reviewed local Ollama routing (v0.5)

After creating an Ollama candidate **outside AthenZ** and verifying its
training lineage yourself, register and evaluate it, select its adapter for
review, then explicitly activate the already-installed tag:

```sh
athenz-training selection
athenz-training runtime-status
athenz-training runtime-activate --baseline EXISTING_EVALUATED_BASELINE \
  --revision 0 --confirm
# AthenZ chat now uses the pinned installed tag, unless --model overrides it.
python -m athenz.chat --mode agent
athenz-training runtime-status
athenz-training runtime-rollback --revision CURRENT_RUNTIME_REVISION --confirm
```

The activation command performs a small local inference smoke check, requires
matching approved dataset/evaluation evidence, and pins both candidate and
baseline Ollama `/api/tags` digests. AthenZ chat rechecks the digest and
reviewed private evidence before sending each prompt. If consent is revoked or
a tag is replaced, chat fails closed until manual rollback/review. Explicit
`--model` always means a deliberate owner override of the configured route.

**Runtime routing itself does not create, convert, import, train, deploy, or replace Ollama model
weights.** The registered adapter-to-candidate association is *owner-attested*,
not independently proven. `runtime-rollback` switches only AthenZ's private
tag preference back to the exact pinned baseline (if it is still installed),
not the Ollama daemon's installed files. No outbound model requests or remote
network calls are authorized. See [docs/TRAINING.md](docs/TRAINING.md).

## Reviewed merged-GGUF import to local Ollama (experimental v0.5)

AthenZ can now **prepare and explicitly invoke a local import** for an
externally merged, converted **complete GGUF model**. It never directly imports
a Qwen PEFT/QLoRA adapter as though it were a complete Ollama model; current
Ollama import documentation only guarantees the documented full-model routes.

```sh
athenz-training prepare-import RUN_ID /path/to/merged.gguf \
  --candidate athenz-experiment:trial --ack-merge --confirm
athenz-training verify-import RUN_ID
athenz-training import-local RUN_ID --confirm
athenz-training verify-import RUN_ID --check-ollama
```

The merged GGUF must be created separately from the **exact matching base
weights** and its completed private adapter. The owner explicitly acknowledges
this lineage; hashes verify unchanged artifacts but cannot prove how the GGUF
was produced. The importer requires a new dedicated tag, records its observed
local digest, and never activates it or pushes anything. Ollama create is not
an atomic compare-and-swap operation; a concurrent external tag creation still
requires a trusted local Ollama environment and separate review.

This new bridge remains untested against the user's actual Ollama/RTX 3060
installation. See [docs/TRAINING.md](docs/TRAINING.md).

## Reviewed offline adapter → GGUF conversion (experimental)

AthenZ now has an **explicit, local CPU merge** for a completed Qwen2-family
PEFT adapter and an owner-trusted, SHA-256-pinned llama.cpp Python converter.
The output is a complete FP16 GGUF with a private provenance record; an Ollama
import is a separate, explicitly approved step. No model is activated or
uploaded, and failed conversion attempts are preserved for explicit recovery.
See [docs/CONVERSION.md](docs/CONVERSION.md) for prerequisites, resource
warnings, and the commands. **Real CPU/RAM/GGUF compatibility has not yet
been validated on the target PC.**

## v0.6 desktop coding-task supervision (experimental)

Launch `athenz-desktop` to access the **Coding tasks** tab. You can now start
an explicitly scoped, detached Git worktree from the GUI, request a proposal
from local Ollama, inspect the **full** proposed diff and **manually approve its
exact SHA-256**, run syntax validation, advance through up to five stages,
recover interrupted checkpoints, optionally run container-only tests, and
export one combined private patch. Every action requires owner interaction;
model-generated text cannot authorize file edits, shell commands, Git push or
model deployment. The original repository remains unchanged by the supervised
sequence workflow. See [docs/DESKTOP.md](docs/DESKTOP.md).

The UI is not a desktop release yet: real Windows rendering, RTX 3060 Ollama
inference, and WSL2 Docker still require hardware validation. No unattended
scheduler or self-training daemon is active.

## Opt-in supervised proposal queue (v0.6)

The desktop Coding tasks panel and `athenz-scheduler` can queue **one local
Ollama code proposal per owner-armed stage**, with private restart-safe leases,
manual pause/resume and manual crash reconciliation. It starts disabled; even
when enabled, it cannot apply patches, execute tests, train models, commit or
push to Git. Each proposal must still pass independent owner SHA-256 review.
See [docs/SCHEDULER.md](docs/SCHEDULER.md). Physical Windows and RTX 3060
integration testing is still outstanding.

## Portable Windows desktop and private setup checks (v0.6)

The optional [Windows portable CI workflow](.github/workflows/windows-portable.yml)
builds an **unsigned onedir ZIP** and verifies `AthenZ.exe --self-test` against
a temporary profile. This is an experimental download artifact, **not a
signed installer or verified release**. AthenZ does not auto-start or install
Ollama, Docker, or additional model weights. The Desktop **Setup** tab checks
local readiness and sends **no** requests to Ollama without pressing **Probe
Ollama**. Python CLI: `athenz-doctor [--probe-ollama]`.

See [Windows portable notes](docs/WINDOWS_PORTABLE.md). Native Windows display,
HiDPI, CUDA GPU and WSL2 Docker tests remain outstanding.

## Offline recovery to a separate profile

`athenz-backup restore-new <id> --destination /path/to/new-profile --confirm`
recovers a checksum-verified SQLite snapshot into a **brand-new directory**;
never into the current live profile. Operational permissions are disarmed:
scheduled proposals pause, in-flight leases are cleared and active Ollama
routing resets to unselected. Only SQLite data is recovered; model files and
other private artifacts require separate owner-controlled recovery. See
[the recovery notes](docs/BACKUP.md). No automatic overwrite or activation.

## Selected private profile bundles (v0.6)

`athenz-profile create --confirm` builds a local, **unencrypted** ZIP of a
consistent SQLite snapshot plus selected private datasets, reviews, model-run
artifacts and conversions. `athenz-profile verify <id>` checks its contents;
`athenz-profile restore-new <id> --destination <new-absent-dir> --confirm`
recovers only into a **new** profile, with scheduler and model-routing authority
disarmed. The Setup tab supports explicit creation/verification, not automatic
restore. External Ollama installations and Git worktrees are excluded.
See [private profile bundle notes](docs/PROFILE_BUNDLES.md).


### Keyboard navigation and portable GUI smoke (v0.6)

Ctrl+1/2/3/4 switch to Chat, Review memory, Coding tasks and Setup; Ctrl+L focuses the chat input. These shortcuts do not authorize reviews or coding. The packaged Windows workflow additionally launches the native four-tab window using an ephemeral private profile via `AthenZ.exe --gui-self-test`, besides the original headless `--self-test`. The real user's profile and Ollama remain untouched by this check. See [desktop documentation](docs/DESKTOP.md) and [Windows portable notes](docs/WINDOWS_PORTABLE.md).
