# Private-profile filesystem safeguards (experimental)

AthenZ stores personal history, memory, feedback, approvals, and local
operational state in an owner-selected directory (`ATHENZ_HOME`, by default
`~/.athenz`). This information must **never** be placed inside a Git checkout.

Before it creates or opens its SQLite database, the shared `IdentityStore`
constructor now rejects:

- Paths located under a `.git` directory **or** a worktree `.git` file.
- Symlinked/junction-backed profile directories or ancestor components.
- Pre-existing symlinked/junction-backed `identity.sqlite3`, `-wal` and `-shm` paths.
- On POSIX, a private-home directory that cannot be restricted to owner-only
  permissions after the directory is created/opened.

The guard runs before SQLite is opened, and all dependent memory/feedback,
training and desktop flows inherit it. A rejected directory is not initialized.
Tests use synthetic, disposable homes and do not access the owner's data.

## Boundaries

This is a **misconfiguration and unsafe-path guard**, not a substitute for OS
filesystem security. It does not atomically lock ancestor path components
against a concurrent malicious local process, does not encrypt SQLite/WAL
files, does not protect a user who explicitly copies private files elsewhere,
and does not verify Windows ACL inheritance or a security-hardened installer.
Keep the profile outside shared folders, cloud-synced workspaces and version
control; use the separately confirmed offline backup/recovery tools.

Real Windows 11 paths, junctions, OS permissions, and upgrade compatibility
remain to be accepted on the owner's machine.
