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
