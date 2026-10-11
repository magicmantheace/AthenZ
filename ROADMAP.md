# AthenZ — Roadmap to v1.0

Mission: a local-first digital twin that models the owner's preferred style, decisions and values; a bounded coding agent that learns from verified work; and periodic evaluated model-weight updates. **Not** a literal copy of the human or an automatically self-modifying neural network.

## Contracts
- Twin estimates how Adam might speak/choose. Agent accomplishes scoped tasks, informed by preferences. Never impersonate the actual person as fact.
- Three learning rates: immediate approved memory; verified experience consolidation; reviewed, benchmark-gated LoRA fine-tuning.
- All personal facts have origin, approval state and revocation. Never promote unverified speculation to known personal history.
- Run code tools in authorized, isolated workspaces, with diff review and constrained commands. External messages, account changes, destructive operations and publishing require explicit approval.
- Private data is stored locally by default, not committed to Git. Have export, deletion, audit and backup controls.
- Model and experience upgrades require evidence, test results, repeatable versioning and rollback.

## Versions and completion gates
| Version | Scope | Acceptance gate |
| --- | --- | --- |
| v0.1 | Prototype chat, local model, memories, feedback and proposals | Mocked prototype tests pass; target-PC inference still unverified |
| v0.2 | Reviewable identity, provenance, revisions, decision cases, private export and granular deletion | Approved items only reach prompts; corrections tracked; import data removable |
| v0.3 | Episodic, semantic and procedural memory; event ledger; contradiction resolution | Evidence-traceable lessons survive restart; contradictions visible |
| v0.4 | Repository-aware autonomous coding loop in disposable worktrees | Multi-file fixes with bounded tests and approval-based commit/push |
| v0.5 | Training candidate review, SFT/LoRA recipes, fixed benchmark and promotion gate | One repeatable adapter train/eval/promotion/rollback cycle |
| v0.6 | Desktop interface and supervised background scheduler | Can pause/restart tasks and supervise changes without CLI |
| v0.7 | Held-out decision matching and stronger reasoning | Identity score improves without fabricated experiences |
| v0.8 | Optional voice and selected local/account connectors | Opt-in scope enforcement and independent disable controls |
| v0.9 | Hardening, migrations, private backups, threat tests and packaging | Regression suite passes on target PC |
| v1.0 | Stable personalized local agent with controlled learning | Measured identity, memory, coding, privacy and recoverability gates met |

## Immediate critical path
1. Port the v0.1 prototype source safely into AthenZ; avoid copying any actual user data.
2. Integrate v0.2 identity store into retrieval and split Twin / Agent instructions.
3. Add a decision-scenario evaluation corpus with held-out cases.
4. Build v0.3 experience ledger and safe coding runner; only then tackle LoRA.
5. Benchmark Ollama inference and VRAM use on RTX 3060 12 GB Windows/WSL2.

All timeline estimates are deliberately omitted until a baseline is benchmarked.