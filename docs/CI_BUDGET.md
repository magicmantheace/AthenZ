# GitHub Actions usage containment — offline review patch

**Historical emergency budget policy (superseded for approved public runners):**
The temporary prohibition below applied before the owner's 2026-10-12
authorization. The currently approved isolated public-runner process is
documented under [Public-repository GitHub Actions validation](#public-repository-github-actions-validation-2026-10-12).
Do not turn on automatic Actions triggers in the archive or in `main`
as part of this consolidation.

**Original budget emergency rule: do not run, rerun, or automatically trigger GitHub Actions.**
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

### 2026-10-12 — v0.7 held-out preflight and provenance increment

Pinned implementation `1def9ba7d983fc617575f62b8ad3341499cb513a`
adds model-tag freshness checks on benchmark save, consistent Wilson/invalid
predictions/chance estimates, local acceptance-history consistency and a
read-only held-out case preflight. Public GitHub Actions Linux Python
3.11/3.12/3.13 passed 471 tests (four skips each) on runs
38346880275 and 38346862618. The latter run also passed Windows unsigned
portable packaging and executable/GUI startup smoke. Native Windows full
regression for the same commit runs separately in 38346880275; do not
mistake a still-running job for a platform pass. No private owner profile,
credentials or installed model weights were uploaded to the public CI runner.

### Public hosted CI — complete batch preflight and recovery privacy increment

The CI-only branches check out exact source SHA
`59b594e3c00773ce7c96c97b79c338009f697463`; `main` remains unchanged.
The full 492-test Linux Python 3.11/3.12/3.13 runs passed (four skips each),
and the unsigned Windows portable ZIP, executable self-test and Tk GUI startup
smoke passed. Evidence: [full Linux/Windows matrix
38348235713](https://github.com/magicmantheace/AthenZ/actions/runs/38348235713)
and [portable/compatibility matrix
38348241604](https://github.com/magicmantheace/AthenZ/actions/runs/38348241604).
Seven digest-pinned real Docker isolation tests passed in
[38348270920](https://github.com/magicmantheace/AthenZ/actions/runs/38348270920).
Windows Python 3.11's longer full-suite job belongs to the first run and
must have a completed success conclusion before claiming that full platform
regression passed. Hosted runners contain only synthetic profiles; actual
RTX 3060 CUDA/WSL2/owner Ollama is still unverified.

### Selected-profile bundle recovery rehearsal (final implementation)

Pinned source `cffd2005a7db6a32a0e822fee5dffde8d8540e9b` adds disposable
full-profile restoration rehearsal and strict backup sidecar JSON validation.
The corrected recovery assertion verifies an intentionally disarmed SQLite
snapshot against the **post-restoration** SHA, with non-SQLite private assets
compared byte-for-byte to the ZIP manifest. Public Python 3.12 and 3.13
completed 500 tests with four skips each and no failure in
[38351342271](https://github.com/magicmantheace/AthenZ/actions/runs/38351342271).
That run also passed unsigned Windows portable packaging and Tk GUI startup.
The full Linux/Windows Python 3.11 run
[38351334337](https://github.com/magicmantheace/AthenZ/actions/runs/38351334337)
and real Docker sandbox run
[38351452118](https://github.com/magicmantheace/AthenZ/actions/runs/38351452118)
are independent evidence; their success must be checked rather than assumed.
All hosted inputs are synthetic and contain no owner private records, models,
archive material, passwords or environment identifiers.

### 2026-10-13 — Isolated per-task Docker and owner conversion pause

Development source commit `7d739ba3669b06466a9cc7e03609a53a3c2861e6`
is checked out by standalone public hosted workflows rather than merging to
`main`. Linux Python 3.12 and 3.13 in public Actions
[38417310918](https://github.com/magicmantheace/AthenZ/actions/runs/38417310918)
passed the 514-test suite, four skips per platform. The job also performs
Windows unsigned portable executable and Tk startup tests. The separate
full Linux Python 3.11/Windows Python 3.11 run is
[38417320334](https://github.com/magicmantheace/AthenZ/actions/runs/38417320334).
Always verify the hosted workflow's final conclusion before claiming a Windows
full-suite or packaged-build pass. Actual owner-machine Docker and GGUF model
conversion are not verified by these synthetic hosted tests. No private owner
databases, code checkouts, or model weights are copied into the Git repository.

### 2026-10-13 — No-follow source snapshots and checkpoint-fenced Docker tests

Source `f98513308e66530528591c7ac80ef1fd80cf6a64` is tested by public
pinned-source workflows, with `main` unchanged. Python 3.12 and 3.13 hosted
Linux suites ran 520 synthetic unittests each (four skips, zero failures)
and Windows unsigned portable package and GUI startup passed in
[38421476754](https://github.com/magicmantheace/AthenZ/actions/runs/38421476754).

Full Linux/Windows Python 3.11:
[38421489833](https://github.com/magicmantheace/AthenZ/actions/runs/38421489833).
Actual Docker isolation:
[38421636859](https://github.com/magicmantheace/AthenZ/actions/runs/38421636859).
These independent runs must be checked for a completed success conclusion;
queued/in-progress jobs never establish acceptance. Tests contain synthetic
Git repositories and deliberately fake owner profiles only. No credentials,
private memories, model weights or owner documents are committed or copied
to public runners.

### 2026-10-13 — Offline voice CLI acceptance

Development source `72d64897f648fa73891cdf819c9c1827bdd9f55c` adds an
entirely opt-in, file-based offline speech-to-text CLI and synthetic local
speech tests. The optional native `faster-whisper` package is never imported
in ordinary chat, desktop startup or model-readiness probes. Audio, model
weights, transcribed words and owner profile files are not uploaded to public
Actions. Public [Python 3.12/3.13 and Windows portable CI
38439435495](https://github.com/magicmantheace/AthenZ/actions/runs/38439435495)
and [full Linux/Windows Python 3.11 run
38439447654](https://github.com/magicmantheace/AthenZ/actions/runs/38439447654)
check the pinned source using synthetic generated PCM WAV and mocked model
segments. Run conclusions must be verified independently; native hardware
voice support and runtime package compatibility remain unverified.

### 2026-10-13 — Voice stability and no-model-load inventory acceptance

Pinned implementation `f8035736936614548f3adc8f88b176cb5481dffa`
adds no-follow selected WAV metadata inspection, local speech-model stability
checks and a native-free `athenz-voice inspect-model` command. Synthetic
[Python 3.12/3.13 + Windows portable
38495755717](https://github.com/magicmantheace/AthenZ/actions/runs/38495755717)
**completed successfully**: Linux Python 3.12 and 3.13 both ran 541 tests
with four skips each, no failures/errors; the unsigned Windows portable app
also passed packaging, executable self-test and GUI startup smoke. Full
[Linux/Windows Python 3.11 run
38495761979](https://github.com/magicmantheace/AthenZ/actions/runs/38495761979)
is a separate longer regression and requires a completed success conclusion.
All tests use synthetic WAVs and fake local inference; no owner audio, trained
weights, secrets or private SQLite files were uploaded.

### 2026-10-13 — Private speech metric evaluation

Pinned development source `69227ea9cb8b04be93446ef68d073e3800d09e0d`
contains owner-confirmed offline WAV/reference and text/text numeric WER/CER
scoring, no returned private text and no persistence of model replies, plus
synthetic reference-race and privacy tests. Public compatible matrix
[38501677826](https://github.com/magicmantheace/AthenZ/actions/runs/38501677826)
completed SUCCESS: 550 synthetic tests each on Linux Python 3.12 and 3.13
(four skips), and a Windows unsigned portable package and Tk startup smoke.
Full Linux/Windows Python 3.11 regression
[38501687005](https://github.com/magicmantheace/AthenZ/actions/runs/38501687005)
is distinct and must have a completed success conclusion before being
reported green. Hosted tests have fake model output and synthetic text, not
actual owner voice/audio or NVIDIA hardware; no private transcript or model
weights were committed.

### Voice scoring edge-case acceptance — 2026-10-13

Public source SHA `1ede7cad603b95fa5fd2c859c07d3ebb082c35e3`
passed 551 synthetic unit tests on both hosted Linux Python 3.12 and 3.13
(four skipped each) and passed the Windows unsigned portable app and GUI
startup checks in [workflow 38502224799](https://github.com/magicmantheace/AthenZ/actions/runs/38502224799).
An empty owner-hypothesis `.txt` scores as complete deletion instead of
creating a bogus denominator or printing private audio. The full Python
3.11 Windows/Linux matrix is separately tracked in
[38502233185](https://github.com/magicmantheace/AthenZ/actions/runs/38502233185).
This evidence does not involve or certify any real owner audio, native
faster-whisper accuracy, RTX 3060, microphone device or model training.
