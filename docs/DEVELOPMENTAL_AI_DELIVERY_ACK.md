# Synthetic D2 HMAC-bound delivery acknowledgments

**Status:** Opt-in local protocol fixture. This is not a production
process-identity guarantee or proof of owner authorization.

`SyntheticDeliveryAck` adds a signed delivery receipt for a learner
proposal or simulator evaluation receipt. It uses the AthenZ direction's
HMAC key from a previously negotiated synthetic `SyntheticFrameSession`.
No new root secret is stored and no network listener, system action,
training call or privileged tool is created.

The receiver may call `issue(event, journal)` **only after** the exact
original producer-signed learner event is present in a
`SyntheticBridgeJournal` with a matching SHA-256 fingerprint. The
receipt identifies only `session_id`, `sequence`, `receiver=athenz`,
`event_id`, `envelope_sha256`, `source_ref`, `source_revision`
and UTC receipt timestamp, with an HMAC signature. It deliberately
contains no natural language or event payload.

The sender verifies the schema, strict fields, HMAC, session ID,
bounded sequence and fresh timestamp. The matching outbox record,
digest and current grant revision must still be present before
`exchange.acknowledge(... confirmed=True)` is called. A failed
signature, stale approval, unknown event, sequence gap or tampered
outbox leaves delivery unacknowledged.

`send/receive` use a 2-byte big-endian length prefix and canonical
JSON, maximum 1024 bytes. On stream failure the caller must end this
synthetic session; durable replay belongs to existing outbox and
journal primitives. No real remote ACK claims should be made from
a merely caller-attested `SyntheticExchange.acknowledge`.

## Boundaries and remaining work

- **Both peers share the session root-derived frame key.** Its HMAC
  proves session key possession, not owner identity, an OS process,
  or independent nonrepudiation.
- The metadata-only `SyntheticBridgeJournal.receive` still checks
  original event freshness. Persisting signed old envelopes on a
  restarted **real** receiver requires a separately designed and
  validated durable receiver journal.
- ACK issuance and local receipt ingestion are not one cross-process
  atomic transaction, and independent private process launch is not
  wired into the real Developmental AI simulator adapter.
- This does not securely provision keys, revoke derivative learned
  state, authenticate owner consent or automatically promote models.
- Approval remains synthetic-only and proposal-only.

Use only for fixed or synthetic D2 unit tests until a real learner
process, secure key management, durable receiver identity, and
end-to-end process recovery have been validated.
