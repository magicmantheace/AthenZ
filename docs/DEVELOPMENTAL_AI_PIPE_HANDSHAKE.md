# D2 supervised binary-pipe handshake fixture

**Status:** Local, opt-in synthetic prototype. It does not spawn a learner,
control an operating system, connect to the actual Developmental AI
repository, import owner messages, grant elevated permissions or train
models. This is the first caller-owned **binary-stream handshake and frame
exchange** test combining the D2 components.

`athenz.developmental_pipe` connects existing components:

1. Caller supplies two already-open binary streams, a **separately and
   securely provisioned** 32-byte-or-longer root transport key,
   independently authenticated D2 event-producer keys, and a current
   synthetic source revision checker.
2. `athenz_handshake(reader, writer, ... enabled=True)` writes an
   unpredictable client challenge, checks the learner's HMAC proof and
   source approval, and emits the final client confirmation.
3. `learner_handshake(reader, writer, ... enabled=True)` validates a
   strict hello and source revision, sends its own random challenge/HMAC
   proof, and verifies the final confirmation.
4. Both return an authenticated `SyntheticFrameSession` with matching
   ephemeral, direction-separated frame HMAC keys. The two participants
   can then send and receive already-signed sandbox-only D2 events over
   those **caller-owned** streams.

Handshake records use a 2-byte unsigned big-endian length followed by
canonical UTF-8 JSON with a hard 512-byte bound and exactly allowlisted
protocol fields. Frames use their separate 4-byte/4096-byte codec,
HMAC and sequence limits. Each side must independently validate
the current source revision before use.

The tested OS-pipe integration has two **threads** connected through
two real OS-created binary pipes (Linux/Windows). The peer has its own
private SQLite registry connection; it never shares AthenZ's SQLite
connection across threads. The test stages one signed synthetic
trace-reference request and both signed, fixed-text replies into a
durable `SyntheticExchange`, verifies they are not commands or human
memories, and revokes their source before further delivery. It tests
bytes crossing an OS stream boundary, **not** two independently launched
operating-system processes.

All participant streams must be closed on error. Half-written frames
invalidate the session; reconnect with a fresh challenge and rely on
the existing durable outbox and event-ID deduplication. No retries of
privileged actions exist; no system actions can be requested by the
allowed synthetic payloads.

## What is still needed for a real connection

The caller must implement protected root-key provisioning and rotation,
authenticated OS peer-process identity, private Developmental AI
executable startup/lifetime controls, secure stdin/stdout ownership,
atomic authorized remote ACK, restart/replay across process failure
and a single authoritative real-person source-consent and derived-state
revocation fence. A process with the transport key could impersonate
the other participant; proof of key possession is not proof of a
consenting person. Running pipes locally is not itself peer
authentication or permission to operate software.

This demo remains off by default and does not alter AthenZ agent
tool permissions, model-training gates or personal biography storage.
