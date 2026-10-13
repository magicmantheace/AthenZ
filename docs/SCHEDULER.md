# AthenZ v0.6 — supervised local proposal scheduler (experimental)

**OFF by default.** The scheduler is opt-in and operates only on existing
owner-created `athenz-sequence` coding tasks. A queued entry is created **paused**.
A human must arm *each* stage, then explicitly launch `tick` or a bounded,
foreground `serve`. The scheduler can request **one proposal** from a
loopback-only Ollama model. It **cannot** accept a patch, run tests, advance a
stage, write/push Git commits, approve memories, train models or deploy models.

## Example: explicitly arm one stage

```sh
# Create scope first via the desktop Tasks tab or athenz-sequence start.
athenz-scheduler add fix-math --model qwen3.5:2b --confirm
athenz-scheduler show fix-math             # initially paused
athenz-scheduler arm fix-math --confirm    # grants ONE proposal request
athenz-scheduler tick --confirm            # local Ollama inference; stops for review
athenz-sequence review fix-math            # inspect FULL diff and exact SHA-256
# Apply/check/advance must still be approved manually via UI or sequence CLI.
# When the next stage is ready, re-arm with explicit authorization:
athenz-scheduler arm fix-math --confirm
athenz-scheduler pause fix-math
```

For a limited polling session, explicitly start `athenz-scheduler serve --confirm
--ticks 10 --interval 30` in a **foreground terminal**. Polling does nothing
if no tasks are armed. It never installs a service, starts on login or reboots,
or automatically re-arms tasks. `--ticks` is limited to 1–120 and `--interval`
to 5–3600 seconds. Closing the terminal stops the scheduler (except for an
already running model request which may finish before it is terminated).

The **desktop Coding tasks tab** exposes Queue (paused), Arm next stage, Pause,
Run queued once, Recover stopped job, and Remove queue. Merely opening the
window never starts scheduling or inference. The queue stores owner-selected
model tag, authorized task/repository/worktree/stage fingerprint and lease in
private `ATHENZ_HOME/identity.sqlite3` metadata. This is **not independently
attested authorization**; access to the private SQLite database remains a
trusted-local-user boundary.

## Failure and concurrency policy

- A queue request is atomically leased in SQLite so two competing scheduler
  processes cannot simultaneously claim that same armed job.
- Any model failure leaves it **paused**. No implicit retry or auto-apply.
- A successful request becomes **review**, and the owner must examine the
  full patch and approve its exact SHA-256 using normal sequence controls.
- If the owner pauses while inference is in flight, the request may still
  finish at the Ollama server, but a lease check under the SQLite proposal-write
  lock discards its output if the pause committed first. No proposal or
  checkpoint is created. The owner must explicitly re-arm to request another
  proposal. A pause observed before sending the request also prevents the
  outbound model call. Pausing cannot forcibly interrupt an active HTTP request.
- Proposal insertion and sequence transition to `awaiting_review` now share
  one lease-fenced SQLite transaction. A failed checkpoint rolls back the
  proposal instead of leaving an orphan reviewable record. The same atomic
  checkpoint boundary now covers owner-invoked foreground sequence proposals;
  a changed checkpoint or dirty worktree during generation refuses persistence.
  A pause after that transaction commits preserves the already-reviewable
  proposal but the queue reports paused and does not automatically retry.
- If the process terminates before recording completion, the persistent
  `running` lease prevents a second scheduler from replaying the call.
  **First ensure the old worker is no longer running.** Then explicitly use
  `athenz-scheduler recover TASK --confirm`. Recovery examines the sequence
  checkpoint; it does not contact the model or approve any code.
  Recovery checks the existing lease and authorized scope before any sequence
  repair, then refuses to clear the lease if another process replaced it while
  recovery was underway. The owner still must stop the old worker first.
- Any unexpected worktree edits or changes to the originally authorized task,
  repository, base commit, worktree or stage scopes block inference.
- To remove a queue entry without deleting reviewed code or worktrees, pause
  the entry and run `athenz-scheduler remove TASK --confirm`. A job still
  running or holding an unreconciled lease cannot be removed.

## Important limitations

This is a *bounded polling supervisor*, not a cloud automation service or an
unattended software-engineering agent. It cannot forcibly cancel an
in-flight Ollama request; a deliberate pause revokes its permission to save a
proposal if the pause completes before proposal persistence. The `recover` command trusts the owner's
confirmation that a previous worker has fully stopped; it is not a cross-host
lease-fencing mechanism. The task controller remains restricted to an already
trusted local Git checkout, and worktrees are **not a security sandbox**.

Synthetic tests cover queue authorization, concurrency, crash recovery,
pausing mid-inference, replay avoidance, tampering and stage-by-stage review.
Actual Windows desktop, Ollama inference and WSL2 Docker tests on the owner's
hardware remain unverified.

### Sanitized supervised proposal failures

A model-generation or scope-validation exception is never returned verbatim
to the desktop, CLI or persisted queue status. Only fixed categories
(`authorization-or-scope-revoked` or `local-proposal-failed`) are displayed;
raw exception messages might include private prompts, file paths, model output
or other untrusted strings. The queue still pauses with no automatic retry,
patch application, testing or deployment. Foreground polling also rejects
boolean values masquerading as integer tick or delay bounds.

### Supervised Git/Docker runner diagnostics

Local Git failures now return a fixed, sanitized error instead of forwarding
Git stdout/stderr, which may contain private source paths, repository names or
local configuration. Owner-invoked container tests reject Docker mount-path
option delimiters and invalid timeout settings before invoking Docker.
Snapshot integrity failure reports contain a fixed public-safe category
instead of a raw exception, and the command continues to refuse a successful
result on unverified or changed snapshots. This is stronger input handling,
not a claim that a worktree is an OS-level adversarial-code sandbox.

Repository coding prompts and copied Docker source snapshots now share a
conservative secret-path policy. In addition to exact names, it blocks
`.env.*`, `credentials.*`, `secrets.*`, common private-key extensions,
local SQLite files and well-known credential directories. Files with multiple
hard links are refused to avoid directly importing a separate local private
file through a tracked or selected alias. These are only filename and local
filesystem controls, **not** content scanners or proof that code cannot
contain an embedded credential. No automatic tests, commits or pushes are
unlocked by these checks.

### Bounded copy instead of live worktree Docker mount

Owner-triggered per-task container testing now reuses AthenZ's stricter,
digest-pinned, snapshot-based Docker runner. It copies only Git-tracked,
regular, non-hardlinked and non-sensitive source files into a disposable
read-only snapshot, verifies the copied bytes before **and after** container
execution, and then removes the snapshot. It never bind-mounts the live
worktree, which could contain untracked private files and Git metadata.
The test result remains a local observation rather than a cryptographic
attestation; Docker and filesystem isolation require owner-device verification.
The runner still uses a fixed unittest command with no host fallback.

### Stable source handles and private snapshot filenames

The Docker snapshot copier now opens regular source files with no-follow
semantics where supported, checks the opened inode against its named path,
rejects hard links and oversized files, and rechecks file metadata after the
read. The post-test snapshot verifier uses the same checks. Tracked Git paths
with control characters or excessive length are refused before copying or
reporting private names. This hardens common file-replacement races; a fully
malicious process controlling ancestor directories or the same operating
system account is **not** an independently isolated attacker model.

### Evidence tied to the current source and owner checkpoint

After Docker exits, the isolated runner hashes the copied snapshot and takes
a second bounded, private tracked-file snapshot of the current checkout.
If either the tested bytes or current source has changed, the result is
`125` (integrity failure), never a passing test. Owner-invoked per-task
verification also rechecks the checkpoint revision, proposal ID and applied
status before recording test evidence. If the owner superseded the task during
Docker execution, the late test result is discarded. This is not a defense
against an adversary with the ability to edit the host between both checks.

Multi-stage coding verification additionally compares the full task sequence
and its checkpoint revision after Docker returns, before writing behavioral
evidence. A concurrent owner scope edit, cancellation or superseding revision
refuses the late result even if its copied source remains unchanged. The final
checkpoint save is still revision-fenced; public tests simulate owner updates
during an isolated test without executing untrusted code on the host.

### Exact CRLF/LF patch fingerprints on Windows

The multistage controller now derives baseline, current-workspace and syntax
checks through the same raw-newline UTF-8 reader used by the review/undo patch
engine. Windows text-mode newline conversion previously could compare a CRLF
patch's exact stored SHA-256 against a normalized LF in-memory copy and reject
a valid owner-approved edit. New synthetic review/apply/validate tests cover
original CRLF source and CRLF replacement without silently changing bytes.
