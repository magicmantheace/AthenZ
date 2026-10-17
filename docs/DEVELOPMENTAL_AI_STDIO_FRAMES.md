# D2 local binary-stream framing (synthetic fixture)

**Status:** An optional, bounded binary-frame **codec** for already-open
stdin/stdout, named pipes or in-memory streams. It does not create a pipe,
spawn the Developmental AI process, open a TCP port, negotiate a shared
session, enroll device credentials or authenticate an owner. There is still
no running cross-repository integration or production local IPC.

## Format

`SyntheticFrameSession` accepts two existing D2 event HMAC producer keys,
**two different frame-layer producer keys**, an externally established
fresh 128-bit lowercase hexadecimal `session_id`, a current synthetic
source-revision checker, and `enabled=True` (default is OFF).
The key bytes are **never** logged or persisted by this module.

Each frame has 4 bytes of unsigned big-endian length (1..4096), followed
by canonical UTF-8 JSON with *exactly*:

- `schema = athenz.d2.stdio-frame/v1`
- `session_id` — a fresh session identifier agreed by the caller/peer
- `sequence` — 1..10000 per producer within the session
- `sent_at` — UTC frame creation time, checked within 300 seconds
- `event` — an existing, separately HMAC-signed D2
  `sandbox/adaptive_sandbox/proposal_only` envelope
- `authentication` — HMAC-SHA256 of the canonical JSON without this
  field, using the *frame* key corresponding to the expected producer

`pack` and `send` validate the embedded signed event and its source
revision before sending. `receive` rejects mismatched session IDs,
producer direction, malformed/oversized/truncated streams, noncanonical
JSON, stale outer timestamps, bad event/frame signatures, skipped/replayed
frame sequence, unsupported authority fields and revoked source revisions.

Only the **outer** frame must be freshly timestamped: signed inner events
from the earlier durable synthetic outbox may be retransmitted under a
new fresh session without erasing their original signed creation time.
`SyntheticFramedJournal` combines a decoded frame with the older
metadata-only `SyntheticBridgeJournal`; that particular journal
**still enforces its own 300-second acceptance window** for original
events. Use a newly signed event for that consumer. Integrating old
outbox delivery into a fully durable receiver is not yet implemented.

## Example of a purely in-memory roundtrip

```python
from io import BytesIO
from athenz.developmental_bridge import synthetic_event
from athenz.developmental_frames import SyntheticFrameSession

# Fixtures only. In production keys need OS-protected distribution,
# each session requires a fresh negotiated ID and peer challenge.
producer = {"athenz": b"a" * 32, "learner": b"l" * 32}
frame = {"athenz": b"f" * 32, "learner": b"g" * 32}
kwargs = dict(
    session_id="5" * 32, producer_keys=producer, frame_keys=frame,
    revision_check=lambda source, rev:
        source == "synthetic:trial" and rev == 1,
    enabled=True,
)
sender = SyntheticFrameSession(**kwargs)
receiver = SyntheticFrameSession(**kwargs)
event = synthetic_event(
    producer="athenz", task_id="trial", seq=1, kind="observation",
    source_ref="synthetic:trial", source_revision=1,
    payload={"signal": "trace_sha256", "value": "a" * 64},
    secret=producer["athenz"])
assert receiver.receive(BytesIO(sender.pack(event)),
                        expected_producer="athenz") == event
```

## Not yet a secure complete connection

This codec **cannot** prove a process's OS identity or who launched it.
A caller that chooses a predictable/reused `session_id` or supplies
shared/public test keys loses cross-session replay resistance. Two
independent participants must still negotiate a fresh random session ID
using an authenticated challenge-response and securely store/provision
keys. In-memory frame counters reset with each codec instance. Durable
event replay/dedup stays the job of the SQLite journal, and reliable
delivery acknowledgments stay the job of the outbox. No outbound
software operation, policy promotion or privileged action is possible
through the frame codec itself.

The registry is still a **synthetic test grant**, not a link to
real consenting-person data. A frame is a transport wrapper; neither
an event signature nor a SHA-256 hash constitutes owner authorization.
Synveil and Windows/WSL2 integrations remain optional and untested.
