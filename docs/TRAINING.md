# AthenZ v0.5 — reviewed training dataset foundation

This is a **private dataset builder**, not model training, LoRA, autonomous
self-learning, or a deployed adapter. It runs locally with Python stdlib.

## Operator workflow

```sh
athenz-training inspect
# Review individual training pairs separately using `athenz list train_pairs`.
# Only approved pairs are eligible; pending/rejected remain excluded.
athenz-training build --confirm
athenz-training verify <printed-full-sha256>
# If you revoke consent, reject/delete the source and remove old exports:
athenz-training delete <printed-full-sha256> --confirm
```

The exported SFT JSONL and source-ID manifest live in
`ATHENZ_HOME/datasets` (by default `~/.athenz/datasets`), **outside Git**.
Owner text never goes in the repository, workflow logs, or CLI readiness
report. Files use restrictive permissions where supported and are immutable
by the tool (identical exports are only reused after verification).

For leakage prevention, exact normalized instruction matches against **all**
calibration/test decision scenarios are withheld. Case, Unicode compatibility,
and whitespace variations are normalized. This is deliberately narrow; it
**cannot detect paraphrased or semantic leakage** and is no substitute for a
curated, separately held-out evaluation set.

Identical approved input/output pairs are deduplicated; conflicting answers
to the same normalized input **block** export until a person reviews them.
A stable SHA-256 identifies the complete JSONL byte stream. The manifest also
records reviewed source row IDs, enabling a future trainer to revalidate
current approval and dataset bytes before starting. Approval revocation, source
erasure, or a newly held-out matching scenario causes `verify` to fail.

**Important:** previously exported snapshots are not deleted automatically
when a source is revoked. Run `delete` for each affected export and manage
external backups separately. SQLite WAL / file backups may retain copies.
Dataset hashes are integrity checks, not signed or independently attested
provenance. Training, model selection, baseline benchmark, LoRA creation,
deployment and rollback remain unimplemented.

## Compare a candidate model (evaluation only)

Once you have a separately created candidate model available in local Ollama,
use the **same** eligible, owner-approved dataset snapshot and a held-out
calibration set to assess whether it performs better than the baseline:

```sh
athenz-training compare <dataset-sha256> --baseline local-base-tag \
  --candidate local-candidate-tag --split calibration --min-cases 10 --confirm
```

This makes local Ollama requests and records **aggregate** accuracy, gain,
model names, decision-set fingerprint and dataset SHA-256 under the private
`ATHENZ_HOME/evaluations` folder. Case scenarios, user answers and predictions
are omitted from the report. Both models are evaluated on the *same*
deterministically ordered/shuffled cases, and the report is discarded if the
private source approvals or evaluation decisions change while running.

The comparison can label a model `eligible_for_review` if its observed
accuracy exceeds the baseline on at least 10 held-out cases. **This is not
statistically robust proof of improvement**, is not independent attestation,
and does not grant permission to install or deploy any adapter. Use calibration
for iterative development and preserve test data for a final, independently
reviewed evaluation. No automatic promotion, model-weight change, or remote
training occurs. Inference may require a working local Ollama installation,
but that is not a prerequisite for independent code development.


## Experimental offline QLoRA backend (v0.5)

AthenZ can now prepare an **immutable local QLoRA recipe**, fingerprint every
base-model safetensors shard, and run an *explicit, opt-in* training process.
The training backend is experimental and has **not yet been run on the target
RTX 3060**; no successful adapter training is claimed.

Prerequisites: a **separately downloaded, trusted Hugging Face Qwen2/Qwen2.5
safetensors directory** containing `config.json` (model_type `qwen2`), a
fast `tokenizer.json`, and weights. An Ollama-only GGUF model directory is
**not** interchangeable with HF safetensors. Use a 1.5B instruct model as a
conservative first GPU test on 12 GiB VRAM; available memory depends on the
OS, model variant and other running programs. On Windows, use a local WSL2
Linux CUDA installation for PyTorch and bitsandbytes.

Install locally compatible CUDA PyTorch, `transformers`, `peft`, `accelerate`,
and `bitsandbytes` from trusted packages **before** invoking training; they
are deliberately optional, not imported by other AthenZ commands. Offline
training requires all model dependencies already installed, and the loader
uses `local_files_only=True` and `trust_remote_code=False`.

```sh
athenz-training inspect
athenz-training build --confirm
athenz-training prepare-qlora DATASET_SHA256 \
  --base-model /path/to/local/qwen2.5-1.5b-instruct --max-steps 80 --seq-length 512 --confirm
athenz-training verify-qlora RUN_ID
# Only on your own trusted CUDA/WSL2 machine, after inspecting the recipe:
athenz-training run-qlora RUN_ID --confirm
# An interrupted or failed run must be explicitly resumed:
athenz-training run-qlora RUN_ID --resume --confirm
```

The run remains under private `ATHENZ_HOME/runs/qlora-<id>/`, with its recipe,
checkpoints, and adapter. QLoRA uses 4-bit NF4 plus LoRA rank 8,
microbatch 1, gradient accumulation 8, up to 500 steps, and saves step
checkpoints with bounded retention. Supervised targets mask the user/prompt
tokens; excessively long examples are skipped instead of silently truncated.
There is **no CPU fallback**, cloud API, auto-resume daemon, model activation,
Git commit of training data or automatic promotion. Training and resumed
training revalidate explicit source approval and weights before loading, and
again before a run can be marked complete. A successful local training run
**does not establish candidate quality or automatically load into Ollama**.

The backend has been unit-tested with synthetic tiny fake weights, mocked
trainer calls and no CUDA. Dependency compatibility and VRAM behavior must
be verified on the target machine; for untrusted model files, use a VM.


## Adapter registry and reversible review pointer (no deployment)

Completed, still-valid private training outputs can be registered only after
verifying the adapter safetensors digest, its LoRA config, and the original
base-model fingerprint. Registration records metadata privately in the AthenZ
SQLite checkpoint store. **The candidate label is an owner assertion**, not
proof that an Ollama tag is actually backed by the registered adapter.

```sh
athenz-training register-adapter RUN_ID --candidate locally-evaluated-candidate --confirm
athenz-training selection
# AFTER creating and reviewing a private comparison report for that candidate:
athenz-training select-adapter RUN_ID --report-sha256 EVAL_SHA \
  --revision 0 --ack-lineage --confirm
athenz-training selection
# To roll back, copy the currently displayed revision:
athenz-training rollback-adapter --revision CURRENT_REVISION --confirm
```

`select-adapter` requires an unaltered, current held-out evaluation report,
a matching approved dataset, a strictly improving candidate score, and a
manual acknowledgment of the unproven adapter→candidate mapping. Both the
adapter and report are revalidated before updating the checkpoint, and a
compare-and-swap revision prevents stale concurrent selection. Rollback also
revalidates its target. **Selection and rollback only change a private review
pointer:** they deliberately do not alter Ollama, load adapters, change Twin
responses, move model files, or make network calls. Actual promotion requires
separate installer integration, model conversion/testing, and user approval.


## Local Ollama candidate selection and rollback (experimental)

AthenZ can safely change **its own chat routing** to an already-installed local
Ollama candidate; it cannot install or import the LoRA weights. The candidate
must be registered with the adapter label, evaluated against an existing
baseline, and chosen via `select-adapter --ack-lineage` first. **The lineage
acknowledgment is a manual assertion, not cryptographic proof that Ollama's
weights contain that adapter.** Independently verifying that mapping and a
supported Ollama import route is future work.

```sh
athenz-training selection
athenz-training runtime-status
athenz-training runtime-activate --baseline base-evaluated-tag \
  --revision 0 --confirm
python -m athenz.chat --mode agent
# Use the displayed runtime revision after any activation or prior rollback:
athenz-training runtime-rollback --revision CURRENT_RUNTIME_REVISION --confirm
```

`runtime-activate` checks that the registered adapter, approved dataset and
held-out evaluation report still agree, ensures that both Ollama tags exist on
an **explicit loopback** endpoint, reads their SHA-256 digests from `/api/tags`,
requires that both hashes match the digests recorded during the *held-out model comparison*,
and runs a small synthetic smoke prompt against the candidate. It never sends
owner private text for that smoke test. The installed tag is not modified. Older evaluation reports created
before model digest pinning cannot authorize runtime activation; rerun the
comparison with the candidate actually installed.
Activation uses a compare-and-swap checkpoint revision to avoid stale writes.

Without `--model`, AthenZ chat consults the private selected route before
startup and rechecks the selected Ollama tag and current review/consent before
each new message. It will *refuse* to route to a replaced tag, revoked dataset,
changed adapter, or altered held-out report. It does not silently downgrade to
a different tag. Explicit `--model` remains an intentional manual override.
`runtime-rollback` restores the already-recorded baseline tag and manifest
digest, even if the candidate has vanished or the adapter consent was revoked.
If the baseline itself has changed, rollback refuses rather than routing to
unknown weights. This is a runtime routing preference, **not Ollama server
model deployment, download, deletion, or weight rollback**.

Local HTTP requests disable proxy inheritance and reject HTTP redirects; this
is essential because Ollama prompts contain sensitive user context. The tag
lookup returns metadata only. Revalidating a large offline base-model
fingerprint on every prompt prioritizes consent/integrity over response speed;
performance optimization without weakening this guarantee is pending.

The current official Ollama Modelfile documentation lists `FROM` for compatible
Safetensors model imports, but does not currently describe `ADAPTER` as a
supported directive. AthenZ therefore does not automate LoRA import or assume
that a separately named candidate includes a given adapter. Actual Ollama
adapter interoperability must be validated on a supported release and target
hardware before an installation pipeline is enabled.

## Offline merged-GGUF handoff to Ollama (experimental)

Current Ollama documentation describes `FROM /path/to/file.gguf` to import a
**complete** model. It does **not** currently document a supported direct
import of AthenZ's Qwen2.5 PEFT/QLoRA safetensors adapter. Therefore the
handoff is deliberately restricted to a *separately merged and converted full
GGUF model*; it never silently treats LoRA weights as a complete model.

After separately reviewing/merging a trained adapter into the **exact matching
base weights**, converting/quantizing the resulting complete model to GGUF,
and verifying the model yourself, run:

```sh
athenz-training prepare-import <run-id> /path/to/merged.gguf \
  --candidate athenz-my-candidate:trial --ack-merge --confirm
athenz-training verify-import <run-id>
# Only after reviewing the private Modelfile and the candidate name:
athenz-training import-local <run-id> --confirm
athenz-training verify-import <run-id> --check-ollama
```

The first command writes a private, immutable Modelfile with a `FROM` directive
for the complete GGUF and binds it to an approved adapter record and an exact
GGUF SHA-256. The owner acknowledges the merge lineage; a digest **does not
cryptographically prove** the merged model came from that adapter. The import
requires a fresh, dedicated `athenz-…:…` tag, checks for an existing
Ollama tag before creating (not atomic against concurrent writers), pins local CLI traffic to loopback, and does not call `ollama
push`, `ollama pull`, `ollama rm`, or activate AthenZ's chat routing.

If `ollama create` crashes or fails after starting, the run intentionally stays
in `running` state to prevent unattended retries or ambiguous overwrites. A
person must inspect Ollama and explicitly resolve the incomplete import. No
OS-level model sandbox, external lineage attestation, adapter merger, actual
CUDA fine-tune or Windows/WSL2 conversion/inference test is claimed here.

Official import docs: https://docs.ollama.com/import

## v0.7 offline learning-cycle preflight (2026-10-14)

Use the new **non-inferential** training command to inspect whether an
owner-controlled learning experiment has enough reviewed training examples,
a distinct and clean set of held-out decisions, and (optionally) a currently
verified immutable SFT snapshot:

```sh
athenz-training learning-plan --split calibration --min-cases 10
# After separately reviewing/approving samples, opt in to exporting:
athenz-training build --confirm
# Pass the SHA-256 printed by the export command:
athenz-training learning-plan --dataset-sha256 <reviewed-dataset-sha256> --split calibration
```

`learning-plan` does **not** create/export a dataset, call Ollama, inspect
installed models, launch GPU training, select a candidate, deploy an adapter
or authorize model promotion. It returns aggregate counts, a verified/stale/
not-selected snapshot status, held-out contamination/independence flags, a
stable-source observation, and one suggested manual next step without printing
private prompt text, answers, rationales, file paths, training samples or
dataset identifiers. A selected invalid/missing snapshot is a blocker, not
an instruction to silently rebuild data.

When `ready_for_manual_model_comparison` is true, it means only that
**preflight source conditions** passed at that instant. It is not evidence
of improved behavior or model quality; the existing explicit local
`athenz-training compare ... --confirm` still requires separately installed
baseline/candidate tags, owner permission, repeated evidence checks, and
manual score/lineage review. Snapshot-read operations do not attest model
weights or protect against hostile same-user filesystem races. A running
AthenZ profile is SQLite-backed and may still create SQLite sidecar files;
the preflight does not create a new dataset or model artifact.

## v0.7 supervised learning-session journal (2026-10-14)

The new session commands persist an **evidence journal only** in the private
AthenZ SQLite profile; they do not call a model, launch training, change local
Ollama routing, or authorize promotion. This makes a baseline → reviewed
training → candidate evaluation → manual rollback decision traceable while
the separate existing commands carry out explicitly approved work.

```sh
athenz-training learning-plan --limit 12 --min-cases 10
athenz-training session-start <approved-dataset-sha256> --limit 12 --confirm
athenz-training session-status <session-id>
# Separately, use the existing prepare-qlora, run-qlora and register-adapter
# commands with their own explicit approvals. Then record the completed run:
athenz-training session-link-run <session-id> <run-id> --revision 1 --confirm
# Separately compare installed baseline and candidate models and save a report:
athenz-training session-link-report <session-id> <saved-evaluation-sha256> --revision 2 --confirm
athenz-training session-close <session-id> --revision 3 --confirm
```

Actual revision values are returned by each step: never guess or reuse a stale
revision. An unfinished session can be cancelled with `session-cancel`,
the current `--revision`, and `--confirm`. Cancellation **does not** cancel
running GPU jobs, uninstall adapters or roll back an activated model; those are
separate explicit operations.

Session creation requires a currently verified consent-based dataset,
adequate protected held-out cases, lexical independence checks, and a stable
evaluation population. Linking a training run requires that it has completed
and has been separately registered under an owner-chosen candidate label.
Linking a report requires an immutable saved schema-two comparison from the
same dataset, exact split, seed, case limit and candidate. The journal accepts
positive, negative and tied observations; **a positive observed score never
automatically promotes a candidate**, and the report's paired significance
must be assessed independently. Completed sessions are also revalidated on
status reads; source revocation, report tampering or changing evaluation data
shows `evidence_current: false` instead of silently preserving readiness.

These checkpoints are not tamper-proof signed attestations. They store opaque
IDs, hashes and metadata locally, not personal examples or transcripts.
Synthetic CI does not establish on-device CUDA training, voice fidelity or
actual behavioral improvement.

## v0.7 source-pinned pretraining baseline (October 14, 2026)

New learning sessions require a locally measured baseline **before** a
completed training run may be linked. This closes the gap where a candidate
could be evaluated with no recorded pre-training reference. The steps are:

```sh
athenz-training session-start <reviewed-dataset-sha256> --confirm
athenz-training session-baseline <session-id> --model <installed-baseline-ollama-tag> --revision 1 --confirm
# Separately prepare, train, and register a candidate with existing commands.
athenz-training session-link-run <session-id> <registered-completed-run-id> --revision 2 --confirm
# After a separate owner-confirmed compare and report save:
athenz-training session-link-report <session-id> <saved-schema-two-report-sha256> --revision 3 --confirm
```

Use the actual current revisions from each response; numbers shown are only
illustrative. `session-baseline` is the one new command that **does**
contact an installed loopback Ollama model, only when explicitly confirmed.
It runs the existing protected held-out evaluation with a pinned model
digest, zero-temperature and deterministic seed. It records aggregate
correct/total counts, exact case-identity and protected source fingerprints
in the private SQLite journal, not personal prompts, predictions, rationales,
or model output text. The confirmation never grants training or deployment
permission. If evidence is revoked or model bytes/tag digest change before
the evaluation completes, the session stays `prepared`.

The later candidate comparison must match the pre-training baseline tag,
digest, selected case set and correct count. If repeating the baseline
produces a different score, it refuses that comparison instead of treating
a candidate gain as established. A session records the observed
`baseline_observed` state while `baseline_model_installed_verified`
stays false during offline status reads: installed model availability is
verified during explicitly approved inference, not in the read-only view.

Legacy schema-one sessions remain readable and may finish the older
pre-baseline workflow; newly created schema-two sessions enforce the new
baseline stage. **This is a local observation, not proof that external
training never happened before it, or that the model's per-case predictions
cannot vary.** Real training and deployment are separate opt-in steps.
