# AthenZ portable Windows build (experimental, unsigned)

AthenZ v0.6 now has a **source-built, unsigned portable Windows directory**.
It is **not an installer**, is not code-signed, does not configure Windows startup,
and does not install Ollama, CUDA, Docker or Python system-wide. The executable
is an optional convenience for the supervised desktop shell; GitHub remains the
source of truth. Do not treat an unsigned CI artifact as a production release.

## Producing and checking the binary

The [Windows portable workflow](../.github/workflows/windows-portable.yml)
uses a Windows GitHub Actions runner and Python 3.11 to build `AthenZ.exe`
with PyInstaller `6.16.0` in **onedir** mode. It verifies the frozen process
using `AthenZ.exe --self-test` before zipping and uploading the unsigned folder.
The smoke test checks Tk/Tcl loadability and a new, disposable private SQLite
profile (including the disabled proposal queue). It does **not** run a visible
window, probe Ollama, change your normal private profile, check HiDPI, or test
the GPU, networking, model training or Docker/WSL2.

The workflow publishes a ZIP as a short-lived **GitHub Actions artifact only**
(retained for 7 days). It does not create a Release, deploy software, execute
third-party setup scripts, run `ollama pull`, or sign an executable. Prefer
artifacts from a trusted reviewed main-branch commit, not an unreviewed PR.
Builds depend on third-party PyInstaller and Windows runner packages; dependency
pinning by version is not a reproducible/supply-chain attestation.

## Running it manually

1. Inspect the GitHub workflow and corresponding source commit; download the
   **unsigned** zip from a trusted successful build's GitHub Actions page.
2. Extract the **entire** `AthenZ` directory to a location you control. Do not
   separate `AthenZ.exe` from `_internal` or other bundled files.
3. On Windows, manually start `AthenZ.exe`. Windows may warn that the unsigned
   executable has an unknown publisher: only proceed if you trust the build.
4. In the **Setup** tab press **Check prerequisites**. This reads local Python,
   Tk, Git and Docker availability without contacting Ollama. Only **Probe
   Ollama (loopback only)** requests `GET /api/version` from your configured
   local Ollama address. It sends no prompts, memories or files.
5. Do not arm a coding task unless you have deliberately reviewed its trusted
   repository, scope and approval policy. No scheduler is automatically started.

The default private profile lives at `%USERPROFILE%\.athenz`, outside the
executable folder. As with any local AI application, use a Windows account and
drive whose local data and backups you trust; AthenZ does not offer at-rest
Windows credential encryption or automated backup/restore yet.

For Python installations, `athenz-doctor` prints a sanitized readiness report.
It can explicitly check local Ollama with `athenz-doctor --probe-ollama`.
Neither command downloads software, starts a scheduled task or approves
personal data. A portable `AthenZ.exe --self-test` is intended for automated
packaging verification, not a substitute for native desktop acceptance tests.

## Remaining release requirements

Native Windows 11 GUI/HiDPI/accessibility testing, real RTX 3060 Ollama
inference, Docker under WSL2, supply-chain review, signing, installer/update
rollback and verified private backup/restore still need dedicated work.
These checks must not be marked complete solely because the Windows CI
application smoke succeeds.

### Native-window CI startup check

The Windows portable workflow now runs both `AthenZ.exe --self-test` (headless Tcl/SQLite check) and `AthenZ.exe --gui-self-test` (opens the real four-tab Tk interface against a temporary profile and exits). The GUI run has a 20-second watchdog. This is a CI-level smoke test and does not constitute a human-visible Windows 11 usability, keyboard screen-reader, HiDPI, GPU, or model-training acceptance test. Neither smoke test is permitted to send private prompts, activate models, or start work.
