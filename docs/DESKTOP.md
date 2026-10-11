# AthenZ v0.6 desktop shell (experimental)

The first **foreground native desktop interface** uses Python's Tkinter/ttk
and the existing local SQLite and Ollama services. There is no browser, web
UI, background scheduler, or remote account integration. It does not download,
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
