# Development integration status (2026-10-13, America/Edmonton)

This branch is an **integration candidate**, not a stable Windows installer or
a release tag. It begins at archival source `233047ee528c969636dc820326268ef7a2164f00`
and preserves its history while applying release-readiness consistency fixes
and correcting stale public status documentation.

## Branch roles

- `main` (`5d7e5b8ef3eca602dee0f9ac2ad85aac7761d255`) is the older
  v0.6 alpha desktop baseline. Do not discard it or force-push it.
- `archive/manual-ci-budget-2026-10-12` is the long-running implementation
  history, including early v0.7 held-out evaluation and v0.8 offline voice.
- `integration/archival-v06-v08-review-20261013` is the reviewable forward
  reconciliation candidate. It must not be reported as merged until a
  deliberate main-branch merge occurs.

## Functional increments carried forward

1. Approved memory and contradiction-review flows, held-out evaluation
   preflights and privacy-sensitive prompt checks.
2. Supervised worktree/Docker test snapshots, private-file exclusions,
   transaction/revision fencing and interruption recovery.
3. Local-only diagnostics, release acceptance, backup/profile restore
   rehearsals, and portable Windows integrity/staging.
4. Owner-initiated existing-WAV faster-whisper transcription and numeric
   WER/CER comparison; no continuous recording, auto-chat or model promotion.

## Validation boundaries

Archived pinned source `1ede7cad603b95fa5fd2c859c07d3ebb082c35e3`
passed the public Linux Python 3.11 / Windows Python 3.11 regression at
[run 38502233185](https://github.com/magicmantheace/AthenZ/actions/runs/38502233185),
and Linux Python 3.12/3.13 (551 tests each, four skips each) plus an unsigned
Windows portable executable and GUI startup smoke at
[run 38502224799](https://github.com/magicmantheace/AthenZ/actions/runs/38502224799).
Those runs validated the pinned source, **not** this branch's newer changes.

The archive's head only adds documentation to that pinned source. This
integration candidate includes additional code and regression tests; it
requires its **own** source-pinned validation before merge.

GitHub-hosted synthetic/packaging tests are not target-hardware acceptance.
Actual Windows HiDPI/accessibility, RTX 3060 CUDA/QLoRA, WSL2 Docker,
locally installed speech-model fidelity, backup-and-rollback, signed
publisher identity and real user-data consent tests remain incomplete.

## Before considering a merge

1. Inspect the full diff against `main`; avoid exposing private memory,
   model corpora, credentials and personal profile artifacts in public Git.
2. Check that the isolated public-runner validation pinned to this exact
   integration commit passes, including Windows compatibility and packaging.
3. Confirm `.github/workflows/` in this branch remains **manual-only**.
   Do not accidentally re-enable paid automatic push/PR workflows.
4. Independently decide whether and when to merge; keep `main` history and
   provide an explicit rollback point. Never present the source-only merge
   as a certified binary or verified local model-training release.
