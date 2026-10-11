# AthenZ

Private, local-first digital twin and coding assistant. **Twin Mode** simulates
style and choices based on approved examples; **Agent Mode** provides independent
assistance without claiming to be the owner. Neither mode modifies model weights
without a separate future training and evaluation pipeline.

**Status: experimental v0.4 pre-release.** Human review is required for identity
claims and file changes. Task checkpoints, scoped patch proposals, reviewed
feedback, episodic memory and the review-gated foreground controller are
implemented. There is no unsupervised daemon, Git publishing, automatic model
fine-tuning, or verified Windows/WSL2 Docker integration.

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

The `athenz`, `athenz-worker`, and `athenz-controller` command-line entries are
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
