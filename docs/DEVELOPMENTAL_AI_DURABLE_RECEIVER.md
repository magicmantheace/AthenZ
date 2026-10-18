# D2 durable synthetic framed receiver — restart/replay prototype

**Status:** Opt-in synthetic-only metadata journal; this is not a production
Developmental AI connection, process identity service, owner consent service
or training mechanism.

The previous `SyntheticBridgeJournal.receive(event)` requires signed event
timestamps to be within five minutes of reception. That is appropriate for a
new direct event, but causes **durable redelivery after restart** to fail,
even if the same signed event arrives in a fresh authenticated transport
frame.

`athenz.developmental_receiver.SyntheticDurableReceiver` solves only that
narrow problem. Its sole ingress method is
`receive_frame(session, binary_reader, expected_producer='learner')`.
It requires an enabled `SyntheticFrameSession` with the same configured
producer keys, verifies the **fresh outer** frame timestamp, per-session
frame sequence, HMAC session authentication, and full original event
producer signature, then applies the current source revision checker
before and during a `BEGIN IMMEDIATE` SQLite transaction.

The inner event's original UTC timestamp may be old because the
original signed event can be retrieved from a durable outbox after days
offline. This is not an unrestricted stale replay exception: the old
event still requires a newly authenticated delivery frame and its exact
HMAC signature; the private receiver tracks global event ID, digest
and per-producer/task sequence across restarted sessions.

For the one-shot D2 request/reply coordinator, the receiver can enforce
the expected task ID, event kind, source reference and revision. These
fields are checked **after frame authentication, before any SQLite insert**.
A signed but unrelated learner reply therefore cannot occupy the legitimate
task's durable sequence slot. Other callers remain compatible because
all expectations are optional. Invalid expectations are rejected before
reading any frame bytes.

The receiver requires an owner-only parent directory and database file mode on POSIX systems; Windows ACL validation remains a deployment gate. It persists **metadata only**, no original JSON/envelope text
or simulation payload. A fixed allowlist permits only signed
`athenz` trace-digest observations and generic non-executable signed
`learner` proposals / trace-evaluation receipts. There is a hard
5,000-event limit without pruning; no unsafe automatic history
rotation or sequence resets. Unknown fields, changed signatures,
missing sequences and missing/stale/revoked grants fail closed.

`SyntheticDeliveryAck.issue` can now accept an enabled
`SyntheticDurableReceiver` as proof that the precise learner event
was committed before a session-HMAC receipt is issued. Legacy
`SyntheticBridgeJournal` callers continue working. The signed
receipt verifies the event/digest against the outbox before marking
delivery acknowledged, and neither event nor receipt authorizes
code/system execution or model promotion.

## Deliberate limitations

- Two processes sharing a root transport secret do not establish an
  independently attested OS executable identity or owner permission.
  Public fixture keys must NEVER secure real content.
- A source revision callback is not authenticated real-person consent.
  Source approval and the receiver SQLite transaction are in
  **different databases**, so downstream revocation still needs a
  stronger authoritative, atomic fence.
- This journal records **what** was received, not private learning
  events, applied results, memories, or model state. It cannot provide
  effective exactly-once side effects for a real adaptive learner.
- Inbound signed frames are validated synchronously. A network, socket,
  pipe service, remote authenticated ACK delivery/restart coordinator,
  secure key vault, verified Developmental AI trace adapter and
  cross-process reconnection orchestration remain separate work.
- Old signed messages remain valid only for unchanged, currently
  approved source revisions; this does not resurrect erased identity
  sources or revoked permissions.

Regression covers aged signed envelopes over fresh session frames,
restart duplicate handling, tampered stored digests, mismatched keys,
sequence gaps, state rollback, bounded storage, source revocation, and
receipt issuance after a matching journal commit.
