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

## Offline validation runner (added in archival development)

Use a **reviewed local checkout** and run from its root. None of these
commands dispatches GitHub Actions or invokes GitHub's API:

```sh
python -m tools.local_validation --mode policy
python -m tools.local_validation --mode full --timeout 300
python -m tools.local_validation --mode wheel
python -m tools.local_validation --mode all --timeout 300
```

The runner first rejects any automatic Actions event in the checked-out
workflow files, then runs a hard-coded validation command. Full mode runs
unittest discovery. Wheel mode stages a temporary copy of the package, then
uses `pip wheel --no-index --no-deps --no-build-isolation` without modifying
tracked source. Every run uses a disposable `ATHENZ_HOME`, bounded step
timeouts, and reports a clear pass/fail summary. Failed checks abort subsequent
steps. The wheel command requires preinstalled build dependencies.

**Not a sandbox:** local source and unit tests are trusted code. They might
have network capabilities of their own; `PIP_NO_INDEX=1` prevents index
package downloads but does not isolate Python processes from the network.
The runner is not an attestation of Windows GUI/CUDA behavior, and it never
checks GitHub billing. Keep feature pushes on non-triggering archive refs
until the manual-only workflows are in force on `main` and the owner approves
resuming cloud validation.
