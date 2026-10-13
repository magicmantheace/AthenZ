# AthenZ — Roadmap to v1.0

Mission: a local-first digital twin of the owner's preferred style and decisions,
a bounded coding assistant that learns from verified work and carefully gated
periodic model updates. It is not a literal copy of a human consciousness.

## Safety contracts
- Twin estimates owner behavior; Agent works for owner. Never invent lived history.
- Three rates of learning: approved context, reviewed/test-backed experience,
  and explicitly approved benchmark-gated local LoRA updates (experimental
  implementation exists; target-device training/inference not yet validated).
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

### v0.6 Windows portable and setup readiness (experimental)

- [x] Off-by-default local Setup tab with separate, explicit loopback Ollama
  probe; no private content in diagnostic responses.
- [x] Windows-only unsigned PyInstaller onedir packaging workflow, disposable
  SQLite/Tcl self-test, 7-day artifact; no automatic release, OS startup or install.
- [x] Hosted Windows CI produced the unsigned PyInstaller portable ZIP and passed
  offline executable + native Tk GUI startup smokes on 2026-10-12
  (public Actions run 38331854750; artifact expires after 7 days).
  **This is NOT owner-device compatibility, code signing or installer validation.**
- [ ] Native Windows 11 GUI/HiDPI/accessibility and RTX 3060 Ollama/WSL2 Docker
  hardware acceptance; Windows installer, signing and rollback remain outstanding.

### Offline SQLite recovery (v0.6 increment)

- [x] Owner-confirmed recovery of verified SQLite snapshots into a **new only**
  AthenZ profile path; never overwrite or modify the running profile.
- [x] Disable previously authorized scheduler leases/arms and runtime model
  routing in the recovered copy, preserving memory and approval records.
- [ ] Complete versioned whole-profile archive/restore of explicitly selected
  private datasets, adapter files, review artifacts and model provenance.
- [ ] End-to-end Windows backup/recovery testing and owner-reviewed release UX.

## 2026-10-12 — Digest-bound episode adjudication (archival development)

- [x] Deterministic topical candidate overlap preview includes full pending and approved records/provenance, with exact SHA-256 over reviewed evidence.
- [x] Explicit owner-confirmed keep-both, reject, or single-predecessor supersession is performed atomically and refuses stale reviews; desktop and CLI surfaces have no auto-decision path.
- [ ] Semantic contradiction detection, advanced retrieval evaluation and Windows assistive-technology acceptance remain unfinished. Tag overlap is NOT a truth judgment.

### v0.6 explicit local inference functional smoke

- [x] Owner-confirmed bounded localhost-only generation check using fixed synthetic prompt, no AthenZ private context, no reply persistence and sanitized outcome.
- [x] Offline fake-model, actual loopback HTTP, proxy bypass and redirect refusal regression tests.
- [ ] Real owner-device inference with installed Ollama model and RTX 3060/WSL2 acceleration remains unverified; does not certify hardware.

## Public hosted acceptance evidence — 2026-10-12

- The repository was verified public. Free standard public-repository GitHub-hosted
  runners are being used on isolated `ci/` branches; the test workflow checks out
  an exact SHA of the archival development branch, never `main`.
- At reviewed source `d538bde4602fab4daeb8cedec3daec6a298b0673`,
  GitHub Actions Linux Python 3.11 (run 38331720210), Linux 3.12 and 3.13
  (run 38331854750) passed the full 413-test suite (four skips each).
- Hosted Windows PyInstaller onedir executable and Tk GUI startup smoke passed
  (run 38331854750), with SHA-256 checked on the ZIP and a seven-day
  downloadable unsigned artifact. This does not establish portable desktop
  readiness on the owner's Windows 11 or with real Ollama/RTX 3060.
- No private owner database, training corpus or personal context was uploaded.
  Hosted Windows Python 3.11 full regression also passed (run 38331720210):
  413 tests, seven platform-dependent skips, zero errors and zero failures.
  This is a hosted runner gate, not owner-device hardware acceptance.

### v0.7 lexical held-out protection and hosted sandbox check

- [x] Fail-closed held-out evaluation check for literal and sufficiently
  distinctive normalized-word collisions in approved private Twin context.
- [x] Withhold approved SFT instruction pairs matching held-out scenarios by
  normalized word sequence, even with changed punctuation or capitalization;
  reverify/revoke stale exports when the private held-out set changes.
- [x] Hosted Docker integration and synthetic sandbox threat suite: seven tests
  passed using a registry-digest-pinned image in public GitHub Actions run
  [38332727303](https://github.com/magicmantheace/AthenZ/actions/runs/38332727303).
- [x] Linux Python 3.11/3.12/3.13: 417 tests each, four skips,
  no failures, and hosted Windows Python 3.11: 417 tests, seven skips, no
  failures against reviewed `be8cf5b93a396b4737bf145e6896d7cac8b9eb66`
  source (public CI runs 38332623888 and 38332502198).
- [x] Hosted unsigned Windows PyInstaller + offline executable/Tk smoke passed
  on this source (public run 38332502198). Artifact retention is seven days.
- [ ] Native owner-device WSL2, real Ollama model, RTX 3060 and assistive
  technology tests remain outstanding. True semantic held-out contamination
  and training-weight memorization detection are not established by these
  normalized-string checks.

### 2026-10-12 — v0.7 evidence isolation and paired model comparison increment

- [x] Reviewed SFT export protects held-out decision scenarios and distinctive
  gold rationales even when embedded inside longer instruction/completion text.
  A compiled four-token-prefix index keeps this deterministic for larger owner
  histories, while preserving conservative exact-sequence comparisons.
- [x] Approved scenario duplicates crossing train/calibration/test partitions,
  after Unicode/case/punctuation/whitespace normalization, fail closed before
  inference, at benchmark persistence and at adapter review. The database
  never exposes collided text in errors or report metadata.
- [x] Local baseline/candidate benchmark evidence checks each case's predicted
  choice, correctness flag, invalid response count and aggregate accuracy.
  Reported paired win/loss/tie counts and an exact one-sided sign-test tail
  provide descriptive information without automatic promotion.
- [x] Immutable aggregate reports are checked for internal arithmetic and
  finite values again when written or read for adapter selection; legacy
  metadata-only reports remain readable but are not independently attested.
- [x] On reviewed implementation `9b423813bfba6039e45be113d8155683da77b668`,
  public CI run [38334418348](https://github.com/magicmantheace/AthenZ/actions/runs/38334418348)
  ran 433 Python tests on Linux 3.11 (four skips, no failures/errors);
  [38334386292](https://github.com/magicmantheace/AthenZ/actions/runs/38334386292)
  passed Linux Python 3.12 and 3.13 (433 tests each, four skips), and the
  unsigned Windows portable build, packaged self-test and Tk GUI startup smoke.
- [ ] True semantic paraphrase detection, independence from prior model-weight
  memorization, independently attested local candidate lineage, owner-device
  Windows 11 accessibility and RTX 3060 Ollama acceptance remain outstanding.

The score comparison is **not** an independent model certification. There is
no automatic training, model switching, installer release, network access to
owner profile data or unattended coding action implied by this milestone.

### 2026-10-12 — LoRA task authority fencing

- [x] Explicit local QLoRA execution now fences completion to the exact
  running checkpoint revision established at launch. A newer pause or owner
  state update is never overwritten by a late training completion or
  error handler; another worker's CAS write wins.
- [x] A trainer must report a bounded positive integer count of actually used
  examples and provide a real, non-symlinked adapter weight file before the
  run can be marked complete. Generated adapters are still NOT auto-deployed.
- [ ] Real RTX 3060 CUDA and process interruption behavior needs an on-device
  acceptance test; synthetic tests cannot certify training quality.

### 2026-10-12 — Adapter registration and training lifecycle integrity

- [x] Entire immutable adapter registration, including candidate tag, lineage
  and no-deployment marker, is atomically committed into the checkpoint and
  separately bound to a SHA-256 digest in the append-only local metadata event
  ledger. Missing, conflicting or changed anchors block subsequent review.
  Older registrations require explicit owner re-confirmation to add an anchor.
- [x] Model-comparison persistence checks ordered held-out case-ID hashes and
  requires well-formed distinct baseline/candidate digests when present;
  partial digest metadata fails closed, including on legacy reports.
- [x] QLoRA training completion is revision-fenced to its owner-authorized
  running checkpoint. A concurrent owner pause or checkpoint update cannot
  be overwritten by completion or by an error handler.
- [x] Invalid/zero/noninteger training example counts and unsafe adapter
  weight pointers are refused; no automatic training or model promotion.
- [x] Distinctive approved decision scenarios with at least 88% lexical
  word-set overlap (8+ distinct words/48+ characters) cannot cross evaluation
  partitions without explicit owner cleanup. Reviewed SFT instructions/answers
  with such strong similarity to private held-out scenarios/rationales are
  excluded from training exports and invalidate stale exports.
- [x] Synthetic regressions added for valid-tag swap attempts, append-only
  registration anchors, legacy owner re-confirmation, training authority
  races, invalid trainer outputs and lexical near-duplicates.
- [ ] Host CI regression and real owner-device model/GPU acceptance remain
  separate requirements; these safeguards are not cryptographic signatures,
  independent semantic similarity or proof of model lineage.

### 2026-10-12 — Public regression evidence for registration and LoRA safety

- Latest implementation SHA: `2b7c1110623588f86e18493d1aee06258ff1b292`.
- Hosted Linux Python 3.11, 3.12 and 3.13: each ran 447 synthetic tests,
  four skips and zero failures/errors. Evidence:
  [regression run 38341284972](https://github.com/magicmantheace/AthenZ/actions/runs/38341284972)
  and [compatibility/Windows portable run 38341100306](https://github.com/magicmantheace/AthenZ/actions/runs/38341100306).
- Hosted Windows portable PyInstaller ZIP, executable self-test and Tk GUI
  startup smoke passed on the same reviewed implementation.
- [x] Pinned, actual Docker isolation and synthetic threat suite: seven tests
  passed on [run 38341307100](https://github.com/magicmantheace/AthenZ/actions/runs/38341307100).
- Full hosted Windows Python 3.11 regression is in run 38341284972; its job
  conclusion must be independently checked before calling that platform green.
- This is a software acceptance increment, not proof of RTX 3060 performance,
  actual Windows 11 accessibility or independent model/adaptor lineage.

### Owner-confirmed local CUDA compute smoke (2026-10-12 increment)

- [x] Extend `athenz-doctor --probe-cuda --confirm` with a minimal, sanitized
  synthetic CUDA tensor computation using optional installed PyTorch only.
  No private profile access, model download, GPU IDs or automatic startup.
- [ ] Actual owner-PC PyTorch CUDA, RTX 3060 and WSL2 results remain unobserved;
  this opt-in diagnostic is not QLoRA readiness certification.
