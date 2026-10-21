# AthenZ

**Current owner priority (October 20, 2026): a working, independently usable
personal Twin on Windows.** Developmental AI, Synveil, and unrelated Agent
expansion are deferred until real owner evaluation demonstrates a useful Twin.
See [the revised roadmap](ROADMAP.md). No real-owner similarity claim has been
established by the synthetic test suite.

Private, local-first digital twin and coding assistant. **Twin Mode** simulates
style and choices based on approved examples; **Agent Mode** provides independent
assistance without claiming to be the owner. Neither mode changes model weights
during chat; experimental fine-tuning is separate, opt-in and review-gated.

**Status: experimental v0.6 alpha, with partial v0.7 evaluation and v0.8 voice
foundations (not a stable release).** Human review is required for identity
claims and file changes. Task checkpoints, scoped patch proposals, reviewed
feedback, episodic memory and the review-gated foreground controller are
implemented. There is no unattended daemon, automatic cloud publishing, automatic
model promotion, or verified GPU fine-tuning on the target Windows/WSL2 system.

## Check real Twin evaluation readiness (no model calls)

AthenZ already has [paired same-model decision evaluation](docs/EVALUATION_SNAPSHOTS.md)
and a blinded [owner writing-style comparison](docs/ONBOARDING.md).
To find out whether the private approved evidence is ready for those tests,
without transmitting personal examples or calling Ollama:

```powershell
athenz-twin-readiness --home "$env:USERPROFILE\\.athenz"
```

Specify the **existing** private AthenZ profile outside Git. AthenZ reports
approved-reference counts, the default 30 independent held-out decision case
target, the existing strict lexical split/leak checks, writing-sample pilot
eligibility and recommended next owner actions. It does **not** report
individual facts, choice answers, held-out prompts, writing samples, private
paths or model replies. No inference, training or model promotion occurs.
The standard SQLite client may perform normal database bookkeeping when
opening the profile; no memory/review records are deliberately modified.

This is a prerequisite check, **not a Twin accuracy score**. The roadmap's
20 independently owner-rated writing prompts must still be collected and
scored using the separate blinded style-comparison workflow. Once the data
is ready, [the evaluation protocol](docs/TWIN_EVALUATION_WORKFLOW.md)
explains the separately consented local model runs and held-out review.

**Twin-first terminal chat:** running `python -m athenz.chat --model <installed-tag>`
now starts in **Twin Mode** too; explicitly pass `--mode agent` when you
intend independent Agent assistance. This changes the default interactive
mode only; it does not alter how existing sessions are stored or silently
promote conversation messages into approved owner facts.

**Twin-first desktop workflow (unvalidated on owner hardware):** the Chat
tab now defaults to Twin Mode, with Agent remaining selectable. Before
sending, type a question and select **Preview Twin evidence** to inspect
the approved, packed references and their provenance without inference or
saving the draft. Topical matches are prompts for review, not proof of an
owner-specific fact; excluded/oversized evidence does not count as available.
See [desktop details](docs/DESKTOP.md).

The current Twin-first relevance work includes
[approved personality, decision and writing-style retrieval](docs/TWIN_CONTEXT.md).
This is deterministic prompt preparation, not evidence of measured owner
similarity or independent model improvement.

Full-history approved context retrieval and its local **synthetic-only**
regression benchmark are described in
[docs/TWIN_CONTEXT.md](docs/TWIN_CONTEXT.md).
Run `python -m athenz.twin_retrieval_benchmark` to inspect aggregate
retrieval and revocation results without accessing the owner's profile or
calling a model. It does **not** measure real Twin personality similarity.

## Private blinded Twin writing-style pilot

The Twin evaluation preflight now blocks substantial lexical near-copies
of approved writing samples. Its aggregate report separates ratings by the
**exact model identity used at generation**, suppressing mixed-version
pooled preference rates. These checks improve experimental integrity but
are not semantic leakage detection or proof of personality fidelity.


`athenz-style-compare` runs an **opt-in, local-only, owner-blinded A/B comparison**
using the same installed model with and without approved Twin context. It keeps
held-out owner writing out of both model prompts and saves responses/owner
ratings in a separate private SQLite database, not model training or public
GitHub. For repeatable owner-reviewed test prompts, run
`athenz-style-compare task-add "Independent writing prompt" --confirm`,
review the private task, then use `athenz-style-compare start-next --confirm`.
See [Twin style comparison and task bank](docs/TWIN_STYLE_COMPARISON.md).
This is a subjective owner-preference pilot, **not validated personality
accuracy**.

## Paired local Twin decision prediction (experimental)

`athenz-decision-compare --split calibration --limit 12 --confirm`
compares held-out owner choices using the **same local Ollama model** with
approved Twin evidence versus a neutral no-personalization baseline. It
reports aggregate Twin/neutral accuracy, an exact matched-pairs
comparison, disagreements, chance expectation and descriptive uncertainty.
Use --allow-abstain on calibration cases to measure explicit uncertainty,
answer coverage and accuracy among answered cases. Alternatively, use
--score-confidence for ten-bin aggregate calibration error and a binary
chosen-answer Brier score. The two options are mutually exclusive. Neither
mode asserts calibrated confidence, and no private choices, individual
probabilities or model responses are returned. [Method and limitations](docs/TWIN_DECISION_COMPARISON.md).
Optional `athenz-decision-compare --family-template --confirm` creates an
owner-only decision-family review manifest; after assigning family IDs and
broad categories, first use `--family-check --confirm` to validate the
owner-private full-evidence fingerprint without loading a local model.
Then use `--family-audit` to reject semantically related train/held-out
decisions and suppress undersized category reports.
For category-balanced evaluation, `--family-audit --require-category-diversity`
enforces three adequately represented
independent reviewed categories before inference, and the aggregate report
shows a macro-averaged Twin-versus-neutral difference when enough cases exist.
This human review is not automatic semantic similarity detection.
Use `athenz-decision-compare --split calibration --limit 30 --stability-trials 2 --confirm`
to compare **semantic** choice agreement across seeded repeats without treating
repeats as new independent cases. All repeat predictions stay ephemeral and
the report contains aggregate stability only.
For a stricter untouched final decision study, run
`athenz-decision-compare --split test --freeze-test-plan --confirm`
with the intended model, family audit, seed and sample-limit settings.
`--check-test-plan` validates the owner-only frozen evidence and model
without generating answers, and `--use-test-plan` refuses altered source,
protocol, model or relevant evaluator code during the final comparison.
This improves reproducibility but cannot prove independent preregistration.
Use `athenz-decision-compare --split calibration --limit 30 --score-confidence
--calibration-grid --confirm` to inspect privacy-suppressed answer
coverage and accuracy at five predefined cutoff candidates. A selected
`--confidence-cutoff 0.5|0.6|0.7|0.8|0.9` may be included in a
`--score-confidence` final test and is pinned by the frozen plan.
This is a descriptive selection audit, not automatic threshold learning or
evidence of calibrated confidence.
A real on-device held-out improvement has not yet been demonstrated.

## Review possible duplicate or contradictory approved memories

Run `athenz memory-audit` locally or open **Review memory → Find possible
duplicates…** in the desktop. AthenZ scans only **approved** memories and
shows candidate record IDs for duplicate normalized wording or narrowly
recognized opposite first-person preferences (for example `I prefer X`
versus `I do not prefer X`). The desktop permits read-only inspection of
both full records and their provenance, followed by the existing separately
confirmed correction/revocation workflow. No model or external service is
called, no private text is printed by the CLI, and no memory status changes
automatically.

The audit is limited to 5,000 approved records and displays at most 80 pairs
(default), with total counts for omitted candidates. A lack of hits is
**not proof of consistency**; synonyms, differing facts, temporal changes
and most natural-language contradictions will not be detected. See
[consistency audit protocol](docs/MEMORY_CONSISTENCY.md).

## Same-session conversational continuity (local, unverified)

AthenZ now retains its recent ten chat turns and, when an older **user-written**
message in the **same session and same mode** matches the current topic, supplies
up to four bounded historical excerpts to the local model. These excerpts are
separately labeled **unreviewed conversation references**, not verified
autobiographical memories, standing preferences, instructions, or permissions.
Old assistant replies are not treated as owner evidence. Unrelated messages
and messages from other chat modes/sessions are never included by this
history-retrieval path. The relevant excerpts are recalculated and checked
during local inference, and stale answers are discarded if a referenced
historical message is edited or deleted.

No automatic summarization, profile approval, model training, internet search,
cross-session tracking or background process is enabled. Explicitly reviewed
long-term memories still use the separate owner-controlled approval flow.
See [same-session context limits](docs/SESSION_CONTINUITY.md).

## Browse, switch and delete individual desktop conversations

The desktop **Chat** tab now has **Browse sessions…**. It lists each existing
local `session / Agent-or-Twin mode` independently with message counts, without
showing message text in the list. Open an existing conversation to continue it,
or type a new session identifier in the Chat field for a new one.

**Review deletion…** shows the number of messages and recent excerpts. Its
private full-history review fingerprint includes **every** message in the
selected mode, even when only eight excerpts are shown. After a separate
confirmation, deletion removes only that specific mode's messages from the
live private database; the Agent conversation is preserved when deleting
the Twin conversation with the same session name (and vice versa). Memories
derived from deleted owner messages, their revision histories, feedback
and linked training pairs are removed alongside those messages. Concurrent
changes invalidate the deletion review; large conversations of more than
5,000 messages must be handled through a deliberate separate owner workflow.
Existing offline backups are **not** securely erased.

The older `athenz delete-session <name>` CLI command still deletes **both**
modes of that name. See [desktop session controls](docs/DESKTOP_SESSIONS.md).

## Run a real local Twin + Agent smoke test without personal data

AthenZ offers an explicit, disposable-profile smoke test through the **Setup**
tab's **Test Twin + Agent (synthetic)…** button or this terminal command:

```sh
athenz-chat-smoke --model qwen3.5:2b --confirm
```

The chosen Ollama model must already be installed and running on the same
computer. After confirmation, AthenZ creates an empty *temporary* private
profile with a fictional preference, verifies its ordinary prompt assembly,
generates exactly **one Twin and one Agent reply** via the desktop service,
checks that the replies were committed in separate sessions/modes, and deletes
the synthetic profile when finished. Only fixed, sanitized outcome flags are
printed; no real owner profile is loaded and no chat content is exported.
A failed request makes the CLI exit nonzero. This exercises actual local
inference and the everyday persistence path—not GPU use, model quality,
personality fidelity, autonomous learning, or installed-model integrity.
No inference is triggered by app startup or ordinary prerequisite checks.

For a deeper five-request check on an already installed local model, run
`athenz-chat-smoke --model qwen3.5:2b --twin-lifecycle --confirm`.
This optional synthetic workflow tests session reopening, staged preference
correction, separate approval, and revocation through the same desktop
service. It checks persistence and reviewed prompt references, **not** whether
the model's generated replies accurately represent the owner.

See [the local chat smoke protocol](docs/LOCAL_CHAT_SMOKE.md).

## Inspect, correct, revoke or forget memories in the desktop

Open the **Review memory** tab and choose **Manage approved**. Inspect the
**complete** approved record and its provenance before choosing an action:

- **Stage correction**: edit the summary and supply a reason. The old
  approval is revoked immediately and the corrected text remains **pending**
  until separately reviewed and approved.
- **Revoke**: set the current approved memory to `rejected`, excluding it
  from the Twin prompt without immediately deleting the private stored text.
- **Forget from DB**: delete the memory and any earlier identity revision
  history from the live SQLite database. The original chat message (if any)
  remains; offline backups and SQLite/WAL deletion limits still apply.

A stale full-record review hash, removed record, or concurrent owner edit
refuses the operation. All actions require a separate explicit confirmation.
They run locally and never call the model. See
[Memory correction and revocation](docs/MEMORY_MANAGEMENT.md).

## Owner-reviewed memories from actual chats (experimental)

AthenZ can now turn one **owner-written** chat message into a traceable
**pending** memory without an AI guessing your biography. In local terminal
chat, record your message ID with `athenz list messages`, then:

```sh
athenz memory-preview 123
athenz memory-from-message 123 preference "I prefer peer review before release" --review-sha256 <reviewed-sha256> --confirm
athenz list identity --status pending
athenz status <new-memory-id> approved
```

In the desktop Chat tab, **Remember my message** opens the full, read-only
owner message and lets you type your own summary and choose a memory type.
Submitting it **never approves** the memory: use the separate full-record
Review memory tab before Twin retrieval. AI replies cannot become owner
biographical memories through this workflow. Each source message can
produce at most one such memory proposal; new proposals and approvals are
not made automatically.

Deleting the source message with `athenz forget-runtime messages <id>` or
its entire session with `athenz delete-session <session>` also deletes the
linked memory and its revisions, including if previously approved.
Deleting a memory does not delete its original message. Other independent
memories are unaffected. This protects the owner's right to correct or
revoke the source of remembered personal information.

See [reviewed chat-to-memory flow](docs/CHAT_MEMORY.md).

## Owner-reported longitudinal decisions (experimental)

`athenz-decision-timeline` is a separate, entirely offline private journal for
recording repeated owner-confirmed decision choices with a date, comparable
context and family identifier. It reports **aggregate consecutive choice
agreement** only when at least five qualifying pairs span three distinct
families; sparse comparisons remain suppressed. Neither these self-reports
nor the summaries enter Twin prompts, model training or the independent
held-out model benchmark. This is a human variability reference, **not**
verified identity or Twin predictive accuracy.
See [longitudinal decision protocol](docs/TWIN_LONGITUDINAL_DECISIONS.md).

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
Both terminal chat and the desktop now check an in-flight answer against
the current **approved memory/reference evidence and same-session history**.
If a memory is revoked, relevant context changes, another turn arrives or
the selected model route changes during generation, the stale answer is
discarded instead of being saved as a fresh reply. Persistence uses a
short SQLite write lock for the final consistency check; inference itself
does not run inside that lock. This is an owner-data integrity safeguard,
not a claim that local AI replies are factually correct or that every
possible hostile filesystem race is prevented.

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
prompt context. Experimental QLoRA updates require separate owner consent,
training evaluation and explicit selection; no model is auto-promoted.

See [development integration status](docs/INTEGRATION_STATUS.md) for the
archival branch, exact tested source and remaining merge gates.

### Developmental AI integration (planned)

Developmental AI
is the planned **single adaptive learning subsystem** for AthenZ's
owner-facing executive, not another digital-twin persona or permission
authority. Its experimental persistent policies, world models, learned
memory controls and reviewed candidates currently run as separate
simulator research; no AthenZ/Synveil learning-service bridge is
implemented yet. The first dependency is a versioned, permissioned local
event/experience interface, with simulated agent memories always
separate from the consenting person's records. Synveil is an optional
future operating host, not a requirement for Windows/WSL2 development.

See [integration architecture and release acceptance gates](
docs/DEVELOPMENTAL_AI_INTEGRATION.md) and the
[updated AthenZ roadmap](ROADMAP.md) for the linked 2027–2029 milestones.
No human-mind emulation or autonomous real-world tool authority is claimed.

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

## Explicit private SQLite health checks (experimental)

Run `athenz-profile-health --confirm` to request a local read-only SQLite
quick check before backup or update work. The report contains only sanitized
integrity/schema metadata, never private row contents. The command does not
perform migrations, recovery, downloads, inference, training or deployment.
See [docs/PROFILE_HEALTH.md](docs/PROFILE_HEALTH.md). A successful quick check
is **not** proof that a backup or an installed model can be restored.

### Manual temporary SQLite restore rehearsal

Run `athenz-rehearse-backup BACKUP_ID --confirm` to rehearse a verified
SQLite-only backup in a disposable private profile, check cleared scheduling
leases and model routing, and remove the temporary copy. Nothing activates
or overwrites the live profile. Scratch contents are plaintext and not
securely erased; details: [docs/BACKUP.md](docs/BACKUP.md).

## Reviewed episode disagreements (v0.3/v0.6 experimental)

In **Review memory**, select a pending episode and choose **Review episode
conflicts…** for a full private, fingerprinted comparison to currently approved
records sharing topic tags. The owner can reject the candidate, retain both, or
supersede one approved predecessor, with explicit SHA-256 re-entry and
transactional freshness validation. The `athenz-conflicts` CLI offers the same
workflow. Matching tags do not establish semantic contradiction; no model can
resolve the conflict automatically. See [docs/CONFLICT_REVIEW.md](docs/CONFLICT_REVIEW.md).

## Owner-confirmed local inference readiness (experimental)

`athenz-inference-check --model qwen3.5:2b --confirm` issues one short, public, synthetic prompt to a previously installed Ollama model over loopback-only HTTP. It checks that text can actually be generated, without reading your profile or storing the response. The request is bounded, does not pull models, and can be given a 1–60-second timeout. No GPU, CUDA, WSL2, model quality, training, or deployment is certified. See [docs/INFERENCE_READINESS.md](docs/INFERENCE_READINESS.md).


## Opt-in local CUDA and inference diagnostics (experimental)

For a supervised hardware acceptance check on a machine with a trusted local
CUDA-enabled PyTorch already installed, use:

```powershell
athenz-doctor --probe-gpu --confirm
athenz-doctor --probe-cuda --confirm
athenz-inference-check --model qwen3.5:2b --confirm
athenz-release-readiness plan
```

These are **separate owner actions**. The VRAM query and small CUDA
tensor-compute smoke do not train, download or select a model, and the
inference check sends only a fixed synthetic prompt to a previously installed
local Ollama model. That response now separately reports whether it followed
the exact `READY` instruction; neither signal certifies model quality or
GPU acceleration. Results are sanitized, without private memories, model
replies or GPU identifiers. Release-acceptance observations require their own
`record --confirm` step and remain owner-reported, never independently
certified. Previous failed/blocked statuses are kept in a local observation
history. See [hardware probe](docs/HARDWARE_PROBE.md),
[inference readiness](docs/INFERENCE_READINESS.md) and
[release acceptance](docs/RELEASE_READINESS.md).

Hosted public GitHub Actions runs exercise synthetic tests and a packaged
Windows application, not the actual owner machine. CUDA/WSL2/QLoRA
compatibility still requires owner-supervised real-hardware testing.

## Read-only held-out evaluation preflight (experimental v0.7)

Before spending GPU/inference time comparing locally installed model tags,
run `athenz-training inspect-heldout --split calibration --limit 100 --min-cases 10`.
This local, read-only command reports the count of owner-approved held-out
decisions, whether the minimum is met, lexical train/calibration/test overlap,
and whether selected case options are well-formed. It does **not** invoke
Ollama, verify the training dataset, disclose private choices or promote a
model. See [evaluation evidence](docs/EVALUATION_SNAPSHOTS.md).

When an owner later saves a model comparison, AthenZ rechecks that the installed
Ollama baseline and candidate tags still have their previously evaluated
digests. Saved confidence intervals, invalid prediction counts and random
chance baseline metadata must agree with the underlying aggregate evidence.
This still cannot independently attest a model's origins or guarantee that
future weights and owner data are free from semantic contamination.

## Offline privacy preflights and held-out batch protection

`athenz-training inspect-heldout --split calibration --limit 100 --min-cases 10`
checks the selected approved batch with the *actual seeded Twin reference*
assembler, without contacting the model or returning private prompt text.
The evaluation now checks the entire selected batch before the first model
request. A protected scenario or rationale in any case's approved profile,
ambiguous options or stale approval snapshots refuses scoring.

`athenz-profile inspect` is a separate read-only preview of counts and size
of the explicitly selected **plaintext** bundle artifacts before running
`athenz-profile create --confirm`. It never creates a profile or reads owner
file contents. Ollama weights, worktrees, previous backups and separate
release-acceptance observations are excluded. The archive remains unencrypted;
keep it in owner-controlled private storage and do not put it in Git.

Supervised proposal-queue failure reports now contain fixed non-sensitive
categories, not raw driver/model exceptions that could reveal private
prompts, filesystem paths or local environment details. These improvements
do not authorize unattended code edits, automatic model training or promotion.

## Rehearse selected-profile recovery without activating it

For an existing, owner-approved **plaintext** private bundle produced by
`athenz-profile create --confirm`, AthenZ can now independently rehearse
restoration in an automatically deleted local scratch profile:

```sh
athenz-rehearse-backup <32-character-bundle-id> --bundle --confirm
# Optionally choose an existing scratch parent with --scratch /safe/private/dir
```

The rehearsal validates all selected artifact fingerprints after extraction,
checks the recovered SQLite schema, and verifies that old scheduled leases,
running checkpoints and active model routing are disarmed. The SQLite snapshot
is deliberately changed during recovery: the rehearsal compares it with its
**post-disarm** recovery fingerprint rather than assuming it remains identical
to the archived bytes. Scratch storage needs free space and temporarily holds
unencrypted private material; cleanup is not secure erasure. No downloaded or
installed Ollama models, Docker worktrees, or external adapters are activated.
See [private profile bundles](docs/PROFILE_BUNDLES.md).

## Supervised coding and CPU model-conversion safety (October 2026)

AthenZ's explicitly owner-invoked per-task Docker unittest command no longer
bind-mounts an active Git worktree. It runs against a disposable copy of only
reviewed Git-tracked, regular source files. The copy excludes Git metadata,
untracked files, obvious credential filenames, hard-linked files and common
private database/key formats; its fingerprint is rechecked before and after
execution. No Docker fallback runs test code directly on the host, and this
is still not a perfect sandbox for adversarial software.

A long-running, explicitly approved local PEFT/GGUF conversion can have its
checkpoint authorization revoked using:

```powershell
athenz-training pause-conversion <run-id> --confirm
athenz-training run-conversion <run-id> --resume --confirm
```

The pause **does not terminate a CPU merge already running**; it prevents
that old worker from adopting its output. Resume requires deliberate owner
review and allocates a new numbered attempt without overwriting prior output.
No model is promoted or deployed by these commands.

## Source-stable supervised Docker test evidence (October 2026)

The owner-invoked Docker unittest runner now pins more than the checked-out
commit. Its disposable, restricted snapshot reads regular files using bounded,
no-follow file handles where supported and verifies inode, hard-link count,
size and modification metadata both during copying and after testing. Tracked
filenames containing control characters are rejected without echoing them.
After Docker completes, AthenZ separately rechecks the **current** tracked
source checkout against the previously tested snapshot, and refuses a green
result if the source or copied bytes changed. A concurrent owner checkpoint
revision also prevents old test evidence from being attached to a superseded
coding task (both direct and multi-stage modes).

The multi-stage code review also preserves literal CRLF/LF source bytes in its
SHA-256 fingerprints, so Windows newline translation cannot silently turn a
reviewed patch into different bytes. This does not turn Docker or a same-user
filesystem into a trusted security boundary, and is not third-party attestation.

## Experimental offline voice input (v0.8 foundation)

For deliberate, local speech-to-text processing of an existing WAV file, the
installed `athenz-voice` CLI supports these separate actions:

```powershell
athenz-voice inspect C:\\PrivateAudio\\note.wav
athenz-voice transcribe C:\\PrivateAudio\\note.wav --model C:\\PrivateModels\\whisper-ct2 --confirm
# Optional: --language fr|es|de (English is the default)
# Optional: --device cuda (CPU is the default)
```

This is **not microphone capture, a voice assistant or continuous listening**.
Transcription requires an already installed, trusted local faster-whisper
CTranslate2 model and optional Python package; AthenZ never downloads it.
It returns the private transcript only to the owner-invoked CLI, without
creating memory, chat messages, training data or model-changing actions.
The file is size/duration bounded, and its content hash is checked before
and after inference so a changed recording invalidates the transcript.
Supported input: 16-bit PCM WAV, up to 90 seconds. Never redirect transcript
output into public logs. See [voice privacy and limitations](docs/VOICE.md).

The optional file-only offline voice CLI can inspect an existing speech model
without importing a native inference engine:
`athenz-voice inspect-model --model <local-ctranslate2-directory>`.
It prints only metadata counts and file sizes, not paths, transcript text or
weights. Actual speech transcription remains separately owner-confirmed, with
no recording, network upload or automatic chat/memory integration.

## Measuring offline voice recognition accuracy without collecting speech

AthenZ v0.8's explicitly owner-invoked voice evaluation compares an existing
local WAV recording with a private, owner-verified UTF-8 reference transcript.
It uses the separately installed local faster-whisper model and computes
normalized word error rate (WER) and character error rate (CER), returning
only counts/percentages rather than the owner's words or file paths:

```powershell
athenz-voice evaluate sample.wav --model C:\\PrivateModels\\whisper-ct2 --reference reference.txt --confirm
```

For two existing UTF-8 transcripts, use
`athenz-voice score-text --reference reference.txt --hypothesis output.txt --confirm`
to calculate the same metrics with **no audio read, model load or CUDA work**.
Consent is always explicit; input files are bounded and rechecked for changes.
Neither path writes text into AthenZ memory/training data, and the output is
not independent proof of real speech-model accuracy. See [offline voice
privacy and evaluation](docs/VOICE.md).
