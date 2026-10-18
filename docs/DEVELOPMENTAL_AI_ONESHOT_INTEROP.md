# D2 single-request synthetic Developmental AI transport (experimental)

**Status:** Off-by-default, non-executing AthenZ interoperability choreography.
This is **not** a deployed integrated Developmental AI worker, authenticated
owner consent, or a device control interface.

`athenz.developmental_roundtrip.synthetic_trace_roundtrip` is a short,
bounded, explicitly enabled contract for caller-owned binary streams.
It never launches a process, opens a socket, reads a human memory or gives
permissions to a model. The request is restricted to a currently approved
`synthetic:interop` source, containing exactly a signed SHA-256 trace
reference and no private text.

Both participants are separately provisioned with 32-byte-or-longer
event signing keys and a root transport key. In the public integration
test, 96 **fresh random bytes** are passed through a child process's
already-open binary stdin *before* the authenticated handshake. This is
synthetic test bootstrapping, **not** OS process authentication or a key
vault. Keys are never placed on the command line or in the Git tree.

The AthenZ client:

1. Verifies source approval and event scope before sending any handshake
   bytes, and verifies its receiver/outbox live in the same private home.
2. Negotiates the existing mutual proof-of-key D2 session and transmits
   the signed, fixed synthetic trace-reference observation.
3. Receives two distinct, authenticated `learner` framed messages,
   persistently journals each via `SyntheticDurableReceiver`, and
   returns only the verified event data to the caller on an explicit
   `include_event=True` request.
4. Requires an `action_proposed` followed by
   `evaluation_receipt`, matching source/revision and task, then
   commits the request and exact reply pair via `SyntheticExchange`.
5. Sends two HMAC-bound delivery ACKs **only after** the complete
   pair has been committed. No reply is a command or model promotion.

The included public CI peer in `tests/fixtures/d2_roundtrip_peer.py`
is a fake, reproducible stand-in. It stages signed generic responses
in an independent private peer outbox and checks that its signed ACK
receipts mark both messages delivered. This exercises two **actual
Python processes** and distinct SQLite databases, but has no private
Developmental AI code, learning algorithm or owner data.

## Cross-repository next step

The separate, private Developmental AI repository has a draft
`verified_synthetic_replies` adapter that independently verifies
the simulator's trace and exports exactly two non-executing signed
envelopes. A corresponding private one-shot peer will use that function
rather than the fixed-response public fixture. Its tests and code
must remain private; the public AthenZ CI must not clone or publish
that private repository.

The private worker will need the same wire keys through protected
one-shot input, approved source revisions, a verified deterministic
trace, its own durable outbox and signed ACK verification.

## Still outstanding

- Actual authenticated OS executable identity, protected credential
  storage/key lifecycle, human consent and source-to-human mapping.
- Robust reconnection after a peer crashes mid-ACK, timestamp-expired
  original requests at outbox replay, and a remote process supervisor
  that **cannot** launch arbitrary system commands.
- Atomic real-owner revocation/derived-state cleanup across different
  databases, interprocess receipt reconciliation and model rollback.
- The protocol is proposal-only and cannot train or autonomously
  update a deployed learner. The full end-to-end acceptance gate
  remains open.

The public CI fixture never authorizes execution of shell, model
promotion or any real action. Only a human who has reviewed a
sandbox-only source can opt into the development demonstration.
