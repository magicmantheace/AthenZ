# GitHub Actions usage containment — offline review patch

**Current rule: do not run, rerun, or automatically trigger GitHub Actions.**
The owner's Actions allowance was exhausted. This change is archived on a
non-triggering `archive/` source branch only. GitHub `main` still contains
its prior automatic workflow triggers until a separately reviewed transition.
Do not create a pull request or update `main` while the previous triggers
remain enabled; either can trigger Actions. Git tags are not themselves a
universal Actions-off switch: workflow event filters, not naming, decide runs.

## Manual-only workflows (once authorized and merged)

- `tests.yml`: `workflow_dispatch` only. **Smoke** is the default, one Ubuntu
  Python 3.11 job. **Full** must be chosen explicitly and runs the previous
  Linux Python 3.11/3.12/3.13 and Windows Python 3.11 matrix.
- `windows-portable.yml`: only an explicitly started manual workflow can build,
  smoke-test, stage, verify and upload the unsigned Windows portable ZIP.
- `docker-integration.yml`: only an explicitly started manual workflow can pull
  a Docker image and run the real container-integration test.
- No push, PR, merge, release, cron or scheduled event triggers any workflow.
  All workflows retain `contents: read` permissions and a bounded timeout.

The owner must **explicitly authorize resuming Actions**. Updating `main`
while its old workflow is active may cause a final `push` run under the old
configuration, even if the new workflow disables pushes. Archival refs outside
`main` and `feat/**` avoid AthenZ's **currently configured** push filters,
but repository-level hooks or future workflow changes may change that.
Only publish commits to a no-trigger archival branch with no PR; do not merge
or open a PR while the allowance is exhausted.
Later, when the owner authorizes repository changes, first verify available
quota and consider temporarily disabling the three Actions workflows in the
GitHub interface before merging the replacement files. Then re-enable them as
manual workflows after the new version is on `main`. If branch protection currently requires named CI checks, moving to manual
workflows may require an owner-reviewed branch protection adjustment before
merging can resume. A manual dispatch still consumes minutes; always obtain
owner authorization for the desired checks.

## Local developer checks (no Actions minutes)

```sh
python -m unittest discover -s tests -q
python -m unittest tests.test_ci_budget -v
python tools/ci_budget.py
python -m pip wheel --no-deps --no-build-isolation . -w ./dist-wheels
```

The guard is stdlib-only and intentionally fails closed on unsupported workflow
trigger syntax. It cannot validate the owner's GitHub billing balance, protect
other repositories, or prevent a human from manually dispatching a run.
Never report a local unit test or GUI smoke as native Windows/RTX 3060/WSL2
hardware certification.

## Efficient future CI policy

Run focused local tests and a package build before requesting **one** authorized
cloud workflow. Prefer the single Linux smoke job for ordinary checkpoints.
Use full cross-platform testing before release candidates or significant
Windows changes, Docker integration only when container-sandbox code changes,
and the Windows portable build when a packaged binary is actually needed.
Never push small speculative fixes solely to watch CI fail: prepare and
consolidate them locally first, then update GitHub in one reviewed batch.
