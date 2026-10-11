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
