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

## Full-sequence behavior check (new, owner-invoked)

Once all stages have been `advance`d, a pinned Docker image can run the
**entire final combined source tree**, rather than testing just one stage:

```sh
athenz-sequence test fix-math --image python@sha256:<verified-image-digest> --confirm
athenz-sequence export fix-math --confirm
```

The sequence runner copies the Git-tracked tree to a short-lived private
snapshot, rejects symlinks and known credential filenames, and mounts that
snapshot read-only. It then launches a fixed unittest discovery command in a
network-disabled, non-root, resource-capped Docker container. Neither the
model nor source files can select a shell command, new file scope, or image.
No Docker means **no test**, not an unsafe host-side fallback. Docker images
must be trusted, already local, and explicitly pinned by digest. Choose
images that contain the dependencies your tests need. Windows/WSL2 is not yet
validated.

A local observation record stores the pinned image, snapshot SHA-256, output
fingerprint, exit status, cleanup result, and local test-run reference under
`ATHENZ_HOME`. After a passing run the combined private patch export may say
`container-tests-observed`; on failure it says `container-tests-failed`.
This is **locally observed evidence, not independently authenticated execution
attestation or proof of correctness**. Evidence cannot enter the personality
model without deliberate human review. This controller still does not commit,
push, publish, or run in the background.

## Controlled local Git handoff

After a **passing** owner-invoked container test and a complete review export,
copy its `sha256` and run:

```sh
athenz-sequence publish-local fix-math --sha256 <exact-exported-patch-hash> --confirm
```

Only the exact reviewed paths are written into a **temporary Git index**, and
Git objects are created locally from the approved byte content. The command
creates a brand-new `athenz/<task>-<hash>` local Git branch without moving the
original repository's HEAD, staging anything in its checkout, or pushing. It
requires an exact patch digest and an observed passing Docker result; syntax
parsing alone is insufficient. Repository hooks are disabled, and the operation
never accepts model-supplied commands or remote addresses. The source Git
configuration itself must already be trusted.

The ref is created atomically only if absent. If an earlier invocation was
interrupted after ref creation, repeating the command verifies the local
branch's tree and base commit before completing the private checkpoint. If a
branch already exists with different content, publication refuses to replace
it. Review and push/cherry-pick manually when you choose. Cancellation removes
the disposable worktree but intentionally **does not delete the local branch**.

## Snapshot integrity, hostile path testing, and real Docker CI

`isolated_unittest` rejects private snapshot directories with commas, newlines,
carriage returns, or NUL bytes before constructing Docker's comma-delimited
`--mount` syntax. It hashes every copied file **again** immediately after the
container returns; unexpected files, symlinks, size changes, or modified file
bytes invalidate a passing result (`returncode=125`). A pre-run fingerprint
check also refuses a copy changed during preparation. The snapshot is still
owned by the local host user, so this is drift detection rather than
independent remote attestation, and it cannot defeat an attacker who changes
files and restores the original bytes between hash checks.

The opt-in `tests/test_docker_integration.py` exercises actual Linux Docker with
passing and failing unit-test fixtures, read-only snapshot mounts, and source
isolation. A separate GitHub Actions workflow resolves a Python image to its
immutable registry digest, runs both tests on an Ubuntu runner, and verifies
Docker behavior beyond mocks. CI evidence here applies to that Linux runner,
not the owner's Windows/WSL2 installation. `ATHENZ_INTEGRATION_DOCKER=1` and
`ATHENZ_TEST_IMAGE=<trusted image@sha256:...>` allow an owner to run it locally.

The sandbox still does not establish independent execution attestation. Source
repositories must already be trusted; containers share the host kernel.
