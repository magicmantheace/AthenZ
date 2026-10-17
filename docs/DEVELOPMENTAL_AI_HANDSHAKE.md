# D2 synthetic mutual-key session handshake (prototype)

This module negotiates a fresh **synthetic, proposal-only** session over
objects supplied by callers. It does NOT run a process, open a network socket,
create pipes, authenticate the person's identity, prove the peer's operating
system process identity, provision credentials, or grant tool permissions.

`athenz.developmental_handshake` offers a four-step flow:

1. AthenZ calls `initiate(source_ref, revision)`, generating a fresh,
   cryptographically random 128-bit nonce, for a `synthetic:` source only.
2. The learner checks the current source revision and responds with
   `respond(hello, root_secret=..., revision_check=...)`, generating another
   128-bit nonce and an HMAC proving knowledge of a separately provisioned
   32-byte-or-longer root transport key.
3. AthenZ calls `finalize(...)`, verifying the learner proof, rechecking
   the source approval, and producing its own HMAC confirmation.
4. The learner calls `accept(...)`, authenticating the confirmation and
   again checking the current synthetic revision.

Both parties independently derive the same `session_id` (128-bit hex)
and separate 32-byte frame HMAC keys for the `athenz` and `learner`
directions. The keys are domain-separated from the root secret and from
each other. All challenges, signatures and key derivations bind the exact
source reference and revision. The module never writes any key to disk.
The root secret must **NOT** be embedded in scripts, public Git, CLI
arguments, telemetry, unprotected environment variables or logs.

```python
from athenz.developmental_handshake import initiate, respond, finalize, accept

# Public synthetic test fixture only, not an actual owner credential.
test_root = b"r" * 32
allowed = lambda src, rev: src == "synthetic:trial" and rev == 1

hello = initiate("synthetic:trial", 1)
reply = respond(hello, root_secret=test_root, revision_check=allowed)
confirmation, athenz_session = finalize(
    hello, reply, root_secret=test_root, revision_check=allowed)
learner_session = accept(
    hello, reply, confirmation, root_secret=test_root, revision_check=allowed)
assert athenz_session == learner_session
```

The resulting keys are designed for the separate
[synthetic framed-stream codec](DEVELOPMENTAL_AI_STDIO_FRAMES.md), whose
first implementation is staged independently. Do not treat either
component as deployed without a validated end-to-end handshake and
frame exchange with a real Developmental AI peer.

## Security and engineering limits

- A shared key proves possession of that key, **not** who the person or
  OS process is; compromise of the key invalidates this authentication.
- The root key is caller-provided and there is no OS credential store,
  secure key delivery, rotation, process identity attestation or real
  AthenZ-approved identity-to-learning-source mapping.
- Sessions are temporary in-memory values. Fresh random challenges and
  transcript binding reject naive replay or mismatched sides, but there
  is no durable nonce replay blacklist and a relay attack is not
  independently defeated.
- The `revision_check` is caller-provided synthetic status; a
  source revoked after the final check can race with downstream use.
  Send/receive, final state commits, and model promotion must apply
  separate authoritative revocation fences.
- No real-owner biography, model state, internet connection, action
  execution, background process or autonomous learning is touched.

This is a cryptographic **building block**, not full D2 acceptance.
