# Sequential reviewed coding tasks (experimental v0.4)

`athenz-sequence` operates in an owner-selected, **trusted local Git repository**.
It creates a disposable worktree under `ATHENZ_HOME/worktrees`, not in the
original checkout. Worktrees isolate edits from the original checkout; they
are **not a security sandbox**. The Git repository itself must already be
trusted. The controller never commits, pushes, runs project scripts on the
host, starts a daemon, or trains a model.

## Walkthrough

```sh
athenz-sequence start fix-math /path/to/trusted/clean/repo "Repair both helpers" \
  --stage calc.py --stage util.py
athenz-sequence prepare fix-math --model qwen3.5:2b
athenz-sequence review fix-math
# Review the actual diff, and copy its printed SHA-256:
athenz-sequence apply fix-math --sha256 EXACT_REVIEW_DIGEST --confirm
athenz-sequence syntax fix-math
athenz-sequence advance fix-math
# Second stage is now available; review and approve a fresh patch:
athenz-sequence prepare fix-math
athenz-sequence review fix-math
athenz-sequence apply fix-math --sha256 SECOND_REVIEW_DIGEST --confirm
athenz-sequence syntax fix-math
athenz-sequence advance fix-math
athenz-sequence export fix-math --confirm
athenz-sequence cancel fix-math --discard-changes
```

Each stage contains 1–4 **existing Python files**. One task can contain up to
five fixed stages, specified **by the owner before any model call**. The model
is shown only the files for the active stage. Every replacement needs its own
explicit SHA-256 approval; approval from an earlier stage never transfers.
The controller checks hashes of *all* owner-authorized files and compares Git
status with expected approved changes before requesting or applying another
patch. Unexpected changes, symlinks, untracked or staged files abort that step.

After each patch, `syntax` parses all authorized Python files using `ast.parse`
without importing or executing project code. On failure, the current patch is
undone while earlier approved stages remain in the disposable worktree. The
retry budget defaults to two syntax failures per stage (max three). If a crash
interrupts rollback, `recover` completes the recorded rollback; state survives
process restarts. The controller has no autonomous retry loop: rerun `prepare`
and approve the new digest yourself.

After all stages advance, `export --confirm` writes **one immutable combined
patch** under private `ATHENZ_HOME/reviews/`, with an SHA-256 checksum and
per-stage syntax check references. The original repo remains unchanged. The
only validation level of these aggregate patches is **syntax-only**, not a
behavioral or integration test result; no lesson is considered verified on
that basis. Review the combined patch, then apply it in a *separate* trusted
checkout with `git apply --check` before `git apply`.

`cancel --discard-changes` removes the worktree; linked procedural evidence is
revoked. Without explicit `--discard-changes`, a dirty worktree is retained.
Review artifacts survive cancellation and must be deleted separately by the
owner when no longer needed. No code or personal memory is uploaded to GitHub
by the controller. Docker integration and independent execution attestation
are still outstanding and the Windows/WSL2 runtime is not yet verified.
