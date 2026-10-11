# AthenZ — Roadmap to v1.0

Mission: a local-first digital twin of the owner's preferred style and decisions,
a bounded coding assistant that learns from verified work and carefully gated
periodic model updates. It is not a literal copy of a human consciousness.

## Safety contracts
- Twin estimates owner behavior; Agent works for owner. Never invent lived history.
- Three rates of learning: approved context, reviewed/test-backed experience,
  and benchmark-gated explicit LoRA updates (not yet implemented).
- Imported chat data remains pending by default; training export only includes
  reviewed data. No private data or corpora in Git.
- Explicit file scope, review and human action precede any code write; no
  unattended code execution, commit, push, purchase, deployment or messages.
- Evidence and evaluation determine promotion; rollbacks must revoke lessons
  tied to reverted changes.

## Versions and gates
| Version | Scope | Acceptance gate |
| --- | --- | --- |
| v0.1 | Local Adam Twin prototype | Mocked tests passed; hardware inference unverified |
| v0.2 | Provenance, conversation persistence, reviewable feedback, writing import and scoped code proposals | One private DB, migration, approvals and tests (implemented, awaiting hardware test) |
| v0.3 | Episodic, semantic and procedural memory; event ledger; contradiction handling and checkpoints | Relevant approved lessons reliably retrieved, corrected or revoked |
| v0.4 | Autonomous coding loop in disposable, isolated worktrees | Multi-file tasks with bounded tests and human review of commit/push |
| v0.5 | SFT/LoRA dataset, fixed baseline, model version registry, promotion gate | Train/eval/promotion/rollback repeatable on supported GPU |
| v0.6 | Desktop shell and supervised background scheduler | Pause/restart jobs and review proposed actions without CLI |
| v0.7 | Held-out identity and decision evaluation | Predictions improve without leaking test cases into prompts |
| v0.8 | Optional voice and local connectors | Per-integration opt-in and disable controls |
| v0.9 | Privacy and reliability hardening, installer and Windows validation | Backup/erasure threat tests and regression gates pass |
| v1.0 | Stable personalized local agent with controlled learning | Identity, coding, privacy, recoverability benchmarks met |

## Next critical path
1. Record and evaluate user decisions with reproducible train/test splits (#3).
2. Complete v0.3 event ledger with replay-safe checkpoints, indexed evidence,
   contradiction review and relevant retrieval (#4). A preliminary test-backed
   proposal/experience ledger already exists, but it is not yet a complete v0.3.
3. Build OS-isolated coding execution (v0.4) instead of running arbitrary
   repository tests in the host environment.
4. Benchmark model inference on RTX 3060 12GB Windows/WSL2.
5. Later: LoRA training should never self-promote an unreviewed model.

## v0.3 incremental development (experience memory)
- [x] Private schema v4 migration preserving historical identity and feedback.
- [x] Owner-reviewed episodes with exact-source purge, topic-tag retrieval,
      supersession review and inspection of potentially conflicting topics.
- [x] Current-test evidence gating for retrieved procedural lessons.
- [x] Revision-checked, restart-safe task checkpoints; contents do not execute.
- [x] Append-only metadata event triggers and synthetic lifecycle tests.
- [ ] Verified artifact IDs and reproducible external test attestations.
- [ ] Semantic contradiction matching and explicit owner adjudication UI.
- [ ] Scoped, isolated worktree coding runner and autonomous scheduler (v0.4).

## v0.3 verification extension
- [x] Explicit owner-reviewed contradiction links; unresolved disputes exclude
      both affected episodes from prompts until an approved winner is chosen.
- [x] Schema v5 adds hashed local artifact IDs linked to exact test runs,
      without storing source evidence files in private memory.
- [x] Cascade deletion and regression tests for artifacts and disputed episodes.
- [ ] Independent run attestation / signed CI provenance. Local file hashing
      alone does not prove that an external test actually ran.

### v0.4 initial supervised-worktree slice (2026-10-11)
- Implemented: explicitly authorized clean-repository worktree, checkpoint restore, reviewed multi-file proposals, host-safe AST parsing, optional digest-pinned container-only unittest command and explicit disposable worktree cleanup.
- Remaining: true multi-step bounded coding loop, cancellation and retry budget, independent test provenance, Windows/WSL2 validation and owner-approved commit/push. Worktrees are not a security boundary by themselves.


## v0.5 private offline QLoRA groundwork (2026-10-11)
- [x] Reviewed SFT dataset creation, deterministic fingerprints, held-out exact-match exclusion and opt-in export.
- [x] Aggregate-only baseline/candidate evaluation with source-consent invalidation.
- [x] Explicit and bounded local Qwen2-family NF4/LoRA training recipe and optional CUDA execution path, private source/model fingerprints and explicit checkpoint resumption.
- [x] Adapter checksum registry and tamper-detecting private selection/rollback pointer, with a current held-out report and owner lineage acknowledgment.
- [ ] **Hardware unverified:** run the QLoRA backend on the target RTX 3060 and verify CUDA/WSL2 dependency versions, available VRAM and saved adapter compatibility.
- [ ] Independently prove that a candidate served by Ollama contains the evaluated adapter; conversion/loading and promotion are NOT implemented.
- [ ] Create robust held-out regression benchmarks, an owner-approved installer/rollback integration, and signed training provenance.

An adapter registry entry or review selection does NOT affect AthenZ inference, install model weights or authorize promotion. A model comparison alone is insufficient to establish an adapter's identity or quality.
