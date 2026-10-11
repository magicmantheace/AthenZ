# v0.4 review-gated coding controller (experimental)

This adds a **foreground** controller to the supervised worktree worker. It does
not autonomously run programs, commit, push, deploy, access network services,
or change the underlying LLM. All plans are explanatory text; only the owner
can choose existing files and authorize specific replacement bytes.

## Example

```sh
athenz-controller start calcfix /path/to/trusted/clean/git/repository 'Correct add() and sub()'
athenz-controller plan calcfix calc.py util.py --model qwen3.5:2b
athenz-controller prepare calcfix --model qwen3.5:2b
athenz-controller review calcfix
# Inspect the diff, then copy the displayed SHA-256:
athenz-controller apply calcfix --sha256 <exact-review-hash> --confirm
athenz-controller syntax calcfix
# If syntax fails, edits are undone inside the disposable worktree and the
# controller moves to retry_needed. Run `prepare`, review a NEW hash, then apply.
athenz-controller export calcfix --confirm
athenz-controller show calcfix
athenz-controller cancel calcfix --discard-changes
```

The planner is local-Ollama-backed, but its 2–5 description steps are **not**
authority for reading, writing or executing anything. The exact 1–4 permitted
existing files come from the owner's arguments. Preparations are proposal-only.
The `apply` command requires both `--confirm` and a matching SHA-256 of the full
proposed replacement contents; editing the proposal invalidates prior approval.
The original repository is never edited by these commands.

`syntax` parses changed Python sources with `ast.parse` **without executing**
the project. On failure, the controller automatically undoes the isolated patch
and records a bounded retry (default: 2, maximum: 3). Model-generated retries
still require human approval on each new patch. No procedural lesson from a
syntax-only result is considered verified behavior. A passing syntax result
allows creation of a private, immutable patch handoff. The handoff does not
mean the patch is correct or that unit tests passed.

Task state and syntax diagnostics are persisted in the private checkpoint DB;
crashes after a proposal, apply, failed-syntax rollback, or review-bundle export
can be recovered by rerunning the respective operation. The controller handles
**one multi-file patch per task**, not arbitrarily many simultaneous steps.

For behavioral tests, use `athenz-worker test` with an explicitly selected,
digest-pinned image and `--confirm`; the container runner remains experimental
and has not been independently verified on Windows/WSL2. The controller cannot
publish code or run trusted tests automatically. Worktrees are *not* an OS
sandbox; only use trusted local repositories, and review Docker mount contents.
