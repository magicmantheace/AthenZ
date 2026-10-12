# Offline side-by-side Windows portable staging (experimental v0.6)

The unsigned Windows ZIP is **not a signed installer**. AthenZ provides an
explicit, offline way to put a verified archive into a brand-new version folder
without uninstalling or overwriting the earlier version. It **never launches**
AthenZ, registers Windows startup, copies private data, sets a default version,
contacts a service, or changes your model/training approvals.

1. Download the ZIP from a reviewed, trusted GitHub Actions build and obtain
   its expected SHA-256 independently of the unsigned ZIP. A checksum bundled
   next to a ZIP proves neither publisher identity nor who supplied it.
2. Choose an **existing, private, trusted directory** to hold versions. Do not
   choose a shared/writable-by-strangers folder, Git checkout, or `.athenz` home.
3. Run the following using an installed Python version of AthenZ:

```powershell
athenz-stage-portable stage .\AthenZ-windows-unsigned-portable.zip 'C:\Users\YOURUSER\AthenZVersions' `
  --sha256 FULL_EXPECTED_SHA256 --name AthenZ-v0-6-preview --confirm
athenz-stage-portable verify 'C:\Users\YOURUSER\AthenZVersions\AthenZ-v0-6-preview'
```

Staging snapshots the ZIP first, validates its full SHA-256/CRC and bounded,
Windows-safe structure, then extracts *only* its safe regular file entries
into an unused version directory. Each file is hashed into a local integrity
manifest (`.athenz-stage.json`). Verification rechecks all file hashes, rejects
added/removed files and directories and symlinks, and does not execute code.
An identical stage name, including case-only changes, cannot overwrite an
existing version. A failed operation must not replace older version folders.

The result contains `AthenZ/AthenZ.exe` **inside** the named version folder.
Only after inspecting the build and its origin should the owner manually run
that file. The previous folder remains present for manual rollback by closing
the new app and launching the old executable. Both builds use the separate
`~/.athenz` profile by default; a new binary against an upgraded database
might make that profile incompatible with an older binary. **Version-folder
rollback does not roll back migrations or restore private data.** Back up your
profile first and use a separately recovered profile for destructive tests.

### Limitations

- The checksum and manifest are local integrity checks, **not publisher
  authentication** or independent attestation. A same-user attacker who can
  rewrite the staged files and manifest can forge a new self-consistent stage.
- The tool assumes a trusted destination parent without concurrently hostile
  processes. Not a safe installer for an attacker-controlled directory.
- Staged versions are unsigned, untrusted until you review their source, and
  are **not installed or selected** by this tool. No automated update polling,
  background service, automatic rollback or silent updater exists.
- Windows 11 native UX, GPU inference, Docker/WSL2, HiDPI and production
  version compatibility still need actual owner-device testing before release.
