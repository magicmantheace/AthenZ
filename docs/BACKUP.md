# Explicit local SQLite profile backups (experimental v0.6)

AthenZ has **private, unencrypted SQLite-only** snapshot support. Backups
contain sensitive personal information and are **not encrypted**. They are
never pushed to GitHub, uploaded to cloud storage, copied outside the private
AthenZ folder, restored into a live database, or created automatically.

In the Desktop **Setup** tab, press **Back up private SQLite…** and confirm
the plaintext-storage warning, then **Verify latest backup**. Use the CLI for
specific snapshots:

```sh
athenz-backup create --confirm
athenz-backup list
athenz-backup verify <32-character-backup-id>
athenz-backup delete <32-character-backup-id> --confirm
```

The snapshots are created under `ATHENZ_HOME/backups` (by default
`~/.athenz/backups`) as a consistent SQLite backup via the SQLite online backup
API, even while the source database uses WAL. Each unique snapshot gets a
SHA-256 and a private metadata manifest recording the snapshot size and schema.
Verification checks exact bytes, manifest status and SQLite integrity without
writing to the backup. The source database remains in place.

Only the `identity.sqlite3` database is included. It contains memory,
conversations, training approval records, checkpoints and other private SQLite
records; **datasets, converted models, adapter weights, reviewed patches,
original conversation-file exports and their backups are not included**.
There is deliberately **no auto-restore** command. Do not try to replace a
live SQLite database by copying files while AthenZ is running. Recovering from
a backup requires a dedicated, owner-reviewed offline restoration workflow
which has not yet been implemented.

Backups are not sent to a cloud account by AthenZ, but other tools such as
OneDrive and OS backup systems may sync the private folder depending on your
configuration. Protect access to backups, delete obsolete copies and account
for copies on other media. A checksum detects accidental/local changes; it
is not a cryptographic signature against a malicious local actor who can edit
both files. This is **not encrypted cloud backup or a complete disaster
recovery solution**.

## Offline recovery into a new profile (v0.6)

A reviewed backup can be **recovered into a new, absent directory**. This is
not an in-place restore and cannot overwrite your existing profile:

```sh
athenz-backup verify <32-character-backup-id>
athenz-backup restore-new <32-character-backup-id> \
  --destination /path/to/new-empty-profile --confirm
# Carefully inspect the recovered profile before explicitly switching ATHENZ_HOME.
```

The destination's parent must exist and be outside a Git checkout and the
original AthenZ home. The destination itself **must not exist**. Recovery
rechecks the snapshot checksum, copies it without overwriting any files and
writes `recovery.json` showing original and post-recovery database checksums.
The live profile, its backups and its SQLite WAL remain untouched.

For safety, recovered scheduler jobs are **paused and disarmed**, existing
in-flight leases are cleared, any active Ollama candidate-routing preference
is removed and running checkpoints are paused. A restored checkpoint is
historical information, not permission to resume its worktree. The external
Git worktrees are not copied; do not attempt to resume old tasks without a
new owner review. The original snapshot is left unchanged for audit.

This currently restores **SQLite records only**: reviewed memory, feedback,
conversation text, decisions, metadata and checkpoints. It does **not**
restore private training JSONL, model adapters, datasets, GGUFs, referenced
base weights, exported reviews, or local Ollama model installations. These
external artifacts must be separately verified/reconstructed before model
training or candidate activation. The recovered database contains sensitive
plaintext, and a restored directory is **not automatically made active**.

## Explicit temporary SQLite restore rehearsal

`athenz-rehearse-backup BACKUP_ID --confirm` verifies an existing local
SQLite-only snapshot, checks free scratch disk space, restores into a brand-new
private temporary folder outside the active profile and all Git checkouts,
checks integrity and that stale scheduler leases, running checkpoints, and
active model routing have been disarmed, then removes the recovered copy.
The command does not run automatically, switch the active profile, access
Ollama, deploy models, or contact GitHub. `--scratch EXISTING_TRUSTED_DIR`
selects a trusted local scratch parent. The rehearsal refuses snapshots over
2 GiB or insufficient temporary disk space (approximately 2x snapshot size
plus 32 MiB). Explicit `--confirm` is mandatory.

The temporary data is **plaintext**; deletion is not secure erasure. The
backend may touch source SQLite WAL/SHM state while reading the snapshot.
This is *not* a complete profile-bundle or installed-model recovery test,
Windows/RTX 3060 validation, or independent release certification.

### Backup manifest input hardening

Both SQLite-only and selected-profile bundle verification refuse malformed
outer JSON types, boolean lengths/schema values and invalid SHA-256 fields
before attempting to trust their recorded snapshot metadata. An unreadable,
non-object or tampered manifest produces a sanitized local `BackupError`;
raw attacker-controlled JSON, paths and private records are not returned in
CLI errors. These structural checks add resilience against corruption; they
are **not** signatures and cannot authenticate metadata rewritten by an
attacker who controls the whole private directory.

Selected-profile bundle restoration and the opt-in temporary rehearsal are
documented in [Profile Bundles](PROFILE_BUNDLES.md). The older SQLite-only
rehearsal remains supported and does not activate restored profiles.
