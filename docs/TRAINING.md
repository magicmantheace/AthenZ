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
