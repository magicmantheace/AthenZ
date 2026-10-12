# Manual private SQLite health observation (experimental)

Before an update or backup/recovery drill, use a **read-only** quick check:

    athenz-profile-health --confirm
    # Optional: inspect a separate trusted private directory
    athenz-profile-health --home 'C:\Users\You\.athenz' --confirm

This runs only after the owner explicitly starts it with --confirm. It reads
SQLite metadata and PRAGMA quick_check(1) in a read-only database connection;
it never runs profile migrations, creates a profile, prints personal records,
contacts Ollama or the internet, tests GPUs or Docker, or grants permissions.

The report distinguishes uninitialized profiles, unreadable databases, failed
integrity checks, and successful local quick checks. The database user-version
is a number, not a claim that the application is compatible. The local folder
and SQLite sidecars may not be symlinks; on POSIX, an existing private profile
must not be group/world accessible. A profile inside Git is rejected.

**Limitations:** A quick check is not a complete integrity or data-consistency
proof and cannot establish that model files, adapters, SQLite WAL transactions,
or backup archives can be restored. SQLite may need pre-existing WAL shared
memory files for a read-only connection, so the operation can report
`unavailable`. Only a separately confirmed, isolated recovery drill can test
restoration. Do not rely on this as publisher, Windows compatibility, or
hardware certification.

## Desktop Setup check

The **Check private SQLite health…** button in Setup is off by default and
asks for separate permission on every invocation. After approval, the same
read-only quick-check runs on a UI worker thread and displays only a fixed
status explanation, numerical SQLite schema version, and sanitized POSIX
file-permission observation. No private records, exception details, filesystem
paths or device identifiers appear in the Setup transcript.

This observation does **not** repair databases, migrate a profile, prove a
backup can be restored, read datasets, authorize scheduled tasks, contact
Ollama or grant access to personal memory. An unavailable/busy live WAL
database is reported conservatively; make and verify a separate backup.
