# AthenZ source consolidation and validation — 2026-10-14

**Current source of truth:** `main` at
`4d02fc7993b72815c9452269ee7595f6bae629de` (post-PR #43).
It is experimental **v0.6 alpha**, with partial **v0.7 held-out evaluation**
and **v0.8 optional offline voice** groundwork. It is not a stable release,
signed installer, independently certified model, human consciousness copy,
or fully autonomous coding agent.

## Consolidation completed

- The old `main` source `5d7e5b8ef3eca602dee0f9ac2ad85aac7761d255`
  is retained on `backup/main-pre-archival-consolidation-20261014`.
- PR [#42](https://github.com/magicmantheace/AthenZ/pull/42)
  passed public Linux 3.11/3.12/3.13 and Windows 3.11 tests plus unsigned
  packaged Windows/Tk startup checks. It hardened local release-readiness
  acceptance history and storage checks.
- PR [#43](https://github.com/magicmantheace/AthenZ/pull/43)
  passed the same five jobs, adding seven regression tests and a lexical
  within-split uniqueness gate for held-out decision evaluation.
- These fixes were merged to the archival implementation history, which was
  then **fast-forwarded** to `main` without force-push. The consolidated
  source advances the original main by 157 commits.
- Obsolete onboarding PR #41 was closed, not merged: its functionality,
  documentation and tests already exist in the consolidated implementation.

## Source-pinned validation evidence

- Release-readiness hardening source `4ddbe9a4ae4d531079b22fc82e13653c44dd72a5`:
  [five passing checks](https://github.com/magicmantheace/AthenZ/actions/runs/38505880817).
- Held-out independence source `0ae6ee8cb723eb3d1673b26436e67641ac4822df`:
  [five passing checks](https://github.com/magicmantheace/AthenZ/actions/runs/38555380534)
  (562 tests per Linux Python version; four expected skips per Linux suite;
  Windows Python 3.11 and unsigned Windows portable GUI smoke passed).
- These checks pin feature source commits before their review merge commits.
  The final merge tree carries that validated implementation; these runs
  are **not** native owner-device tests or cryptographic supply-chain proof.
- This consolidated `main` has `workflow_dispatch`-only core Python,
  Docker and portable Windows workflows. There was no new automatic `main`
  workflow run observed after the fast-forward.

## Available engineering capabilities (experimental)

Approved persistent memory, explicit contradiction review, supervised
isolated Git worktree coding and Docker snapshots, bounded proposal scheduler,
opt-in reviewed QLoRA/GGUF conversion and manual routing, selected profile
recovery, owner-only hardware diagnostics, read-only benchmark preflight and
existing-WAV offline voice transcription/scoring.

## Remaining v1.0 acceptance blockers

1. Real observed improvement over a sufficient, distinct, owner-reviewed
   held-out decision set without test leakage or biased examples.
2. Target-PC Windows 11 GUI/HiDPI/assistive technology, RTX 3060 local Ollama,
   CUDA/QLoRA, model conversion, installed model lineage and WSL2 Docker tests.
3. Signed Windows installer and authenticated upgrade/rollback,
   secure private backup lifecycle and full end-to-end recovery on owner PC.
4. Owner-controlled scheduling, stronger cancellation/fencing and approved
   longer-running task autonomy, without implicit model-granted permissions.

Git history is the source of truth. No owner profile, memory corpus, private
speech or model weights should be committed to this public repository.
