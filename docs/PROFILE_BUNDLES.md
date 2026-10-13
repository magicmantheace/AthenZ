# Selected private profile bundles (experimental v0.6)

This workflow packages a **consistent SQLite snapshot** and a bounded selection
of private AthenZ artifact files into a local, **unencrypted ZIP**. It is
opt-in and intended for owner-controlled recovery and relocation; no files are
uploaded, pushed to Git or automatically activated. This is not an online
synchronization service, an encrypted vault, or an atomic snapshot of every
mutable directory. Never share the ZIP or its manifest without reviewing it.

## Include / exclude

Included are `identity.sqlite3` (consistent SQLite online-backup copy) and
ordinary files under the **explicit allowlist** `datasets/`, `evaluations/`,
`reviews/`, `runs/`, `conversions/`, and `ollama-imports/`. These may contain
personal prompts, complete messages, model weights, or other sensitive data.

Not included: Git `worktrees/`, container `snapshots/`, previous `backups/`,
`bundles/`, arbitrary home contents, base-model files stored elsewhere,
installed Ollama model images, external repositories, and operating-system
settings. The restored SQLite records may contain historical absolute paths
that no longer exist; training/model work must be revalidated by the owner.

Symlinks, hard-linked files, invalid Windows names and case collisions are
refused. Limits: up to 5,000 files, 2 GiB each, 16 GiB total, and no ZIP
compression. The operation **fails closed** if the selected private artifacts
are too large or mutate while being read. If any authorized files change after
the SQLite snapshot, a new bundle may not reflect an atomic single moment;
pause training and editing before creating a bundle.

## Explicit workflow

```sh
athenz-profile create --confirm
athenz-profile list
athenz-profile verify <32-hex-bundle-id>
athenz-profile restore-new <32-hex-bundle-id> \
  --destination /path/to/brand-new-profile --confirm
```

`athenz-desktop` also offers **Bundle selected private files…** and **Verify
latest bundle** in the Setup tab. The desktop does **not** offer one-click
restoration into a running profile; restore is deliberately an offline CLI
operation with explicit destination and confirmation.

The restored destination must not exist, must be outside the original AthenZ
profile and Git checkouts, and must have an existing safe parent. ZIP entries
are allowlisted and fingerprint-verified again during extraction. Recovery
saves a `recovery.json` provenance record and **disarms scheduler jobs, clears
all leases and removes active Ollama routing** in the restored database.
Nothing is automatically deployed, scheduled or started. The source profile
is never replaced or deleted. You must intentionally select the new profile
later (for example `ATHENZ_HOME=/path/to/new-profile`) after inspecting its
contents and reconciling any missing external files.

Integrity checks (SHA-256 per file, ZIP digest and SQLite integrity) detect
accidental changes, but **are not cryptographic signatures** against a local
attacker who can edit the entire bundle and sidecar. Windows filesystem
permissions are only best-effort. Windows desktop/HiDPI, actual GPU training,
Ollama weight conversion, and end-to-end target-PC disaster recovery remain
unverified. Keep an independently encrypted backup in a secure location if
you need protection from a stolen drive; AthenZ does not manage that encryption.

### Malformed private bundle manifest handling

Bundle verification validates the internal manifest's object structure and
each listed path/hash type before case-insensitive collision checking.
Invalid entry metadata, malformed root objects and non-integer byte lengths
fail with a sanitized `BackupError` rather than an unexpected attribute or
sort error. Synthetic tests deliberately modify an archive and update its
*unsigned* outer sidecar checksum; they verify internal validation rather
than treating a rehashed archive as trusted proof. Bundle integrity is still
SHA-256 identity, not a signature, encryption or authentication against an
attacker with full access to both archive and sidecar.

### Read-only plaintext backup scope inspection

```powershell
athenz-profile inspect
```

Without creating a database, archive or any file, this shows only aggregate
counts and observed byte sizes of the explicit private artifact scope. It
excludes worktrees, existing backups, releases, Ollama model files and the
separate `release-acceptance.sqlite3` database (old hardware acceptance
observations must not silently transfer to a new recovered installation).
It refuses symlinked, hard-linked, unsafe or oversize selected files and
unsafe private profile roots. The size is only an estimate: the eventual
SQLite consistent snapshot and selected files may change before the user
explicitly runs `create --confirm`. The ZIP remains **plaintext**; the
inspection grants no authorization to create, restore or share it.

## Supervised full-profile recovery rehearsal

```sh
athenz-rehearse-backup <bundle-id> --bundle --confirm
# Optional: --scratch /existing/private/scratch-directory
```

The `--bundle` option restores a **verified plaintext selected-profile ZIP**
into a freshly created, disposable local scratch profile, checks its SQLite
integrity, verifies every recovered dataset/review/adapter file against the
original ZIP manifest, and independently confirms that scheduler leases,
running checkpoints and model-routing pointers are disarmed. It then deletes
the temporary recovered copy. It never selects the recovered profile, deploys
weights, starts Ollama, or modifies an existing destination. The scratch
location must be an existing safe directory outside the live profile and any
Git checkout with sufficient disk space; private plaintext temporarily exists
there during the explicit rehearsal. Reports contain only counts and booleans,
not private names, records, local paths or model contents. This is a recovery
rehearsal, not encrypted backup or independent model provenance.

A restore failure inside the temporary bundle rehearsal returns a fixed
local error, not an underlying operating-system exception that may contain
private paths, prompts or artifact filenames. The independently re-read ZIP
manifest is bounded before parsing and must remain structurally valid. A
failure in the rehearsal never authorizes activating the temporary recovery.
