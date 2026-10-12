# AthenZ v0.6 desktop shell (experimental)

The first **foreground native desktop interface** uses Python's Tkinter/ttk
and the existing local SQLite and Ollama services. There is no browser, web
UI, automatically started scheduler, or remote account integration. It does not download,
train, install, push, publish or execute repository code.

## Launch (Windows Python 3.11+)

```powershell
python -m pip install -e .
athenz-desktop
# Optional private data directory outside Git:
athenz-desktop --home "C:\Users\You\.athenz"
```

Install local Ollama and a compatible model separately before chatting.
When a reviewed Ollama tag is selected, the same digest/consent checks used by
the existing CLI are applied. Ollama HTTP is loopback-only, with proxies and
redirects disabled. The desktop does not install Ollama or models.

## Available screens

**Chat:** Choose *Agent* or *Twin*, select a named private session, send local
prompts and review persisted messages. Inference runs on a worker thread to
keep the window responsive; database connections are opened separately per
operation. Complete user/assistant turns are saved together only after a
successful response and unchanged selected model route. No incomplete model
response is silently committed. Reply feedback is owner-initiated, with any
training candidate kept pending separate approval.

**Review memory:** Lists pending identities, decisions, episodes, examples,
writing samples and procedural experiences. The preview is only a navigation
aid. Approve/reject opens the **entire private source record** first, requires
an explicit confirmation, and rechecks pending status before modifying it.
There is no automatic memory approval or model training.

**Tasks:** Read-only view of local checkpoint keys, statuses and revisions.
It intentionally provides no shell, Git, Docker, or unattended task-start
button. The separate command-line coding worker remains available.

## Limits and acceptance testing

- This is an early native desktop shell, not a polished installer or tray app.
- Headless CI tests cover service/database/privacy behavior and CLI help only;
  **they cannot prove Tkinter rendering, DPI behavior or Ollama performance**.
- Tkinter must be included in the local Python distribution, and a graphical
  session is required. Linux headless CI does not launch a window.
- Private memory currently uses SQLite permissions, not OS keychain-backed
  encryption; review data stays on this local screen.
- More refined navigation, model-download/onboarding, streaming responses,
  task approvals, pause/recovery controls, and Windows packaging are future
  v0.6/v0.9 milestones.

You do **not** need to install or test this immediately to unblock development.
We will flag hardware-specific testing when it becomes necessary.

## Supervised coding tasks (v0.6 follow-up)

The **Coding tasks** tab now exposes an explicitly owner-operated UI over the
existing `SequenceController`. There is no autonomous scheduler, Git push, or
model-controlled tool use. Open **New scoped task**, select a **trusted, clean**
local Git repository, write the task description, and enumerate existing Python
files as comma-separated stage scopes, using semicolons to separate stages:

```text
calc.py,tests/test_calc.py; util.py
```

A confirmation dialog shows the exact repository and file scopes before a
**detached, disposable Git worktree** is created. Only those files may be
sent to the local model for review-only code proposals. Worktree creation may
run trusted local Git checkout filters; a worktree is **not** an OS sandbox.
The owner must initiate each of the following actions:

1. **Prepare proposed patch** calls local Ollama in a worker thread. It does
   not apply any changes, even if the model asks it to.
2. **Review / approve patch** shows the complete unified diff and its exact
   SHA-256 fingerprint. The user must **manually enter the entire fingerprint**
   and confirm again before any file in the worktree is changed. A stale or
   modified proposal is refused. No automatic approval from chat responses.
3. **Syntax check** parses Python without executing it. A failure revokes only
   the current patch, preserving earlier approved stages and the configured
   limited retry budget. This is **not** a behavioral test.
4. **Advance stage** explicitly accepts the syntax-checked stage. Repeat
   steps 1–4 for the other owner-chosen stages.
5. **Container test** is optional after the complete sequence; the user must
   provide an **already installed and trusted, SHA-256-pinned Docker image**
   and confirm running its fixed unittest command. There is no host fallback.
6. **Export private patch** saves one immutable, reviewable combined patch
   under `ATHENZ_HOME/reviews`. This does not push, merge or commit anything.

The tab also supports **Details**, **Recover checkpoint** and **Cancel /
discard**. A dirty worktree cannot be cancelled without explicit discard
permission. Closing AthenZ does not automatically continue any coding task:
records persist, and operations can be resumed only through an explicit owner
action. Tasks originating from other AthenZ features remain listed, but cannot
be promoted into sequential coding tasks by the desktop.

Git and Docker operations run on user-invoked worker threads so the Tk window
remains responsive. Each operation opens and closes its own private SQLite
connection. Private diffs, error messages and file paths are displayed only in
the local application. The desktop does not grant the local model permission to
run shell commands, train itself, create Git commits, push to remotes, install
an adapter, or submit a PR.

### Tests and limitations

Headless synthetic integration tests cover approval-hash binding, multiple
stages, rollback, source-checkout isolation, cancelled work, resumable
checkpoints, missing Docker, and non-sequence checkpoint refusal. The native
Tk panel can be smoke-tested using an Xvfb display on Linux. These checks **do
not** validate the actual Windows HiDPI layout, clipboard interactions, GPU
inference, Windows filesystem paths or WSL2 Docker setup. A Windows/RTX 3060
hands-on release test remains necessary, but not blocking independent code
work at this stage.

**Review integrity:** Approving or rejecting a pending personal-memory item
requires its full content and provenance to match the record displayed in the
review dialog. A SHA-256 digest of the displayed record is checked within an
exclusive SQLite write transaction; if another process edits its contents or
approval status before confirmation, the UI rejects the stale review and the
owner must inspect it again. Task patch approvals use a separate digest of the
exact replacement bytes.

## Supervised proposal queue (v0.6)

The desktop Tasks panel also offers an **off-by-default** proposal queue.
Create a coding task with a fixed owner-selected file scope first, then
**Queue (paused)** and **Arm next stage**. **Run queued once** requests a
single local Ollama proposal on a worker thread; it never applies code.
**Pause queue** disables future proposals, while **Recover stopped job**
requires confirming that no prior scheduler process is still running.
**Remove queue** deletes scheduling metadata but does not delete worktrees.
No proposal is prepared merely because the window is open. To run a bounded
foreground polling loop separately, use `athenz-scheduler serve --confirm`.
See [SCHEDULER.md](SCHEDULER.md) for explicit commands and recovery cautions.

On first launch, the desktop serially initializes private SQLite migrations and
the disabled scheduling table **before** starting chat/review/task worker
threads. This avoids concurrent first-run schema creation and does not arm or
run any job. A headless regression test and Linux virtual-display startup test
exercise this fresh-profile path; native Windows rendering remains unverified.
