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

### 2026-10-12 — Owner-observed CUDA, inference and acceptance readiness

- [x] Explicit `athenz-doctor --probe-cuda --confirm` does a tiny synthetic
  PyTorch CUDA tensor computation using an already installed local Torch.
  Optional import, driver errors and replies are sanitized; default startup
  has no CUDA action. QLoRA training performance is **not** validated.
- [x] Explicit synthetic Ollama inference reports separately whether text was
  generated and whether the bounded prompt's exact READY instruction was
  followed. Incomplete/error responses are rejected; owner content is not
  read or stored, and quality/lineage are not certified.
- [x] Release acceptance retains previous owner-reported failed/blocked/pass
  observations in a separate local SQLite history and exposes a bounded,
  read-only `athenz-release-readiness history --limit 25` command. Neither
  outcome authorizes deployment or replaces independent verification.
- [x] The portable Windows ZIP and startup smoke passed against implementation
  `4089049c402701b832919a0768449db9a7615427` in public Actions run
  [38343157982](https://github.com/magicmantheace/AthenZ/actions/runs/38343157982).
- [x] Public Linux Python 3.11/3.12/3.13 ran 460 tests each with four skips,
  zero failures or errors (runs
  [38343154083](https://github.com/magicmantheace/AthenZ/actions/runs/38343154083)
  and [38343157982](https://github.com/magicmantheace/AthenZ/actions/runs/38343157982)).
- [x] Actual Docker isolation/threat suite: seven passed against the same
  implementation in [38343274127](https://github.com/magicmantheace/AthenZ/actions/runs/38343274127).
- [ ] Target-machine RTX 3060/WSL2/Ollama/LoRA integration still requires
  explicit owner-observed acceptance; CI hosted runners are insufficient.

### 2026-10-12 — Owner benchmark preparation and evidence consistency

- [x] Compare baseline/candidate evaluations only with plausible, matching
  random-chance baselines on the same held-out cases.
- [x] Owner-confirmed comparison persistence rechecks installed local Ollama
  tag digests and rejects stale baseline/candidate weight identities.
- [x] Owner review cannot save fabricated Wilson 95% intervals or invalid
  response counts in new aggregate evidence.
- [x] Read-only `athenz-training inspect-heldout` reports limited approved
  held-out sample counts, strong lexical split overlap and option validity
  without contacting a model or outputting private scenario text.
- [x] Release acceptance current results must agree with the latest local
  owner-observed audit history for the same check, while legacy unanchored
  records remain readable.
- [x] Source commit `1def9ba7d983fc617575f62b8ad3341499cb513a`
  passed 471 regression tests on Linux Python 3.11, 3.12 and 3.13
  (four platform skips each), plus hosted Windows portable packaging in
  runs [38346880275](https://github.com/magicmantheace/AthenZ/actions/runs/38346880275)
  and [38346862618](https://github.com/magicmantheace/AthenZ/actions/runs/38346862618).
- [ ] Full Windows Python 3.11 suite and actual owner-device RTX 3060/WSL2
  training and inference require separate completed acceptance results.

### 2026-10-12 — Held-out batch privacy, supervised errors and recovery preflight

- [x] Shared deterministic protected prompt construction across actual held-out
  scoring and read-only preflight; reject ambiguous answer labels, including
  case/whitespace variants and malformed historical decision rows.
- [x] Validate **every** selected held-out question/reference combination
  locally before *any* Ollama generation, so contamination in a later case
  does not unnecessarily expose earlier private held-out cases to the model.
  Continue to fence changes between inference calls and final score evidence.
- [x] Preflight returns only aggregate privacy/snapshot checks, never the
  private assembled prompts, rationales or expected choices.
- [x] Explicit private profile ZIP verification now fails closed on malformed
  internal manifest roots, member paths, hashes and noninteger lengths.
- [x] Read-only `athenz-profile inspect` previews selected plaintext archive
  scope by counts/estimated sizes before confirmation, without creating files
  or reading private contents. Release-acceptance history is intentionally
  excluded from restored profiles to avoid stale device certification.
- [x] Supervised queued coding proposals never return or store raw exception
  messages, which may contain private prompts or file paths. Fixed failure
  categories remain visible; jobs still pause without automatic retry.
- [x] Source `59b594e3c00773ce7c96c97b79c338009f697463` passed Linux
  Python 3.11/3.12/3.13: 492 tests per runtime (four skips each), zero
  errors or failures; hosted Windows unsigned portable package and GUI smoke
  passed. See public runs
  [38348235713](https://github.com/magicmantheace/AthenZ/actions/runs/38348235713)
  and [38348241604](https://github.com/magicmantheace/AthenZ/actions/runs/38348241604).
- [x] Pinned Docker integration and sandbox threat suite: 7 passed, run
  [38348270920](https://github.com/magicmantheace/AthenZ/actions/runs/38348270920).
- [ ] Hosted Windows full Python 3.11 result for run 38348235713 must be
  checked separately; native RTX 3060, WSL2, real local Ollama, assistive
  technology and semantic paraphrase handling still need owner validation.

### 2026-10-12 — Disposable selected-profile recovery acceptance increment

- [x] Add `athenz-rehearse-backup <bundle-id> --bundle --confirm` for a
  bounded, explicitly authorized recovery into a disposable local profile.
  Verify every selected recovered artifact against the private ZIP manifest,
  verify the intentionally modified SQLite file against its **post-disarm**
  recovery digest and independently reject retained scheduler leases, running
  jobs, or active Ollama routing. No live profile activation is permitted.
- [x] Require existing trusted non-Git scratch space, sufficient free disk,
  owner consent and safe paths. Temporary plaintext is removed on exit;
  neither temporary deletion nor checksum comparison is encryption/signature.
- [x] SQLite-only and full-bundle verifiers reject malformed **outer** JSON
  manifests, booleans presented as sizes, invalid SHA types, and corrupt schema
  metadata with controlled private errors. No raw source file or text is sent
  to hosted tests.
- [x] Synthetic recovery drills cover active synthetic scheduler leases,
  existing running checkpoints, external private adapter assets, unsafe Git
  scratch roots, missing sources and exception sanitization.
- [x] Reviewed implementation `cffd2005a7db6a32a0e822fee5dffde8d8540e9b`
  passed 500 synthetic tests on Linux Python 3.12/3.13 with four platform skips
  each; Windows unsigned portable executable/Tk startup checks passed
  ([public run 38351342271](https://github.com/magicmantheace/AthenZ/actions/runs/38351342271)).
- [ ] Full hosted Windows/Python 3.11 validation and actual owner-device
  restoration, encrypted transport, installed model lineage and independent
  acceptance remain separate from these synthetic tests.

### 2026-10-13 — Scoped coding/runner privacy and conversion lifecycle

- [x] Sanitize Git subprocess failure diagnostics before they reach local
  worktree/desktop interfaces; reject unsafe Docker mount delimiters and
  invalid timeout argument types.
- [x] Share conservative sensitive filename/path exclusions across supervised
  model code prompts and isolated Docker test snapshot copies, including
  private SQLite, secret extensions and hard-linked local files.
- [x] Enforce revision-fenced, owner-controllable completion and failure of
  multi-hour local CPU PEFT/GGUF conversion. Older workers cannot override a
  pause or superseding revision and never automatically promote a model.
- [ ] Actual CPU merge and GGUF quality/lineage on supported owner hardware,
  interactive Windows accessibility and safe model promotion remain unverified.

### 2026-10-13 — Full supervised coding snapshot isolation and conversion pause

- [x] Owner-triggered per-task Docker unittest now invokes the same
  tracked-file-only, size-bounded snapshot runner used for full-task
  verification. It never mounts the live Git worktree containing `.git`
  or untracked files, and compares snapshot fingerprints before/after Docker.
- [x] Git subprocess messages containing private paths are sanitized; Docker
  argument limits and mount source syntax are checked before execution.
- [x] Reject obvious secret-name variants and filesystem hardlink aliases in
  both model-selected code inputs and Docker snapshot source files.
- [x] Long-running PEFT-to-merged-GGUF conversion is owner-pausable via
  `athenz-training pause-conversion`; revision-fenced workers cannot accept
  stale completion/failure after owner intervention. Explicit `--resume`
  starts a new numbered attempt; CPU process termination remains manual.
- [x] Latest source `7d739ba3669b06466a9cc7e03609a53a3c2861e6`
  passed 514 hosted Python regression tests on Linux 3.12 and 3.13, four
  platform skips each, no errors/failures. Public compatible-build run:
  [38417310918](https://github.com/magicmantheace/AthenZ/actions/runs/38417310918).
- [ ] Latest full hosted Linux/Windows Python 3.11 and unsigned Windows
  portable packaging conclusions, actual owner-machine Docker, RTX 3060 CUDA,
  accessibility and independently attested model identity remain separate.

### 2026-10-13 — Source-stable Docker observation and exact Windows file hashes

- [x] Use bounded no-follow source file handles with inode/link-count/mtime
  checks for staging and rechecking Docker snapshots; refuse tracked names
  with control characters without exposing private source filenames.
- [x] After Docker returns, independently re-copy and compare the current
  tracked checkout to the original tested snapshot. Never report successful
  tests for changed working files; return fixed integrity error status 125.
- [x] Require the owner checkpoint revision and applied proposal to match
  when per-task Docker evidence is recorded; multi-stage verification also
  rechecks the sequence state and revision before persisting evidence.
- [x] Use raw-newline UTF-8 hashes for baseline and applied multi-stage code
  review and syntax checks; synthetic CRLF cases preserve exact approved bytes
  even on hosted Windows Git configurations.
- [x] Public compatibility CI for source
  `f98513308e66530528591c7ac80ef1fd80cf6a64`: Linux Python 3.12/3.13
  passed **520 tests** each (four skipped each, no failures) and Windows
  unsigned portable application executable/GUI smoke passed in
  [38421476754](https://github.com/magicmantheace/AthenZ/actions/runs/38421476754).
- [ ] The full Linux/Windows Python 3.11 regression, actual Docker isolation,
  owner-device training/inference and adversarial same-user filesystem races
  require separate evidence; source snapshot hashes are not cryptographic
  independent attestation.

### 2026-10-13 — Optional private voice input (v0.8 first implementation)

- [x] New `athenz-voice inspect` returns only bounded metadata for a local
  owner-selected 16-bit PCM WAV. It never loads inference packages, opens the
  microphone, creates a background process or stores personal audio.
- [x] New `athenz-voice transcribe --model <existing-local-ct2-dir> --confirm`
  invokes optional faster-whisper with `local_files_only=True` and strict
  absolute-directory validation; CPU default, explicit CUDA option and English,
  French, Spanish, German language selection.
- [x] Bound file size/duration, local model size, segment counts and transcript
  output. Input WAV hashes are checked with bounded no-follow file handles
  before/after inference, and raw model/backend exceptions are sanitized.
- [x] The transcript is owner-visible output only, with no automatic storage,
  Agent/Twin chat action, learning consent, wake word, audio upload or model
  promotion. Synthetic WAV and fake speech-model tests exercise privacy gates.
- [ ] Actual installed faster-whisper/CTranslate2 accuracy and CUDA acceleration
  on the owner PC, native microphone/TTS UI, accessibility and connected
  local voice workflow require separate explicit acceptance. These tests
  are not a privacy or hardware audit of external model libraries.

### 2026-10-13 — File-based voice runtime input stability

- [x] Optional, consent-only offline WAV transcription now checks both the
  selected audio SHA-256 and local CTranslate2 model file identities before
  returning speech text. Model configuration, weights and optional tokenizer
  sidecars cannot silently change during a transcription operation.
- [ ] Real CPU/CUDA speech quality, Windows native CTranslate2 dependencies,
  multilingual comprehension and accessible voice controls remain unverified.

### 2026-10-13 — Offline voice file and native-free inventory safety checkpoint

- [x] WAV metadata inspection opens the selected PCM file via a no-follow
  handle where supported and verifies file identity/size/mtime rather than
  reopening an unchecked filename after path validation.
- [x] Existing local speech model weights/configuration and any recognized
  tokenizer sidecars have stable file identities before/after explicit native
  inference. Changed files prevent an outdated transcript from being returned.
- [x] `athenz-voice inspect-model --model <local-model-directory>` provides
  bounded selected-file count and aggregate size without importing native
  libraries, loading model weights, reading audio, or disclosing owner paths.
- [x] Windows Git CRLF synthetic regression fixture records the entire
  test checkout with autocrlf disabled before demanding a clean source tree;
  worktree cleanliness protections remain enabled.
- [x] Source `f8035736936614548f3adc8f88b176cb5481dffa`
  passed **541 tests** on Linux Python 3.12 and 3.13 (four skipped each), plus
  Windows unsigned portable executable/GUI startup in public CI
  [38495755717](https://github.com/magicmantheace/AthenZ/actions/runs/38495755717).
- [ ] The complete Windows/Linux Python 3.11 regression run
  [38495761979](https://github.com/magicmantheace/AthenZ/actions/runs/38495761979)
  must finish separately before full native CI can be marked successful.
- [ ] Real owner-device WAV/model accuracy, native CTranslate2/RTX 3060 CUDA
  support and voice accessibility still need supervised acceptance.

### 2026-10-13 — Offline private speech quality measurement

- [x] Implement explicit `athenz-voice evaluate ... --reference ... --confirm`
  to compare local native faster-whisper transcripts to owner-authored ground
  truth entirely in memory; return only aggregate normalized WER/CER, edit
  counts, and consent/privacy flags. No automatic chat or storage.
- [x] Implement `athenz-voice score-text --reference ... --hypothesis ... --confirm`
  for native-free, network-free comparison of existing owner-selected text
  transcripts. Unicode NFKC/case-folding/punctuation rules are documented.
- [x] Private UTF-8 reference/hypothesis files use bounded no-follow regular
  file reads, hardlink checks and stability rereads; malformed references are
  refused **before** launching optional native speech inference.
- [x] Synthetic CI source `69227ea9cb8b04be93446ef68d073e3800d09e0d`
  passed 550 Python regression tests each on Linux Python 3.12 and 3.13
  (four skipped each) and unsigned Windows portable startup/GUI checks in
  [run 38501677826](https://github.com/magicmantheace/AthenZ/actions/runs/38501677826).
- [ ] Full Linux/Windows Python 3.11 regression run
  [38501687005](https://github.com/magicmantheace/AthenZ/actions/runs/38501687005),
  actual reference-labelled WAV data, installed native faster-whisper model
  CPU/CUDA behavior, human review and accessible UI remain separately unverified.

### 2026-10-13 — Voice WER/CER final regression checkpoint

- [x] An empty *hypothesis* UTF-8 file is a valid speech failure with full
  deletion error, not a filesystem/input-format error; empty owner reference
  remains disallowed. Synthetic race-mutation fixtures accept the same
  bounded reader flags as production code.
- [x] Source `1ede7cad603b95fa5fd2c859c07d3ebb082c35e3` passed
  **551 tests each** on Linux Python 3.12/3.13 (four skips each), and passed
  Windows unsigned portable executable/Tk startup in public CI
  [38502224799](https://github.com/magicmantheace/AthenZ/actions/runs/38502224799).
- [ ] Complete Python 3.11 Linux/Windows regression for this source in
  [38502233185](https://github.com/magicmantheace/AthenZ/actions/runs/38502233185)
  must be separately confirmed. Real faster-whisper accuracy, CPU/CUDA
  behavior, owner-device latency, audio accessibility and owner-reviewed
  ground-truth corpus are not verified by public synthetic tests.


### 2026-10-14 — v0.7 repeated held-out scenario preflight

- [x] Reject punctuation/Unicode-equivalent duplicates and strong lexical
  near-duplicates within a selected approved calibration/test batch before
  any local model inference.
- [x] Include private-text-free `selected_cases_independent` in read-only
  held-out preflight, reject biased comparisons/report saves and recheck
  before accepting an inference result.
- [ ] Test semantic/paraphrase independence and real owner-chosen scenarios
  without contaminating train/calibration/test partitions; synthetic CI
  checks do not validate true independence or improved behavior.

### 2026-10-14 — v0.7 learning-cycle readiness bridge

- [x] Aggregate-only `athenz-training learning-plan`: evaluates consent-reviewed
  training source counts, calibration/test lexical distinctness, protected
  reference cleanliness and an optional existing immutable SFT snapshot.
- [x] Detects in-process source drift and emits a bounded owner next-step
  category without running a model, training, exporting data, changing
  inference routing or authorizing deployment.
- [x] Synthetic regression coverage for empty/clean/conflicting/revoked
  training, incomplete or modified snapshot, held-out duplication, concurrent
  source drift, input bounds and sensitive-text exclusion.
- [ ] Complete a real baseline → owner-reviewed examples → CUDA training →
  candidate → held-out evaluation → explicit rollback/promotion exercise on
  the owner's target PC. Offline readiness is **not** evidence of learning.

### 2026-10-14 — Held-out population freshness (increment)

- [x] Compare and review-save stages bind new reports to the original
  requested case limit **and entire approved calibration/test population**,
  catching new evidence outside the scored window.
- [x] Keep previous report schemas readable but do not misrepresent legacy
  evidence as newly population-verified; synthetic forgery and midflight
  mutation tests added.
- [ ] Measure model improvements with a real, owner-reviewed distribution of
  independently sampled decisions and an explicit rollback benchmark.
