# D2 separate-process, buffered-stdio synthetic smoke test

**Status:** Test-only process fixture; not connected to the private
Developmental AI runtime and not production IPC.

`SyntheticFrameSession.send()` now calls `flush()` after writing a complete
HMAC-framed synthetic message to a caller-owned binary stream. Prior to this
change, Python buffered stdio could retain an entire message while the peer
waited for it. A short/broken write, missing flush method, or failed flush
**permanently poisons** that in-memory sender. Reusing the same session
would risk sequence ambiguity; callers must negotiate a new session and use
the separate durable event ledger to deduplicate replayed messages. Invalid
untransmitted events do not poison the session.

The `tests/fixtures/d2_process_fixture.py` file is an intentionally
insecure, fixed-key, non-executing synthetic learner stand-in. Its
`--synthetic-fixture` flag is required. `test_developmental_subprocess.py`
starts it in a **separate Python process** with an allowlisted environment,
buffered standard streams, and a 12-second per-process watchdog. It
negotiates the existing shared-key handshake, sends one synthetic signed
trace digest reference and receives exactly two fixed, generic signed
learner replies. A private synthetic registry gates both parties; the
test then stages the pair transactionally and checks revocation.

Additional negative tests check missing approval and wrong transport key.
The subprocess cannot launch shell commands or act on a real OS, inspect
owner memories, run a model, or change system permissions. The fixed
keys in these tests are public and must never be reused in deployment.

## Not yet implemented

This is an **actual OS process boundary test**, not the real private
Developmental AI program. It does not authenticate a human or a
specific executable's OS identity. Protected credential provisioning,
process lifecycle isolation, independently verified simulator trace
adapter, remote authenticated ACK, receiver-side durable deduplication,
restart recovery and authoritative real-source consent remain required
before a D2 production release.

To run locally on a supported Python 3.11+ installation:

```bash
python -m unittest discover -s tests -p test_developmental_frames_flush.py -v
python -m unittest discover -s tests -p test_developmental_subprocess.py -v
```
