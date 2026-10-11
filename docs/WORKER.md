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
