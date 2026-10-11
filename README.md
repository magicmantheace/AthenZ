# AthenZ

**AthenZ** is a private, local-first project to build a personal digital twin, an autonomous-but-bounded coding assistant, and an evidence-driven learning system.

**Current status:** v0.2 identity foundation (pre-release), plus a local-only Ollama chat entry point. The earlier Adam Twin v0.1 coding/feedback prototype is not yet migrated into this repository. Ollama inference on the target PC has not been tested; self-directed coding and LoRA fine-tuning are **not** implemented.

## Operating modes

- **Twin:** estimates how the owner might write or decide, based on approved examples. It must not claim to literally be that person.
- **Agent:** works as a capable assistant, respecting the owner's preferences while using independent reasoning and verification.

## What's implemented in this branch

- Private SQLite identity store, no cloud dependency.
- Proposed vs approved vs rejected profile information and decision examples.
- Explicit source/provenance fields, confidence labels, and reviewable text revisions.
- Granular deletion of records and exact-source purge (including revision history).
- Importable approved-only context builder, separate Twin/Agent prompt policies.
- CLI controls and a synthetic unit test suite.
- Optional interactive local Ollama chat, with Twin/Agent modes and approved profile context. Session history is currently in-memory, not persisted.

## Quick start (Python 3.11+)

```bash
python -m pip install -e .
athenz init
athenz propose preference "Prefer evidence over speculation"
athenz list identity --status pending
athenz status 1 approved
athenz decision "Ship now or verify first?" "Verify first" "Avoid regressions"
athenz decision-status 1 approved
athenz context
python -m unittest discover -s tests -v
# After Ollama is installed and the model has been pulled:
ollama pull qwen3.5:2b
python -m athenz.chat --mode twin
# or python -m athenz.chat --mode agent
```

Run from Windows PowerShell with `py -3.11 -m pip install -e .` if `python` is not the desired interpreter.

Private data is kept at `~/.athenz/identity.sqlite3` (or `ATHENZ_HOME`). The above commands write locally; do not commit that directory or user-specific exports to Git. Export with `athenz export private-profile.json` **outside** the repository. Use `athenz --help` for the full command list.

## Important controls

- `athenz revise <id> "replacement" --reason "correction"` resets approval to pending.
- `athenz forget identity <id>` removes a specific memory and its stored revisions.
- `athenz purge-source <source> --source-ref <ref>` deletes all data imported under that precise source pair.
- Stored activity events contain operation names and record IDs, not raw personal text.

This is **not yet encrypted at rest**. Keep your user account and backup destination secured. SQLite WAL sidecar files may retain older content until checkpointing; private-data erasure and backup retention require further hardening before v1.0.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the v0.1–v1.0 acceptance gates, [AGENTS.md](AGENTS.md) for contribution/privacy rules, and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for system boundaries.
