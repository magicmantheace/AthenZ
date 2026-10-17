# D2 synthetic durable request/reply outbox — experimental

**Scope:** offline fixture only. This code does **not** start a network listener,
talk to the private Developmental AI process, authorize a human action, train
models, read personal data, or provide production-grade authenticated consent.

`athenz.developmental_exchange.SyntheticExchange` is a separate,
off-by-default SQLite journal for a bounded synthetic request and its two
generic responses. This extends, not replaces, the earlier metadata-only
`SyntheticBridgeJournal`.

## Why a new journal?

The existing AthenZ protocol journal can accept one event durably but cannot
atomically stage an independently produced response pair. A crash after
recording an inbound observation could silently lose the two replies.

`stage_pair(request, proposal, receipt)` validates three signed D2 messages,
matching synthetic source revision and task ID, strictly consecutive producer
sequence counters, immutable sandbox scope and fixed generic response text.
Then a single `BEGIN IMMEDIATE` SQLite transaction records the request
digest, advances both producer sequence numbers and stores **both** signed
learner response envelopes. Any error rolls back the entire transaction.

- `pending(limit=20)` revalidates the stored message digest/signature,
  source revision and synthetic revocation status; old signed timestamps
  remain replayable after a restart, not subject to a fresh-send timeout.
- `acknowledge(event_id, digest, confirmed=True)` records a caller-attested
  delivery only after checking the saved digest and current revision. This
  is **not** a remote authenticated acknowledgment.
- `receive_revocation(signed_event)` atomically records an AthenZ-origin
  source fence and marks outstanding messages for that source revoked.
- Exact request retries return a deterministic duplicate status while the
  originally stored pair remains the one available for retransmission.
  A different payload under the same event ID fails closed.
- At most 256 unacknowledged messages, 20 returned in one call and 5,000
  distinct ingested requests; it never attempts to run or apply a proposal.

This is **at-least-once delivery staging**, not exactly-once execution:
the sender can crash after sending an event and before recording an ACK.
A real receiver must independently authenticate and deduplicate events.

## Synthetic usage

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from athenz.developmental_bridge import synthetic_event
from athenz.developmental_exchange import SyntheticExchange

keys = {"athenz": b"a" * 32, "learner": b"l" * 32}  # public TEST keys
common = {"task_id": "demo", "source_ref": "synthetic:demo",
          "source_revision": 1}

with TemporaryDirectory() as temp:
    with SyntheticExchange(
        Path(temp) / "queue.sqlite3", keys=keys,
        revision_check=lambda source, revision:
            source == "synthetic:demo" and revision == 1,
        enabled=True,
    ) as queue:
        request = synthetic_event(
            **common, producer="athenz", seq=1, kind="observation",
            payload={"signal": "trace_sha256", "value": "a" * 64},
            secret=keys["athenz"])
        proposal = synthetic_event(
            **common, producer="learner", seq=1, kind="action_proposed",
            payload={"summary": "synthetic proposal only; no system action"},
            secret=keys["learner"])
        receipt = synthetic_event(
            **common, producer="learner", seq=2, kind="evaluation_receipt",
            payload={"result": "independently replayed 4 simulator events"},
            secret=keys["learner"])
        assert queue.stage_pair(request, proposal, receipt)["status"] == "staged"
        assert len(queue.pending()) == 2
```

## Limitations that still block production D2

The public test HMAC secrets are not device credentials. The injected
`revision_check` is an explicit synthetic test callback and is not wired to
AthenZ's real identity/consent database. The code accepts deliberately
generic simulator-reply wording only, to avoid accidentally persisting owner
information in this experimental journal. There is no authenticated IPC
transport, managed key rotation, safe cross-process queue ownership,
end-to-end source revocation into learned state, remotely authenticated ACK,
Windows installer integration or consumer interface.

SQLite writes and reads are transactional but a caller's independent consent
source can still change after the final callback. Production integration
will require a single authoritative consent revision fence spanning final
delivery/use and downstream state, rather than treating a callback as a
capability or local HMAC as proof of owner approval.

No real learning, autonomous task, durable physical action or long-run
survivability claim is supported by these tests.
