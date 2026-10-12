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

## v0.5 private offline QLoRA groundwork (2026-10-11)
- [x] Reviewed SFT dataset creation, deterministic fingerprints, held-out exact-match exclusion and opt-in export.
- [x] Aggregate-only baseline/candidate evaluation with source-consent invalidation.
- [x] Explicit and bounded local Qwen2-family NF4/LoRA training recipe and optional CUDA execution path, private source/model fingerprints and explicit checkpoint resumption.
- [x] Adapter checksum registry and tamper-detecting private selection/rollback pointer, with a current held-out report and owner lineage acknowledgment.
- [ ] **Hardware unverified:** run the QLoRA backend on the target RTX 3060 and verify CUDA/WSL2 dependency versions, available VRAM and saved adapter compatibility.
- [x] Manual merged-GGUF Ollama import handoff with approved adapter/consent rechecks, immutable local source fingerprint, non-overwrite preflight, private intent journal and observed local tag digest; no auto-selection.
- [ ] Independently prove that an imported candidate contains the evaluated adapter: PEFT merge/GGUF conversion and independently attested lineage are NOT implemented. The owner currently acknowledges the merge manually.
- [ ] Create robust held-out regression benchmarks, an owner-approved installer/rollback integration, and signed training provenance.

An adapter registry entry or review selection does NOT affect AthenZ inference, install model weights or authorize promotion. A model comparison alone is insufficient to establish an adapter's identity or quality.

## v0.6 desktop foundation (experimental)
- [x] Basic native Tkinter desktop shell: Agent/Twin local chat and session persistence, manual feedback, full-context review of pending identity/decision/episode/training items, read-only checkpoint status.
- [x] Thread-separated Ollama work, no shared cross-thread SQLite handle, fail-closed model-route checks and no unreviewed auto-training.
- [ ] Windows desktop visual/manual integration test, real Ollama inference, polished UX and secure installer.
- [~] Supervised scheduler: bounded opt-in foreground proposal queue implemented; native notifications, stronger cancellation/fencing and lifecycle recovery remain.

## v0.6 supervised task interface (incremental)
- [x] Explicit trusted Git repo and owner-selected file-stage entry in the Tk UI.
- [x] Full proposed diff preview, manual exact SHA-256 entry, and second apply confirmation.
- [x] Bounded syntax-only stage validation, explicit advancement, checkpoint
  recovery, missing-Docker fail-closed test command and private aggregate patch export.
- [x] User-initiated threaded operations with SQLite handles isolated per thread.
- [x] Synthetic headless review, rollback, integrity and privacy regression tests.
- [ ] Native Windows/HiDPI keyboard, screen-reader and Ollama/WSL2 integration tests.
- [ ] Build an off-by-default scheduler with explicit per-task authorization,
  cancellation and OS-restart lifecycle, and a signed Windows installer.

The UI does not run tasks in the background without a user action. User-run
hardware tests do not currently block further independent engineering.

### v0.6 supervised scheduler (implementation increment)

- [x] Private disabled-by-default coding proposal queue scoped to a pre-existing, owner-selected Git worktree and immutable stage plan.
- [x] One-shot owner-armed model proposal; manual review/apply/advance remains mandatory for every stage.
- [x] Transactional single-job lease, explicit pause, owner-directed interrupted-run reconciliation and no automatic replay.
- [x] Bounded foreground polling CLI and desktop queue/pause/arm/tick controls; never an OS startup service.
- [ ] Validate live model inference, desktop accessibility, Windows/WSL2 Docker and RTX 3060 integration on target machine.
- [ ] Installer, trust boundary hardening for concurrent recovery and optional future authorized unattended policy (separate approval design required).
