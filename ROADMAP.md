# AthenZ — Roadmap to v1.0

Mission: a local-first digital twin of the owner's preferred style and decisions,
a bounded coding assistant that learns from verified work and carefully gated
periodic model updates. It is not a literal copy of a human consciousness.

## Safety contracts
- Twin estimates owner behavior; Agent works for owner. Never invent lived history.
- Keep four distinct learning tracks: approved context, reviewed/test-backed
  AthenZ experience, Developmental AI sandbox policy/world-model adaptation
  (not yet integrated), and explicitly approved benchmark-gated local LoRA
  updates (experimental; target-device training/inference not yet validated).
- Imported chat data remains pending by default; training export only includes
  reviewed data. No private data or corpora in Git.
- **Current implementation:** explicit file scope, review and owner action precede
  any code write; there is no unattended code execution, commit, push, purchase,
  deployment or messaging.
- **Proposed pre-v1.0 task-autonomy mode (not enabled):** one explicit, revocable,
  time-limited owner grant may later authorize repeated *sandbox-only* edits and
  tests within fixed repository/worktree/path boundaries. Never infer broader
  authority from a project goal, model output, learned preference or stored memory.
  Remote push, merge, release, deployment, self-update, host/OS actions, secret
  access and outward communication require separate owner authorization.
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
| pre-v1.0 (planned task-autonomy gate) | Owner-directed, persistent, repo-scoped development work inside an isolated sandbox | Single standing grant, bounded multi-task execution, verified tests, interruption/restart recovery and no out-of-scope or unapproved external actions |
| v1.0 | Stable personalized local agent with controlled learning | Identity, coding, privacy, recoverability benchmarks met; task-autonomy mode passes its separate owner-hardware gate before shipping enabled |

## Owner-directed persistent coding autonomy — pre-v1.0 (planned)

**Priority and scope:** Preserve the current Twin-first implementation and owner
Windows/Ollama validation as the active priority. This is a future AthenZ coding
milestone, not an instruction to the current worker to switch tracks or an
implemented capability. It builds on v0.4 isolated worktree proposals and the
v0.6 owner-armed supervised queue; it does not rename those partial features
or claim that their existing manual per-stage approvals already implement it.

**Owner experience:** The owner can say once, for example, "Work on the AthenZ
repository against its roadmap." With a separately reviewed *standing task
grant*, AthenZ can inspect that repository and its issue/roadmap backlog,
select eligible improvements, plan and implement one scoped change at a time,
run tests, diagnose failures, revise the patch and continue with the next
eligible task **without another chat prompt for every step**. When blocked by
an ambiguous choice, policy boundary or exhausted budget, it must stop and
request further authorization rather than guessing. No grant means the
existing supervised/manual behavior remains the default.

### Development slices and acceptance gates

- [ ] **A1 — Read-only project planner:** inspect an explicitly selected Git
  repository, roadmap, tests and owner-approved issues; propose a bounded,
  prioritized task queue with dependencies, success criteria, risk and scope.
  Don't invent owner priorities, rewrite the roadmap or expand permitted files.
- [ ] **A2 — Narrow standing authorization:** an explicit local review grants
  a *specific* repository/worktree, task classes, allowed files, permitted
  tools and network policy, duration, resource/test/retry limits and expiry.
  Store a provenance-linked revocable grant. Default to off; never treat
  remembered preferences or the AI's own ideas as permission. Support
  immediate pause, cancellation and audit of every attempted operation.
- [ ] **A3 — Isolated execution and feedback loop:** use disposable worktrees/
  branches and a constrained runner (e.g., a pinned, policy-limited test
  container), not unrestricted host shell commands. Iterate plan → edit →
  syntax/targeted tests → broader regression → diagnose → retry with bounded
  attempts. Record actual test results and diffs, including failures; do not
  substitute model self-assessment or passing unit tests for task success.
  Prevent access to private Twin data, credentials and other repositories.
- [ ] **A4 — Durable, inspectable operations:** persist the task queue, model/
  code/permission fingerprints, stage state, output summaries and checkpoints
  across shutdowns or model changes. Verify grants, file scope and base
  revisions on resume; avoid duplicate commits or replayed side effects.
  Detect loops and stalls, enforce time/compute budgets and allow the owner
  to see what was attempted, changed, tested, blocked or left unfinished.
- [ ] **A5 — Promotion and self-development boundary:** candidate edits and
  explicitly granted *local checkpoint commits* may occur only in isolated
  branches. No unattended remote push, merge to a protected branch, release,
  package installation, deployment, update of the running AthenZ executable,
  removal of safeguards or cross-project action. Those remain separately
  reviewed owner decisions with regression and rollback checks; an update
  must not replace the currently functioning Twin on its own.
- [ ] **A6 — Owner-device acceptance:** on the intended Windows/WSL2 host,
  complete at least two independently selected eligible roadmap/issue tasks
  from one reviewed objective, including a real failing-test/debug/retest
  cycle, restart/resume and owner interrupt/revoke exercises. Produce
  reproducible passing targeted and regression tests, reviewable candidate
  diffs, truthful failure reports and zero observed out-of-scope writes or
  unauthorized push/merge/host effects. A clean blocked stop is preferable
  to violating scope; failed tasks must not be counted as completed.

**Architectural ownership:** AthenZ owns user-issued objectives, the task
controller, coding tools, permission decisions and the visible work journal.
The later Developmental AI D5 track concerns *self-selected goals and learned
motivations*, not prerequisite orchestration for owner-issued coding jobs.
Neither its integration nor Synveil is a prerequisite for this pre-v1.0
milestone. A future learning subsystem may recommend better strategies, but
must never expand AthenZ's owner-granted tool authority.

**Status (2026-10-21):** design/roadmap only. Do not change the active
Twin-first worker's implementation priority, claim continuous coding exists,
or relax current per-stage approvals before A2–A6 are implemented and tested.

## Cross-project Developmental AI integration track (added 2026-10-14)

**Architecture decision:** AthenZ is the persistent owner-facing agent and
consent/identity authority. Developmental AI is its **single adaptive learning subsystem**, not a second independent persona
or an authority over the owner's data or computer. Specializations (reasoning,
coding, speech, perception, planning, skills) are invoked as bounded
capabilities by that one agent, never as competing identities. Synveil is the
future optional local operating environment and guarded actuator host; the
AthenZ + Developmental AI combination must also run on Windows/WSL2 without it.

**Learning modes are distinct and must not be conflated:**
1. AthenZ owner-reviewed factual and autobiographical retrieval (no weight updates).
2. AthenZ evidence-backed agent episode/procedural memory with source revocation.
3. Developmental AI's *sandbox-only* experiential policy, world-model, and
   memory-control learning, with isolated checkpoints and candidate quarantine.
4. Separately consented AthenZ neural fine-tuning, held-out evaluation,
   provenance checks, explicit promotion and reversible rollback.
No simulated experience becomes a fact about the consenting person's life.

This is a **parallel dependency track**, not a renumbering of completed v0.1–v0.8
features. Its gates are prerequisite to claiming one continuously developing
v1.0 agent. Detailed contract and acceptance plan:
[docs/DEVELOPMENTAL_AI_INTEGRATION.md](docs/DEVELOPMENTAL_AI_INTEGRATION.md).
The separate access-controlled Developmental AI source-of-truth roadmap
tracks research D0–D10; this public AthenZ roadmap tracks integration.

| AthenZ target | Cross-repository dependency and acceptance gate | Status on 2026-10-14 |
| --- | --- | --- |
| v0.7 bridge / 2027 Q1 (Developmental AI D2) | Versioned local, authenticated or explicitly owner-authorized transport; typed, bounded observation/episode/action-proposal/result envelopes; schema negotiation, provenance, deduplication, replay and pause; no real action execution | Not implemented: Developmental AI has a simulation-only ledger and a draft integration contract |
| v0.7–v0.8 evaluation / 2027 Q2 (D3) | Independent held-out cross-task and shifted-distribution benchmarks; abstain on unfamiliar conditions; report success, wrong decisions, coverage, regressions and unknowns, including negative results | Not implemented: separate research experiments exist, but generalization/reliability is not established |
| v0.8 skill and memory service / 2027 Q3 (D4) | One AthenZ agent invokes reusable approved skill descriptors; sandbox demonstrations, reproducible skill tests, retrieval with rollback; no learning of extra permissions | Not implemented |
| v0.8 supervised sandbox autonomy / 2027 Q4 (D5) | Durable bounded perceive → propose goal → simulate/action proposal → feedback → learn loop, with time/compute budgets, interruption, no unreviewed physical/system acts and restart recovery | Not implemented |
| v0.9 lifelong learning / 2028 Q1 (D6) | Quarantined candidate policies; replay and forgetting checks across old/new tasks, owner approval for promotion, versioned knowledge snapshots and tested recovery after restart | Partial research components only; not an integrated lifelong learner |
| v0.9 AthenZ personal integration / 2028 Q2 (D7) | Owner-approved human history and agent-acquired experience in separate provenance namespaces; deletion/revocation propagated to derived features, lessons and candidates; one stable persona | Not implemented |
| v0.9 optional Synveil hosting / 2028 Q3 (D8) | Sandboxed typed system action proposals, Synveil policy mediation and AI-off fallback; AthenZ remains functional on Windows/WSL2 without Synveil | Not implemented |
| v1.0 long-run readiness / 2028 Q4 (D9) | At least 30 days of supervised, restartable, auditable operation with retention, drift, no-contamination, rollback, safe shutdown and privacy tests; independently held-out acceptance suite | Not implemented |
| v1.0 integrated candidate / **2029-02-09** (D10) | Demonstrate one persistent learning agent, controlled improvements and retention across tasks, consented Twin simulation, safe Agent coding, optional Synveil home and reproducible limitations | Not implemented; date is a research target, not a claim of mind transfer, consciousness or human-level ability |

**Immediate implementation order:** (1) freeze a minimum event / feedback / checkpoint
schema and a synthetic bidirectional adapter, (2) test consent and
human-vs-agent-vs-simulation provenance boundaries plus replay and revocation,
(3) connect a single sandbox lifelong-learning cycle, (4) evaluate across
unseen task families before escalating autonomy, (5) add Synveil as an
optional adapter rather than a dependency. Do not put personal examples in
either public Git repository, permit learned text to grant tools, or use
simulation checksums as user authentication.

### 2026-10-17 — D2 buffered stdio and separate-process fixture

- [x] Flush signed framed messages after full stream write, fail closed
  on short writes, flush failures or missing flush support; permanently
  invalidate sender session after uncertain delivery.
- [x] Introduce five buffered-send regression tests plus three distinct
  Python-process handshake, request/reply and synthetic-revocation tests.
- [x] Full Linux and Windows Python 3.11 suites passed: **981 tests each**
  (Linux 4 expected skips; Windows 11). All five buffered-send, three
  separate-process, 18 frame and nine pipe tests passed on both.
  [GitHub Actions evidence](https://github.com/magicmantheace/AthenZ/actions/runs/39071764990).
  One-off CI workflow removed before merge.
- [ ] A fixed-key test peer is not private Developmental AI; real peer
  attestation, credential protection, verified learning adapter and remote
  durable ACK are outstanding.

### 2026-10-18 — D2 expected reply binding before durable commit

- [x] Enforce explicitly expected event kind, task ID, source and revision
  **after** authenticated frame verification but **before** SQLite receipt
  insertion. A validly signed unrelated learner event cannot occupy a
  different task's durable sequence slot.
- [x] Preserve existing default behavior for standalone D2 receiver users
  and reject invalid expected fields without reading any stream bytes.
- [x] Add three negative regression tests for mismatched kind, task,
  revision and invalid caller-provided expectations.
- [x] [Cross-platform run](https://github.com/magicmantheace/AthenZ/actions/runs/39162538508):
  18 receiver, seven one-shot exchange and 14 signed-ACK focused tests
  passed on Linux and Windows. Full Linux Python 3.11 suite passed
  **1,020 tests (four expected skips)**. Full Windows suite was not
  rerun; only focused Windows D2 tests were executed.
- [ ] Real private Developmental AI peer validation, OS trust and
  owner consent remain release-blocking tasks.

### 2026-10-18 — D2 one-shot private-learner interface (candidate)

- [x] Add an explicitly enabled, fixed `synthetic:interop` trace-reference
  roundtrip over caller-owned binary streams: mutual-key handshake,
  request frame, two durably verified simulator reply frames, atomic
  reply-pair validation/staging and two signed ACKs after commit.
- [x] Add separately launched public test peer with per-session random
  synthetic signing/transport keys passed through binary stdin and an
  independent transactional outbox requiring both signed ACKs.
- [x] Allow durable receiver to return an authenticated event only
  after persisted metadata commit, with unchanged default return format.
- [x] Final cross-platform validation: [GitHub Actions run 39161779916](https://github.com/magicmantheace/AthenZ/actions/runs/39161779916) passed all 7 new separate-process integration tests, 15 receiver tests and 14 ACK tests on both platforms; full **1,017 Python tests** passed on Linux (4 expected skips). Windows full suite was not rerun for this change. The disposable workflow was removed before merge.
- [ ] Real private Developmental AI trace producer, safe process lifetime
  and OS identity, protected secrets, retry of aged inbound requests and
  human consent are still open.

### 2026-10-17 — D2 durable framed receiving after restart (candidate)

- [x] Add private metadata-only SQLite receiver with event-ID/digest and
  per-producer/task sequence replay fences; strict 5,000-event upper bound,
  fail-closed approval checks and no simulator/personal payload storage.
- [x] Accept legitimately aged producer-signed D2 events only inside a
  **fresh authenticated frame** with source-revision revalidation; no
  unchecked direct stale `receive(event)` pathway.
- [x] Permit `SyntheticDeliveryAck` to issue a signed receipt after this
  journal's matching durable commit, preserving the legacy journal path.
- [x] Add 15 synthetic unit tests for restart/replay, revoke, tampered
  fingerprints, bounded backlog, fixed generic messages, signed ACK and
  owner-only POSIX storage.
- [x] [GitHub Actions validation](https://github.com/magicmantheace/AthenZ/actions/runs/39078855068):
  full Python 3.11 Linux suite passed **1,010 tests (4 skipped)**;
  Windows focused 15 receiver, 14 ACK, 3 subprocess and 18 framing
  tests passed (receiver 2 expected POSIX-only skips). Removed the
  temporary CI workflow before merge.
- [ ] Windows complete 1,010-test suite, OS process peer verification and
  the real private Developmental AI adapter remain open; this is not
  real-owner consent, atomic cross-database revocation or exactly-once
  learner state updates.

### 2026-10-17 — D2 signed synthetic delivery receipt (candidate)

- [x] Add opt-in bounded ACK frames with HMAC from ephemeral negotiated
  session keys, fixed receiver, event ID, signed envelope digest, source
  revision, timestamp and strict per-session sequence.
- [x] Require receiver's prior durable metadata-journal record before
  issuing an ACK; require current synthetic source revision and exact
  outbox digest before applying one.
- [x] Test wrong keys, stale source approvals, missing/reordered receipts,
  tampered metadata, extra fields and malformed/oversized frames.
- [x] Fourteen signed-ACK tests passed on Linux and Windows, with the previous bridge and outbox tests. Complete combined-mainline Linux Python 3.11 regression passed **995 tests (4 skipped)**. [Validation run](https://github.com/magicmantheace/AthenZ/actions/runs/39072442100). Windows focused ACK, buffer and subprocess tests passed. Temporary workflow removed. Combined full Windows regression was not run for this ACK branch, but all focused tests passed there.
- [ ] Complete real process key provisioning, authoritative owner consent,
  durable receiver replay for aged events, independent ACK persistence
  and Developmental AI private adapter integration.

### 2026-10-17 — D2 caller-owned OS-pipe synthetic roundtrip (candidate)

- [x] Add strict bounded, canonical handshake records over already-open
  binary read/write streams. Explicit enable flag defaults to OFF;
  the library never launches a process or opens a network listener.
- [x] Add an OS-pipe integration fixture with two threaded participants,
  independent private grant connections, challenge-response proofs,
  signed D2 event frames and two transactional learner reply records.
- [x] Test source revoke after delivery, malformed/truncated/oversized
  handshake packets, disabled state, failed write/flush and private
  credential exclusion from hello bytes.
- [x] Nine new OS-pipe tests, 14 handshake and 18 frame tests passed on Linux and Windows. Complete Linux Python 3.11 regression passed 973 tests (4 skipped): [Actions evidence](https://github.com/magicmantheace/AthenZ/actions/runs/39060025385). No interprocess production IPC or actual Developmental AI connection is claimed from a thread test.
- [ ] Protect/provision root secrets, implement verified OS peer identity
  and the real process lifecycle, atomic ACK, restart and owner consent
  before accepting D2 end-to-end integration.

### 2026-10-17 — D2 mutual-key synthetic session handshake (candidate)

- [x] Add fresh random 128-bit client and peer challenges, mutual
  proof-of-key possession, strict schema/provenance transcript binding
  and independent HMAC-derived `athenz` and `learner` frame keys.
- [x] Connect derived session keys to the independently validated D2
  binary frame codec in synthetic integration tests; revocation
  invalidates framed delivery after the handshake.
- [x] Test forged/altered proof, wrong key, stale source revision,
  malformed and replayed challenges, and independent session derivation.
- [x] Validated against merged frame codec: 14 focused handshake tests plus 18 frame tests passed on Linux and Windows; full Linux Python 3.11 suite passed 964 tests (4 skipped). [Actions run](https://github.com/magicmantheace/AthenZ/actions/runs/39059539883). Temporary validation workflow removed. Full Windows regression of this stacked combination was not rerun, but Windows focused tests passed and previous frame/registry Windows suites were green.
- [ ] Protected per-device key provisioning, Windows/Linux OS peer identity,
  a real Developmental AI counterpart, live pipe service and authenticated
  owner consent are still unimplemented. A local shared key is not
  human identity or full D2 acceptance.

### 2026-10-17 — D2 signed synthetic stream frame codec (candidate)

- [x] Add a 4-byte bounded, canonical JSON local binary-stream frame
  format over caller-owned stdio/pipe streams; no network listener.
- [x] Double-authenticate producer event envelope and per-session delivery
  frame with separate producer-scoped 32-byte-or-longer HMAC keys.
- [x] Enforce per-producer transport sequencing, session identity, outer
  frame freshness, strict frame size, current source-revision and authority
  scope; allow signed old inner outbox events with *fresh* delivery frames.
- [x] Add fixture tests for corruption/truncation, replay/skip, wrong
  session/producer, stale clock, revocation and journal dedup.
- [x] Python 3.11 full regression passed on Linux and Windows: 950 tests each (Linux 4 skips; Windows 11 skips); 18 focused stream tests passed on each. [Actions evidence](https://github.com/magicmantheace/AthenZ/actions/runs/39058910673). Temporary CI workflow removed. Actual owner-PC pipe integration and session handshake remain pending.
- [ ] There is NO authenticated key/session negotiation, OS peer identity,
  live Developmental AI subprocess, production IPC, durable channel ACK or
  actual owner consent. This cannot close D2 acceptance yet.

### 2026-10-17 — D2 local synthetic source review CLI

- [x] Add terminal `status`, `preview`, and exact-digest-confirmed
  `review` commands for narrow synthetic grant/withdrawal actions.
- [x] Confirm no command auto-approves, opens the owner's personal-memory DB
  or converts a simulator proposal to a system action.
- [x] Run seven CLI tests on Linux and Windows, plus Linux complete regression:
  932 tests passed (4 expected skips). [Validation run](https://github.com/magicmantheace/AthenZ/actions/runs/39052962377).
- [ ] This CLI does not authenticate the human at the terminal or furnish
  secure interprocess trust. Production source approval remains open.

### 2026-10-17 — D2 private synthetic approval registry

- [x] Add standalone private, outside-Git registry for exactly scoped
  synthetic sandbox source approvals, with explicit preview/review digest,
  owner-facing `confirmed=True` and monotonic approval/revoke revisions.
- [x] Bind the durable AthenZ synthetic outbox to the registry with a
  constrained constructor; prevent queuing inside Git working trees.
- [x] Test default-deny, stale/cross-source review, persisted revocation
  across restarts, no resurrection on reapproval, POSIX privacy and
  negative unauthorized/disabled cases.
- [x] Linux and Windows Python 3.11 full suites passed: 925 tests each (Linux 4 skipped, Windows 11 skipped), and the focused source-registry and exchange tests passed. [Validation run](https://github.com/magicmantheace/AthenZ/actions/runs/39052458570); disposable workflow deleted before merge.
- [ ] Real verified owner session, identity-source consent coupling,
  separate-process authentication, atomic downstream revocation,
  authorized remote ACK and runtime learner connection remain open.
  A review digest or local confirmed flag is NOT authenticated consent.

### 2026-10-17 — D2 synthetic durable replies (implementation candidate)

- [x] Add an off-by-default transactional local synthetic request/reply
  outbox; stage one trace-ref observation and two signed, strictly generic
  learner replies in one SQLite transaction or stage nothing on failure.
- [x] Add persistent per-producer sequence counters, exact idempotent
  request retries, bounded unacknowledged backlog and replay after restart.
- [x] Re-authenticate stored envelopes and recheck the injected synthetic
  revision callback at delivery/ack time. Record AthenZ-origin source
  revocations and cancel outstanding deliveries.
- [x] Focused 18 tests and complete Python 3.11 suites passed on Linux and Windows: 910 tests each (Linux 4 expected skips, Windows 10). [Validated workflow run](https://github.com/magicmantheace/AthenZ/actions/runs/39046001711); disposable workflow removed from the branch before merge.
- [ ] Wire actual AthenZ source-consent service, private learner IPC,
  independently authenticated remote ACK and atomic downstream
  revocation. The fixture does not yet close the D2 gate.

### 2026-10-17 — D2 cross-repository synthetic wire compatibility

- [x] Pin a canonical synthetic HMAC fixture in AthenZ and the experimental
  Developmental AI integration branch; keep producer/origin, authority,
  schema fields, canonical bytes and test signatures identical.
- [x] Add three AthenZ fixture/forgery tests. Verified Windows Python 3.11
  focused compatibility tests (3 passing) and Linux 3.11 complete regression
  (892 tests, four expected skips): https://github.com/magicmantheace/AthenZ/actions/runs/39040877682.
- [ ] Developmental AI's private cross-repository adapter and trace-based
  response tests require independent execution: its first Actions run did
  not start any test steps. Do not claim paired runtime integration complete.
- [ ] Independently verify the full live bidirectional IPC, consent source
  lifecycle, trusted key provisioning and durable reply replay across restarts.

### 2026-10-17 — D2 AthenZ-side synthetic event envelope and journal (in progress)

- [x] Implement strict sandbox-only schema-one messages with distinct
  producer/origin claims, non-executable typed payloads, bounded identifiers,
  UTC event times, per-producer HMAC fixture authentication and fixed scope.
- [x] Add durable metadata-only SQLite sequence/idempotency fences,
  synthetic source-revocation guard, explicit disabled mode and injectable
  revision-matching approval callback.
- [x] Add synthetic replay, tampering, forged-origin, escalation, rejection,
  revocation, restart and privacy regression tests.
- [x] Synthetic and full Python tests passed on Linux and Windows Python 3.11: 889 tests each (Linux 4 expected skips, Windows 10). Validation: https://github.com/magicmantheace/AthenZ/actions/runs/39038760996. Temporary one-time workflow removed before merge.
- [ ] Implement compatible Developmental AI counterpart and real private
  consent-backed IPC transport, staged replay and end-to-end revocation
  of derived learner state; **D2 is not yet completed**.
- [ ] Confirm real Windows/WSL2 and Linux deployment security, source
  deletion propagation and owner-in-the-loop review.

### 2026-10-16 — Approved-memory consistency review

- [x] Implement bounded deterministic, read-only detection of duplicate
  approved-memory text and narrowly recognized opposite first-person
  preference wording, with no inference or automatic resolution.
- [x] Add CLI audit returning only candidate IDs, counts and generic reason
  types, plus desktop owner-triggered candidate list and read-only complete
  provenance comparison before existing review actions.
- [x] Refuse partial oversized scans and suppress unrelated pending/rejected
  claims; test no status, event, revision, training or prompt changes.
- [ ] Evaluate owner-labeled consistency cases (including temporal changes,
  exceptions and synonyms) on device before expanding beyond explicit
  narrow pattern hints.

### 2026-10-16 — Bounded older same-session chat continuity

- [x] Retrieve up to four older topic-matched, owner-authored excerpts
  beyond the recent 10-message window from the exact current chat/mode;
  stream session history with bounded top-K memory and bounded excerpts.
- [x] Label retrieved history as unreviewed reference data, exclude past
  assistant outputs, unrelated topics, other sessions and other modes,
  and never auto-promote historical chat into approved memory/training.
- [x] Recompute and fingerprint the assembled conversation including older
  excerpts before and after inference and under the final transactional
  persistence guard; synthetic midflight editing/deletion regression coverage.
- [ ] Verify real owner-session continuity, local inference latency, and
  measured relevance on Windows without cross-session private-data exposure.

### 2026-10-16 — Desktop conversation navigation and reviewable deletion

- [x] Show owner-only, text-free metadata for recent Agent and Twin chat
  sessions; support opening each mode's saved conversation from a dedicated
  desktop browser while preserving the existing manual session field.
- [x] Add explicit **mode-scoped** session deletion that never silently removes
  the other mode under the same name; validate a full-conversation content
  fingerprint under a SQLite write lock before removing messages.
- [x] Cascade deletion to approved/pending memories derived from deleted
  user messages, their revision history, feedback and linked training pairs.
  Refuse stale reviews, require confirmation, and bound review size.
- [ ] Verify real Windows GUI session switching and deletion of larger
  owner-private histories with recovery backups before normal daily use.

### 2026-10-16 — Owner-device local chat acceptance bridge

- [x] Add a one-command and Setup-tab **explicitly authorized** two-request
  Twin/Agent smoke using actual local Ollama inference on a disposable,
  synthetic-only approved profile and the real desktop persistence path.
- [x] Verify mode-separated user/assistant turn persistence, source prompt
  assembly, cleanup and bounded sanitized results without opening personal
  profile files or logging model output; no model download or training.
- [x] Add synthetic service tests for consent, malformed model IDs,
  report privacy, first/second inference failure and environment isolation.
- [ ] Run the smoke on the owner PC with an already installed model and
  separately test RTX 3060 acceleration, real approved-memory handling,
  Windows GUI usability, private backup/recovery and Twin predictive fidelity.

### 2026-10-16 — Desktop memory correction and revocation

- [x] List current approved personal memories in the local desktop,
  inspect the complete record and provenance, and require an owner review
  digest plus confirmation for any edit or removal.
- [x] Stage a correction as pending (old approval immediately invalid),
  revoke approval without deleting private text, or explicitly forget a
  live memory and its revision history while preserving other sources.
- [x] Use SQLite write-lock transactions to refuse concurrent record edits;
  add synthetic review, consent and stale-digest regression coverage.
- [ ] Conduct owner-device desktop usability tests and verify retention,
  private backups and review flows with real source histories.

### 2026-10-16 — Owner-reviewed chat-to-memory capture

- [x] Preview one complete user-authored local message and its session/mode
  provenance, require an owner-supplied summary pinned to that exact source
  and explicitly confirm a pending identity/style/value/preference record.
- [x] Add local CLI and desktop Review-memory workflow; no LLM extraction,
  assistant-role promotion, automatic approval or weight training.
- [x] Erase linked approved/pending personal memories and old revision text
  when the original chat message or session is removed, while preserving
  unrelated independent memories.
- [ ] Validate on owner Windows hardware, including review GUI usability,
  realistic imported chat volume and SQLite/backup data lifecycle.

### 2026-10-16 — Live Twin/Agent context integrity

- [x] Discard local chat replies whose approved evidence or exact prompt
  context changes while Ollama is generating, including memory revocation,
  edits to approved identity/decision records, and concurrent session turns.
- [x] Revalidate the owner-reviewed context under SQLite `BEGIN IMMEDIATE`
  before atomically saving the complete user+assistant turn in both terminal
  chat and desktop; no long-lived database write lock during model inference.
- [x] Keep prompts and source contents out of diagnostic errors; synthetic
  concurrency and revocation regressions cover both entrypoints.
- [ ] Validate actual simultaneous owner reviews and local inference on
  target Windows 11 hardware, including cancellation and power-loss cases.

### 2026-10-14 — Twin-first personality and relevance improvement

- [x] Select topical approved training decisions and personality evidence for
  each Twin question rather than blindly supplying the newest 20 decisions.
- [x] Include short, explicitly approved writing-style examples in Twin
  prompts, excluding pending/rejected records and Agent-only task contexts.
- [x] Use a whole-record, valid-JSON profile budget with per-category
  constraints; omit oversized items instead of truncating facts.
- [x] Preserve reference contamination protection across ALL approved
  records, including approved writing and unresolved episode disputes,
  even when a query filters those records from the current prompt.
- [ ] Full-history semantic/lexical memory retrieval beyond the current
  candidate windows, with explicit uncertainty, owner review and benchmarks.
- [ ] Demonstrate objectively improved owner-style and decision predictions
  with real, independently held-out owner examples on the target PC.

Details: [docs/TWIN_CONTEXT.md](docs/TWIN_CONTEXT.md). This is prompt
retrieval engineering, not validated personality fidelity or weight training.

### 2026-10-14 — complete approved-history Twin retrieval

- [x] Stream **all** approved identity, value, style and preference records,
  training-split decisions, and writing samples from local SQLite rather than
  dropping everything outside the latest-200 candidate windows.
- [x] Maintain fixed-size deterministic top-K heaps: source corpus size no
  longer controls memory selected for Twin or Agent prompts.
- [x] Retrieve relevant passages buried within long explicitly approved
  writing samples, without sending the whole document to the model.
- [x] Test revocation, older evidence recovery, unchanged JSON/profile
  budgets, and held-out/pending/rejected isolation beyond 200 records.
- [x] Supply a repeatable *synthetic only* offline retrieval benchmark
  with aggregate recall@prompt and privacy checks; no owner data or model calls.
- [ ] Measure retrieval latency at realistic profile sizes and independently
  measure Twin decisions and writing-style similarity on consented held-out
  owner examples (synthetic recall is not personal accuracy).

See [docs/TWIN_CONTEXT.md](docs/TWIN_CONTEXT.md).
 
### 2026-10-14 — Paired held-out Twin decision prediction

- [x] Reuse approved test/calibration decision scenarios and exact shuffled
  option order for both the Twin-personalized and unpersonalized model arms.
- [x] Preflight every held-out case for cross-split leakage, repeated cases,
  malformed options and owner-reference collisions before local inference.
- [x] Check local model identity and complete approved source fingerprints
  before and after each inference; drop results on any consent/model drift.
- [x] Return aggregate paired contingency, Twin/neutral accuracy, invalid
  predictions, chance baseline and descriptive intervals without revealing
  individual owner choices or rationales.
- [ ] Freeze independent real-owner held-out questions and report verified
  on-device Twin improvement over a no-personalization baseline.
- [x] Add opt-in explicit abstention, separate malformed responses from
  deliberate uncertainty, and report selective accuracy, coverage and an
  exact paired McNemar test with synthetic unit coverage.
- [x] Add opt-in self-reported confidence evaluation with strict numeric
  parsing, fixed-size private-only Brier/ECE aggregate counters, synthetic
  negative cases and separate calibration/test protocols.
- [x] Optional owner-reviewed semantic decision-family manifest with
  cross-split related-scenario quarantine, immutable consent snapshots and
  privacy-suppressed category comparison (synthetic evidence only).
- [x] Bind family reviews to the full approved decision record set and
  support explicit, offline review validation without model inference.
- [x] Add an opt-in held-out category-diversity gate (three reviewed
  categories, >=5 cases each, <=60% dominance) before any inference,
  plus macro-averaged Twin-vs-neutral accuracy with privacy thresholds.
- [x] Add opt-in within-case repeated decision stability over changed
  deterministic model seeds and option permutations, count semantic-option
  agreement only, and keep primary paired accuracy/stats independent.
- [x] Add a separate owner-only, consented longitudinal decision observation
  journal with dated/context-grouped comparison, bounded atomic writes and
  small-sample aggregate suppression (synthetic tests only).
- [x] Add optional owner-private frozen final-test protocol: hash all
  approved decisions/reference evidence, the selected heldout sample,
  family review, explicit local model digest, exact evaluation settings and
  directly involved code; refuse drift before/after each model response.
- [x] Add calibration-only aggregate self-reported confidence cutoff grid,
  suppress small answer groups, and bind explicit chosen cutoff into frozen
  test protocol without modifying raw paired accuracy or model behavior.
- [ ] Actually calibrate uncertainty or abstention on real owner-labelled
  data; independently validate semantic group labels, topic-family
  generalization and observed owner variability against on-device model
  predictions.

Details: [docs/TWIN_DECISION_COMPARISON.md](docs/TWIN_DECISION_COMPARISON.md).
Synthetic passing tests verify data isolation and algorithm behavior,
**not** real-person decision fidelity or model success.

### 2026-10-14 — Independent Twin writing-style evaluation groundwork

- [x] Versioned private schema v6 partitions owner-reviewed writing into
  train/calibration/test, migrating historical samples to train only.
- [x] Keep explicitly approved held-out style examples out of Twin and
  Agent prompt contexts and out of evaluation reference digests.
- [x] Offline `athenz style-readiness` counts source approvals and obvious
  normalized duplicate contamination across training/held-out splits
  without returning personal text or calling a model.
- [x] Preserve historical training evidence fingerprints and allow private
  backup/restore of the v6 database schema; regression coverage includes
  migration, consent, leakage and duplicate detection.
- [ ] Implement a blinded owner-rated local writing-style comparison on
  independently held-out tasks; produce meaningful fidelity metrics and
  intervals with explicit consent.
- [ ] Validate actual Twin style, decision accuracy and inference latency
  with the owner's real local installed model on the target PC.

Details: [docs/TWIN_STYLE_VALIDATION.md](docs/TWIN_STYLE_VALIDATION.md). Readiness
counts do not demonstrate correct style imitation or human digital continuity.

### 2026-10-14 — Blinded local Twin style preference pilot

- [x] Generate two supervised local-only responses to the same independent
  owner writing task, using the same installed model and deterministic settings:
  one neutral, one with approved Twin personalization.
- [x] Present randomized unlabeled A/B responses and collect one explicit
  owner rating (A, B or tie) before reporting which policy was preferred.
- [x] Keep withheld calibration/test writing out of *both* model prompts;
  require independent reviewed samples and reject obvious direct copy of
  withheld text into tasks.
- [x] Persist completed pair and rating in an isolated private SQLite file,
  not in AthenZ training records or public GitHub, with deletion and no
  partial results after aborted generation.
- [x] Recheck reviewed source and local model fingerprints during generation;
  mark comparisons stale and exclude them from aggregate results after
  consent or source changes.
- [ ] Collect owner judgments on truly unseen writing tasks using the actual
  local model; assess preferences, uncertainty, hallucinations, within-person
  variation and confidence intervals.
- [ ] Add a semantically leak-screened independent heldout task bank and
  external or blind adjudication before claiming quantitative Twin fidelity.

Details: [docs/TWIN_STYLE_COMPARISON.md](docs/TWIN_STYLE_COMPARISON.md).
This pilot measures owner preference only, not an authenticated personality
copy or objectively proven style match.

### 2026-10-14 — Owner-reviewed independent Twin writing task bank

- [x] Create privacy-scoped, individually owner-reviewed and explicitly
  confirmed independent writing prompts before local A/B inference.
- [x] Use only currently approved tasks, bind approvals to training and
  withheld-reference snapshots, and prevent one prompt from being counted
  more than once in a blinded evaluation.
- [x] Atomically link approved task consumption to the saved A/B pair,
  preserving the unpersonalized and Twin arm distinction privately.
- [x] Distinguish owner-rated approved task-bank cases from ad hoc,
  exploratory cases in the aggregate (never publish private writing).
- [x] Reject task or consent changes during inference, and support
  owner-confirmed deletion of a task and all its derived paired output.
- [ ] Validate independent task authoring and genuinely blind rating
  against the owner's local installed model, with enough diverse scenarios.
- [ ] Compare Twin-vs-neutral **style**, **factual integrity**, **decision
  accuracy**, and uncertainty as separate metrics before claiming fidelity.

Details: [docs/TWIN_STYLE_COMPARISON.md](docs/TWIN_STYLE_COMPARISON.md).
The reviewed task bank improves repeatability and provenance but is **not**
a psychometric assessment, semantic-contamination guarantee, or proof of
a conscious/digitally continuous self.

### 2026-10-15 — Stronger owner Twin evaluation integrity

- [x] Reject substantial lexical near-copies of either held-out style evidence
  **or approved training examples** before independent writing-task review
  and before model inference, without exporting example text or matches.
- [x] Reject reviewed style examples that closely overlap a different split,
  while keeping all approval and consent checks owner controlled.
- [x] Separate local model tag/digest cohorts in blinded style reports and
  suppress pooled win rates and intervals across differing model versions;
  continue reporting privacy-safe counts and stale/unrated records.
- [x] Add synthetic tests for Unicode normalization, long quoted passages,
  near-copy substitutions, task bank review, cross-split approval, model
  upgrades, mixed-cohort reports and stale evidence.
- [ ] Run a consented, adequately sized owner-rated pilot on the target PC.
  Include real model lineage, bias awareness and separate accuracy/abstention
  measures; never confuse preference counts with owner identity accuracy.
- [ ] Expand beyond lexical overlap to a reviewed semantic holdout audit and
  independently evaluated task diversity (still no claim of consciousness).

See [docs/TWIN_STYLE_COMPARISON.md](docs/TWIN_STYLE_COMPARISON.md).

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

### 2026-10-14 — Immutable schema-two evaluation lineage

- [x] Newly generated comparison reports require schema-two complete paired
  metrics and full held-out population; stripping fields cannot downgrade the
  evidence contract without explicit historical schema-one handling.
- [x] Downstream adapter selection and runtime review invalidate schema-two
  evaluation reports when additional held-out cases are approved.
- [x] Legacy schema-one report reading remains compatible, but cannot claim
  the new full-population freshness guarantee.

### 2026-10-14 — supervised local learning-session journal

- [x] Private, revision-fenced `session-start/status/link-run/link-report/close/cancel`
  lifecycle for reviewed dataset, separately completed and registered QLoRA
  adapter, and saved schema-two model comparison evidence.
- [x] Revalidate current consent, full held-out content fingerprint, reference
  memory and registered adapter on reads and before transitions; mark stale
  rather than silently granting model access.
- [x] Preserve unsuccessful learning attempts as comparable negative/tied
  observations. Completing a session never deploys, rolls back, trains, or
  selects a candidate.
- [ ] Prove real improved decisions and explicit runtime rollback on the
  owner's Windows/RTX 3060 machine with separately approved local inference.

### 2026-10-14 — bounded pre-training baseline milestone

- [x] New schema-two learning sessions require an owner-confirmed local
  baseline prediction benchmark before linking registered training output.
- [x] Pin the exact baseline Ollama model digest, selected held-out case IDs,
  dataset consent and complete approved case population before/after inference.
- [x] Require later candidate comparison to match baseline tag, model digest,
  selected cases and observed correct count; refuse reproducibility failures.
- [x] Preserve existing schema-one session compatibility and fail-closed
  revision fencing, no implicit model training or deployment.
- [ ] Re-run end-to-end pre-training baseline → CUDA fine-tuning → paired
  comparison → explicit rollback on owner hardware with approved real data.

### 2026-10-14 — prediction-level reproducibility and rollback preflight

- [x] New schema-three sessions keep a private per-session HMAC key and
  keyed ordered-case baseline outcomes, including errors, without storing
  prompts, answer labels or predictions.
- [x] Session-bound paired comparison verifies matching baseline predictions,
  model digests, selected evidence and checkpoint revision before saving
  a reviewed report. Equal total accuracy cannot disguise case-level drift.
- [x] Read-only rollback readiness distinguishes offline structural review
  from explicit loopback Ollama baseline digest verification, independently
  of candidate availability and without mutating model routing.
- [ ] Validate this workflow against real owner-reviewed held-out examples
  and installed models on the target Windows/RTX 3060 environment.

### 2026-10-14 — transactional local rollback rehearsal

- [x] Owner-confirmed `runtime-rehearse-rollback` verifies pinned baseline
  tag, performs harmless local smoke inference, checks model/revision drift,
  and tests the **same** SQLite checkpoint CAS used by real rollback inside
  a savepoint that is always reversed.
- [x] Synthetic regressions check that active runtime pointer and events
  remain unchanged, including failed staged writes, invalid baseline,
  disappearing candidate and locally raised private inference errors.
- [ ] Repeat rehearsal on the owner's PC against a genuinely installed local
  baseline; CI only uses synthetic model responses and disposable SQLite
  fixtures, not actual Windows/Ollama/GPU behavior.

### 2026-10-14 — cross-stage model-lineage audit

- [x] Introduce a read-only `lineage-audit` covering current adapter
  consent/registration, conversion GGUF content, owner-attested import,
  selected benchmark/reference, active runtime pointer and optional local
  Ollama digest evidence in one bounded aggregate report.
- [x] Distinguish an observed local conversion from a manual merge; no
  report can claim independent proof that GGUF contains a particular adapter.
- [x] Synthetic regression cases for complete local record chain, unreviewed
  adapter, interrupted import, GGUF mutation, imported digest mismatch,
  revoked consent, owner-attested manual merge and privacy-safe CLI output.
- [ ] Exercise real owner hardware, imported weights, end-to-end model
  improvement, and an actual consented rollback after model selection.

### 2026-10-14 — model activation lineage gate

- [x] New candidate activations require a currently completed private Ollama
  GGUF import, matching adapter/candidate tag, digest and reviewed evaluation;
  reject partial, mutated and stale import evidence before and after smoke.
- [x] Require explicit `--ack-legacy-lineage` for older selected models with
  no recorded import. Never allow the legacy flag to bypass a present but
  invalid import.
- [x] Pin local import revision and GGUF SHA-256 in new runtime checkpoints;
  fail closed on changed imported evidence during later candidate routing.
- [x] Preserve existing pre-gate runtime pointers for restoration and
  previously approved owner workflows, without claiming stronger provenance.
- [ ] Measure the cost of per-inference large-GGUF verification on owner
  hardware and optimize only with equivalent content-integrity guarantees.
