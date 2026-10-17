# Synthetic D2 event bridge: AthenZ-side prototype

This is **only a schema and offline in-process journal fixture**, not an
operating Developmental AI integration, network endpoint, real user consent
checker, model training system or privileged tool runner.

## What is implemented

- Strict schema-one, authenticated per-producer envelopes with an explicit
  sandbox-only namespace, purpose and fixed `proposal_only` scope.
- An allowlisted producer/event/origin matrix. The synthetic learner cannot
  publish human records, owner approvals, executed actions or system commands.
- Per-event HMAC-SHA256 message authentication for test fixtures. The secrets
  are passed directly to the fixture, never generated from a hash of private
  content or committed. A shared HMAC key is **not owner consent** or
  production identity, and these fixture keys must not be reused.
- Bounded UTF-8 JSON envelopes, exact payload field/type checks, strict
  identifiers, UTC timestamps and sequence counters.
- SQLite replay journal storing **metadata and digests only**, with
  per-producer/task sequence fences, exact idempotent retries and durable
  synthetic source-revocation blocks. No prompt content, personal memories,
  private training data or simulated observation strings are persisted.
- Explicit owner-side opt-in with `enabled=False` as the default and a
  caller-supplied consent-check function evaluated for every new event.
- Fail-closed errors for missing consent, altered signatures, forged origins,
  unexpected fields, event reordering and revoked sources. No execution,
  auto-approval, learning, candidate promotion or side effects.

Example (synthetic-only, in a disposable directory):

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from athenz.developmental_bridge import SyntheticBridgeJournal, synthetic_event

secrets = {"athenz": b"a" * 32, "learner": b"l" * 32}
with TemporaryDirectory() as folder:
    journal = SyntheticBridgeJournal(
        Path(folder) / "bridge.sqlite3", keys=secrets,
        consent_check=lambda ref, rev: ref == "synthetic:demo" and rev == 1,
        enabled=True,
    )
    event = synthetic_event(
        producer="athenz", task_id="demo", seq=1,
        kind="observation", source_ref="synthetic:demo", source_revision=1,
        payload={"signal": "synthetic-position", "value": "zero"},
        secret=secrets["athenz"],
    )
    assert journal.receive(event)["status"] == "accepted"
    assert journal.receive(event)["status"] == "duplicate"
    journal.close()
```

## Important limitations

This artifact deliberately **rejects real source references** and never
exports identity or autobiographical records to Developmental AI. There is
no learner subprocess, no transport authentication, no cross-repository
schema negotiation, no owner UI, no secure secret management and no
consent callback bound to AthenZ's actual reviewed-source revisions.
SQLite stores an event digest and sequence, not the payload, so this is
not a full recovery/replay transport. For full D2 acceptance the transport
must durably stage permitted payloads in an access-controlled private queue,
revalidate owner consent and revision at the final point of use, and
propagate revocations into any downstream derived policy state.

The synthetic journal does not close the D2 gate in
[DEVELOPMENTAL_AI_INTEGRATION.md](DEVELOPMENTAL_AI_INTEGRATION.md).
Any real transport needs fresh, per-session trust establishment and
OS-specific permissions on Windows/WSL2 and Linux, compatibility tests
against the Developmental AI repo, and independent human approval before
real device actions.


## Cross-repository synthetic compatibility milestone (2026-10-17)

An unmerged Developmental AI integration branch has an experimental mirrored
`developmental_ai.athenz_bridge` implementation and
`developmental_ai.athenz_sim_adapter` proposal projection. The projects
pin identical `tests/fixtures/d2_synthetic_vector.json` fixtures and
independently check the HMAC-signed AthenZ observation's exact canonical
JSON digest, immutable fields and fixed sandbox authority.

The learner-side fixture verifies a simulator ledger **against its original
verified trace** and returns only generic `simulation_episode` proposal and
evaluation receipt metadata, never a shell command or a person's history.
AthenZ's fixed synthetic `human_record` tag on an observation is a request
reference only and must never become a human-autobiographical memory.

The two projects' tests validate **format compatibility**, not live IPC,
owner authorization, complete durable restart replay, model learning,
sensor reliability or safe real-world action. Full D2 acceptance stays open.
