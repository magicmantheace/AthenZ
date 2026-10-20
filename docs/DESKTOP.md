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

## Twin-first conversation and evidence inspection (2026-10-20)

The **Chat** tab opens in **Twin** mode by default. The owner can still
explicitly switch to Agent Mode; both histories remain independent.

Enter a Twin question and choose **Preview Twin evidence** to inspect the
*actual serialized, bounded and approved* reference profile that would be
supplied to the local model. The private read-only dialog shows evidence
types, provenance and selected excerpts without opening Ollama, updating
memory, sending messages or examining unreviewed session history.

- A positive evidence-status label means topically matched approved reference
  *was packed into the model prompt*; it does **not** prove that the reference
  answers the question or that model output will be true.
- Missing, pending, revoked, held-out and too-large omitted references do
  not appear as approved personal facts. A question with no packed topical
  personal references is explicitly marked insufficient.
- The preview is a point-in-time owner-local view, not a lock. Source review,
  model routing or chat content may change before the owner actually sends.
  The normal chat pipeline rechecks changes before persisting generated turns.
- When Twin Mode uses recent session history, that **unreviewed conversation**
  is separately labeled and is not shown in this approved-only preview.

The preview's synthetic tests verify selection and consent separation.
**No Windows GUI validation, owner personality comparison or model-quality
measurement is implied by committing these changes.**

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

**Coding tasks:** Supervised worktree patches require exact-digest owner approval, bounded syntax checking and optional confirmed Docker tests. The paused-by-default proposal queue can prepare one explicitly armed stage, but cannot apply it, commit, push or deploy.

## Limits and acceptance testing

- This is an early native desktop shell, not a polished installer or tray app.
- Headless CI covers service/database/privacy behavior. A packaged Windows GUI
  smoke now opens and closes the real four-tab window on a disposable profile;
  it still cannot prove HiDPI usability, screen-reader support or Ollama performance.
- Tkinter must be included in the local Python distribution, and a graphical
  session is required. Linux headless CI does not launch a window.
- Private memory currently uses SQLite permissions, not OS keychain-backed
  encryption; review data stays on this local screen.
- Keyboard navigation, first-run guidance, supervised approvals, queue
  pause/recovery and unsigned portable Windows builds exist. Streaming
  responses, native accessibility acceptance and a signed installer remain future work.

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

## Setup and Windows portable build (v0.6)

The **Setup** tab provides optional local readiness checks. Nothing is probed
at launch: **Check prerequisites** reports Python, Tcl/Tk, Git and Docker
availability in sanitized form. **Probe Ollama (loopback only)** explicitly
issues a `GET /api/version` request using the proxy-disabled,
redirect-refusing HTTP transport. **Probe NVIDIA VRAM…** requires a separate
confirmation dialog before running the read-only `nvidia-smi` inventory. Only
GPU count and approximate VRAM totals appear: no GPU serial numbers, UUIDs,
model names, process output, or personal records. The three diagnostic buttons
have separate permissions; allowing Ollama to be probed never authorizes a GPU
query, and merely opening Setup never contacts either. Backup operations are
on their own row for keyboard navigation and narrow screens. Availability
does not verify CUDA, actual Docker execution, inference, or QLoRA feasibility.
Checks are descriptive and never grant execution permissions.

A Windows-only GitHub Actions job builds an **unsigned portable onedir ZIP**
with PyInstaller and runs an offline packaged `--self-test` using a disposable
profile. It is not an installer, does not create a Windows startup entry, does
not publish to GitHub Releases, and does not sign the binary. See
[WINDOWS_PORTABLE.md](WINDOWS_PORTABLE.md) for limitations and instructions.

## Manual SQLite profile backups

The **Setup** tab also has owner-initiated **Back up private SQLite…** and
**Verify latest backup** actions, executed on separate UI worker threads.
Backups are consistent, SHA-256-checked, remain inside the private home and
are **unencrypted**. No backup happens automatically, and restoring a backup
into a live database is deliberately unsupported. These snapshots do **not**
include adapter/model/dataset files. See [BACKUP.md](BACKUP.md).

## Keyboard navigation (v0.6)

The desktop supports **Ctrl+1**, **Ctrl+2**, **Ctrl+3** and **Ctrl+4** to focus Chat, Review memory, Coding tasks and Setup respectively. **Ctrl+L** returns focus to the chat input. Tk notebook's **Ctrl+Tab** and **Ctrl+Shift+Tab** navigate tabs. The message input continues to use Enter to send when focused. These shortcuts **only change focus or tabs**, never approve data, arm the scheduler, run commands or submit coding patches. The review dialog still requires explicit confirmation.

For a temporary, non-persistent GUI startup check, run `athenz-desktop --gui-self-test` (or the portable `AthenZ.exe --gui-self-test`). It opens the real four-tab window briefly using an automatically deleted profile, then exits. This checks Tk creation and event-loop startup, **not native accessibility, usable HiDPI scaling, model inference or your real private profile**. For an entirely windowless startup check use `--self-test`.

## Text scaling and scrollable reviews (v0.6)

Use **Ctrl+Plus** (or **Ctrl+Equals**) and **Ctrl+Minus** to increase/decrease
desktop text size, or **Ctrl+0** to reset. The range is bounded from **80% to
200%**, affects Tk's standard named UI fonts and review-table row heights, and
resets when the desktop closes. This preference is session-only; it never
changes the private profile, training data, scheduler permissions or Windows
system settings. The chat transcript, pending memory list and Setup results
have vertical scrollbars so long records remain navigable with a keyboard or
mouse. Ctrl+1–4, Ctrl+L and explicit review confirmations remain separate.

This improves keyboard usability but **does not certify screen-reader support,
Windows HiDPI behavior, font rendering or accessibility conformance**. Native
testing on the target Windows machine remains necessary before release.

## Offline first-run guidance

Setup initially shows a read-only **Getting started** checklist. The same guide
can be reopened using the Getting started button, or printed with
`athenz-onboarding` (`--json` for structured public-only metadata).
Viewing the guide neither probes Ollama/GPU nor authorizes model, memory,
scheduler, coding, backup or training operations. See
[ONBOARDING.md](ONBOARDING.md) for the precise privacy and hardware limitations.

## Owner-controlled reply discard (experimental)

While a chat response is pending, **Cancel reply** requests that AthenZ discard
the generated response before storing it. If cancellation wins the commit race,
neither the user's message nor a partial assistant reply is added to the private
conversation. The pending draft remains in the input field for manual retry.

Cancellation is **cooperative**: it does not terminate an in-flight Ollama HTTP
request, free GPU memory immediately, or guarantee that a response already
committed can be undone. The button remains disabled until a worker finishes.
The feature never changes approved memory, scheduler permissions, code patches
or model weights. Synthetic concurrency and atomic-turn tests are included;
real Windows/Ollama integration testing is still outstanding.

Closing the desktop while a reply is generating also requests discard before the
model worker stores its response. Closing the window does not forcibly terminate
Ollama, and a reply committed before the close cannot be retroactively revoked.
A virtual-display integration test exercises this behavior with a synthetic
in-flight model request and ensures no conversation was persisted.
