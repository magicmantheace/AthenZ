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
- If the process terminates before recording completion, the persistent
  `running` lease prevents a second scheduler from replaying the call.
  **First ensure the old worker is no longer running.** Then explicitly use
  `athenz-scheduler recover TASK --confirm`. Recovery examines the sequence
  checkpoint; it does not contact the model or approve any code.
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
