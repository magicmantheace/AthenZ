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

## Source-completeness preflight before full regression or wheel builds

Run `python -m tools.source_inventory --root .` to check that every Python
source/test file from the pinned archival baseline is present as a real local
file, without contacting GitHub. `tools/local_validation.py --mode full`,
`--mode wheel`, and `--mode all` now refuse an incomplete source checkout **before**
starting a test or build. The `policy` mode remains usable on an incomplete
checkout for checking the manual-only workflow rules.

The inventory is a **path-only completeness** check anchored to archival
commit `550eee10f3a0f9d530cb9424ba6b7ed18e5516c4`; it covers all 109 Python/package/test paths present
in that checkout (including later-added recovery, cancellation and privacy
regression modules) and permits edited and
new development files. It does **not** verify file bytes, trust, GitHub freshness,
model weights, full behavior, or real PC hardware. Regenerate and review its
expected path list if the project's source tree changes substantially. The
runner returns `source_inventory_complete` separately from
`source_content_verified: false` to prevent an unsupported attestation claim.

## Running focused tests from an incomplete local reconstruction

When the source-inventory preflight reports missing files, a *full* regression
pass or release wheel is **not verified**. You can still run individual existing
local test modules in a fresh temporary private profile without cloud CI:

    python -m tools.local_validation --mode focused --test tests.test_profile_health
    python -m tools.local_validation --mode focused --test tests.test_release_readiness --test tests.test_ci_budget

Only safe `tests.test_*` module names (up to 12 per run) are accepted; no shell
commands, arbitrary import strings, remote fetches, or non-test files. This is
not a subprocess sandbox for untrusted tests and a focused pass must never be
misreported as the complete regression suite. The policy audit always runs
before invoking tests, and no GitHub Actions are invoked.

## Provisional testing on an incomplete local source checkout

When the GitHub archive's full file inventory cannot be reconstructed locally,
use `python -m tools.local_validation --mode available` to execute *all currently
present* test modules without claiming a complete regression suite. On POSIX
with `xvfb-run` installed this uses a fresh virtual display, including when a
stale `DISPLAY` environment variable exists. The JSON report includes
`source_files_missing`, `virtual_display_used`,
`source_inventory_complete` and `release_gate_passed`. A successful
provisional test run is **not** a release gate or a complete source verification.
Full and wheel modes still refuse incomplete source trees. No GitHub Actions
are invoked by this command, but locally reviewed tests are not an OS sandbox.


## Public-repository GitHub Actions validation (2026-10-12)

The repository has been verified **public**. The owner subsequently authorized
use of standard public GitHub-hosted Actions for development validation. This
supersedes the earlier blanket prohibition on cloud test runs **only for public
standard runners**; the restriction against unexpectedly triggering workflows
on `main` and against uploading private profile data remains in force.

Validation is triggered by commits to isolated `ci/public-runner-validation-*`
and `ci/public-packaging-validation-*` branches. Their workflows pin
`actions/checkout` to the exact commit to test on the archival source branch,
use read-only `contents` permission and disable persisted checkout credentials.
These CI-only workflows are not copied to `main` or the archival source branch;
neither branch's prior automatic-trigger policy changes. Linux Python
3.11/3.12/3.13 and an unsigned Windows portable build/GUI smoke now have hosted
passing evidence. No physical target-PC or GPU validation is implied.

Evidence: [regression Linux + Windows run 38331720210](https://github.com/magicmantheace/AthenZ/actions/runs/38331720210)
and [additional Linux Python matrix + Windows portable build run 38331854750](https://github.com/magicmantheace/AthenZ/actions/runs/38331854750).
The unsigned portable artifact is retained only seven days and is not a
signed release or a trusted installer. GitHub Actions does not reveal or certify
any local owner profile or production hardware.

### Hosted Docker and latest source coverage

On 2026-10-12 the owner-approved public-runner Docker test was invoked from
an isolated `ci/` branch with read-only checkout pinned to source commit
`be8cf5b93a396b4737bf145e6896d7cac8b9eb66`. Run
[38332727303](https://github.com/magicmantheace/AthenZ/actions/runs/38332727303)
passed seven real-Docker integration/sandbox threat tests with a registry
SHA-256-addressed image. No model inference or owner private files were used.
Run [38332502198](https://github.com/magicmantheace/AthenZ/actions/runs/38332502198)
passed Linux Python 3.12/3.13 regression and unsigned Windows portable
smokes against the same source; run 38332623888 passed Linux Python 3.11.
These tests are hosted evidence only, not independent container isolation
certification or acceptance on the owner's hardware.

### Public hosted v0.7 benchmark review suite

Validated source commit `9b423813bfba6039e45be113d8155683da77b668`
includes strengthened held-out train/calibration/test partition checks,
private gold-rationale SFT exclusion, O(tokens) indexed protected-phrase
lookup, paired candidate evaluation arithmetic, and owner-review-time stale
report rejection. Hosted runs 38334418348 and 38334386292 validate the
Linux 3.11/3.12/3.13 433-test suites and unsigned Windows portable smoke.
Run 38334418348 additionally checks the Windows Python 3.11 full suite;
read its individual job result before claiming a Windows regression pass.
All CI-only branches check out the immutable implementation SHA; `main`
remains untouched and no private identity data is uploaded.

### Latest isolated public CI source (adapter/LoRA integrity)

Public runners check out pinned archival source, never the default branch.
After previous Linux and Windows 433-test baselines, the development sequence
introduced immutable adapter registration digest anchors, checkpoint-fenced
training and strong lexical near-duplicate exclusion. The most recent
implementation source is `2b7c1110623588f86e18493d1aee06258ff1b292`.
The Python 3.12/3.13 and Windows portable runner is
[38341100306](https://github.com/magicmantheace/AthenZ/actions/runs/38341100306).
This is hosted synthetic/packaging evidence only and cannot certify real
CUDA training, independent lineage or the owner's desktop.

### Pinned public CI evidence for final 2026-10-12 implementation

Source `2b7c1110623588f86e18493d1aee06258ff1b292` (archival development)
was checked out by isolated CI workflows without editing `main`. Linux
Python 3.11/3.12/3.13 ran 447 synthetic tests each with four skips and no
failures. Windows portable packaging and executable/GUI smoke passed.
Actual digest-pinned Docker integration and sandbox tests passed all seven
cases in run 38341307100. Public job references: 38341284972,
38341100306, 38341307100. Hosted runners have no access to the owner's
local memory database or RTX 3060. The Windows full-suite job result remains
separate until it completes and is independently inspected.

### 2026-10-12 — Latest owner-readiness development CI

Implementation `4089049c402701b832919a0768449db9a7615427` includes opt-in
synthetic CUDA compute, separately reported Ollama synthetic instruction
following and read-only release-observation history. Public Actions
[38343154083](https://github.com/magicmantheace/AthenZ/actions/runs/38343154083)
passed Linux Python 3.11 (460 tests, four skips), and
[38343157982](https://github.com/magicmantheace/AthenZ/actions/runs/38343157982)
passed Linux Python 3.12/3.13 (460 tests each, four skips), plus unsigned
Windows portable packaging and startup smoke. A prior Windows test-cleanup
failure from synthetic SQLite handles was fixed before this source; full
Windows 3.11 regression on the pinned source is tracked separately in run
38343154083 and must be verified before declaring that job green. The
separate actual Docker integration job
[38343274127](https://github.com/magicmantheace/AthenZ/actions/runs/38343274127)
passed seven tests. The public CI runner never sees owner profiles or tests
native RTX 3060 hardware; no automatic model training is initiated.
