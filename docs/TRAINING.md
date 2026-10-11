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
and runs a small synthetic smoke prompt against the candidate. It never sends
owner private text for that smoke test. The installed tag is not modified.
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
