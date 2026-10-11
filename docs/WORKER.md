# v0.4 supervised worktree worker (initial slice)

`athenz-worker` creates *detached disposable Git worktrees* under the private
`ATHENZ_HOME/worktrees` directory, not inside your original working copy. This
is **working tree separation, not execution isolation**. Use only local
repositories you have already trusted. Git checkout may invoke configured
filters: do not use on attacker-controlled repositories.

## Example workflow

```sh
athenz-worker start fix1 /path/to/clean/repository "Fix the arithmetic in calc.py"
athenz-worker show fix1
athenz-worker propose fix1 calc.py --model qwen3.5:2b
athenz-worker diff fix1
athenz-worker apply fix1 --confirm
athenz-worker syntax fix1
athenz-worker diff fix1
# Optional, only if Docker installed and the image was pre-pulled + trusted:
athenz-worker test fix1 --image python@sha256:<trusted-64-char-digest> --confirm
athenz-worker cleanup fix1 --discard-changes
```

A task can be resumed after process restart with `show` / `diff` / `syntax`.
Only a single proposal per checkpoint is supported in this first slice. You
may apply reviewed replacements; there is no commit, push, merge, GitHub write,
filesystem-wide autonomous agent, or background scheduler here. Worktree
removal defaults to *refusing dirty workspaces* unless `--discard-changes` is
explicit. Cleanup retains the private metadata checkpoint as complete.

The `syntax` command uses `ast.parse`, which **does not execute** the candidate
project. Success only shows that changed Python files parse; it does not mean
tests pass or that a patch solves the request. Evidence is stored in the
existing private ledger with a new record requiring human review.

For runtime tests, the Docker runner is optional and **fails closed** if Docker
is unavailable. The container starts without network access, privileges,
additional capabilities, or a writable root; it mounts the worktree read-only
and uses resource caps. The image MUST already be available locally, be
explicitly selected, and be pinned by SHA-256. Containers are not a guarantee
against all kernel/container vulnerabilities; use a dedicated sandbox VM for
untrusted repositories. The repo can contain secrets even without .env files;
inspect it before mounting. Windows users should run Docker with a Linux
container backend. Docker runner is not yet verified on the target PC.

This first stage does not meet all of issue #9's autonomy and trust-boundary
requirements. Next: an explicit multi-step controller, retry budgeting,
trusted test attestation, safe immutable snapshotting, cancellation, and
Windows/WSL2 integration validation.

## Manual bounded retries and cancellation

`athenz-worker retry fix1 --confirm` reverts a previously applied patch (or
removes an unapplied proposal), verifies that the disposable tree is clean,
and permits another proposal. The default budget is **three retries** per
task. If undo is interrupted before the checkpoint update, retry can recover
from the already-undone proposal state. It does not itself ask the model to
retry or run any code. `athenz-worker cancel fix1 --discard-changes` ends a
task and explicitly discards the isolated worktree; `show` will no longer
resume it. A completed checkpoint retains only private task metadata.

## Private review handoff (new)

Once an explicitly reviewed proposal has been applied, use:

```sh
athenz-worker syntax fix1
athenz-worker export-review fix1 --confirm
```

`export-review` verifies that **only the approved tracked files** differ from
HEAD and that every changed file still matches its approved SHA-256. It writes
an immutable `*.patch` under the private `ATHENZ_HOME/reviews` directory,
never under the repository. A SHA-256 digest, selected paths, base commit and
latest matching verification level are saved in the private task checkpoint.
Untracked files, staged changes and surprise modifications block export.

Verification levels are *not-verified*, *syntax-only*, or
*container-tests-observed*. The latter records the exit code observed from the
configured Docker runner; it is not a cryptographically independent attestation
of arbitrary code safety or functional correctness. Recheck patches and rerun
trusted tests before merging them into a project. No Git commit, push, merge or
remote action is performed.

The exported patch survives worktree cleanup and can be applied manually with
`git apply --check /path/to/patch` followed by `git apply /path/to/patch` after
review. Do not export a patch to an untrusted destination or Git repository;
private source fragments may be present in it.

## Container timeout and procedural learning restrictions

A Python syntax check is useful but **cannot** be approved as a proven
procedural lesson. Historical syntax-only lessons are also excluded from
retrieval. A behavioral test result and explicit human approval are required
for that memory path; model descriptions alone remain insufficient evidence.

Docker test containers are assigned random names. If `docker run` times out,
AthenZ attempts `docker rm -f <name>` with a separate bounded timeout.
If the Docker daemon does not confirm removal, the run is recorded as failed
and **cleanup UNCONFIRMED**; inspect your Docker daemon manually. Killing a
Docker CLI process alone is not proof its container stopped. This timeout path
is unit-tested with a simulated Docker client, but has not yet been validated
on the owner's Windows/WSL2 machine.

## Legacy proposal API: no host-side Python execution

The older `athenz code-test --kind compile` command now parses the edited
Python files with `ast.parse` instead of launching `python -m py_compile` in
an untrusted repository directory. Its result is **syntax-only evidence** and
cannot become a verified procedural lesson. The old `--kind unittest` path
has been removed from the legacy command: use `athenz-worker test` with the
explicit digest-pinned Docker image and review confirmation instead. Existing
stored `python -m py_compile` evidence is excluded from procedural retrieval.

## Windows path and original-line-ending integrity

Git for Windows can report a registered worktree with forward slashes while Python's Windows `Path` prints backslashes. Registration checks now compare normalized absolute paths, rather than raw strings. File-scoped proposals and undo use an exact-newline UTF-8 reader: original CRLF bytes are preserved across apply/undo so a cancelled or retried change does not leave a Git working tree dirty. This is covered by synthetic CRLF round-trip regression tests on Linux and a Windows Python 3.11 CI job. Windows CI checks do not replace real WSL2/Docker validation on the owner's PC.
