# Owner-reported release-readiness checklist (experimental)

AthenZ's automated Linux/Windows tests, unsigned packaging smoke and local
GPU-inventory checks are **not** proof that the application is usable on the
owner's Windows/RTX 3060/WSL2 computer. This private checklist makes those
unverified requirements explicit. It never executes a task, launches Ollama,
contacts GitHub, probes the GPU, starts Docker, approves a memory, or deploys a
model.

```sh
athenz-release-readiness plan
athenz-release-readiness status
athenz-release-readiness record windows-gui-hidpi passed --confirm
athenz-release-readiness record ollama-inference blocked --confirm
athenz-release-readiness status
# For an isolated, non-Git test profile:
athenz-release-readiness --home /trusted/private/profile status
```

The `plan` action is public static documentation. `status` is read-only and
creates no database if none exists. `record` is an **explicit owner assertion**
and stores only the check ID, `passed`/`failed`/`blocked`, the literal
`owner-reported` source and a timestamp in the private
`release-acceptance.sqlite3`. The acceptance file remains separate from the
identity/chat database and is never used as a model-training source.

The `record` action refuses locations inside a Git checkout and symlinked
private homes/databases. It does not save logs, hardware identifiers, GPU
model information, conversation content, credentials, paths, or model output.
Keep this private file on a trusted drive; like other local state, it is not
encrypted by AthenZ.

**Critical limitation:** A person can mark all checks `passed` even when the
hardware test is absent or wrong. The report therefore always says
`release_certified: false` and `hardware_independently_validated: false`, even
if all owner-reported checks passed. It never grants deployment or scheduled
execution authority. Independent validation, qualified human acceptance and
signed release engineering remain separate milestones.

## Required manual categories

1. Native Windows 11 visual / HiDPI usability.
2. Keyboard and assistive-technology accessibility.
3. Actual local Ollama Agent/Twin inference and pinned-model routing.
4. RTX 3060 CUDA/WSL2 QLoRA memory, training, adapter conversion.
5. Trust-pinned Docker sandbox behavior under WSL2.
6. Private archive backup and recovery into a new profile.
7. Windows portable side-by-side staging and manual rollback.
8. Privacy controls, memory/patch approval and consent review.
9. Authenticated signing, installation and release-update validation.

Neither a synthetic unit test nor a local status flag replaces any of these.
Do not claim a certified release before target-hardware and independent tests.

## Optional SQLite recovery rehearsal

`athenz-rehearse-backup BACKUP_ID --confirm` checks a verified SQLite
snapshot by restoring it to a disposable new profile and requiring integrity,
paused checkpoints, no active scheduler lease, and reset model routing.
It deletes the temporary restored files, but neither securely erases scratch
media nor validates external models, datasets, Windows/WSL2 hardware,
complete-profile restore, or independent release acceptance. Owner-reported
`profile-recovery` remains a distinct manual acceptance checkpoint.
See [BACKUP.md](BACKUP.md).
