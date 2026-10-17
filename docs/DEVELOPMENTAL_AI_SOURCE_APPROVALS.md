# Reviewed synthetic source approvals for D2 (experimental)

This experimental local approval registry is a **human-facing confirmation
boundary**, not authentication of who clicked a confirmation and not
permission to use personal history. It is separate from the real
`IdentityStore`, and cannot authorize model promotion, tool use,
automated shell execution, or non-simulation learning.

## Opt-in source review

`SyntheticSourceRegistry` uses a separate private SQLite file at
`~/.athenz/d2_synthetic_grants.sqlite3` (or `ATHENZ_HOME`). The constructor
uses AthenZ's existing outside-Git home guard and owner-only POSIX directory
and file permissions. The schema holds only short `synthetic:` source
identifiers, approval/revocation revision and the fixed
`adaptive_sandbox/proposal_only` scope. No human text, credentials,
biography, trace or model checkpoint is stored.

- `registry.preview("synthetic:trial", "approve")` returns the **next**
  monotonically increasing revision and a digest binding the exact
  source, action, schema, purpose and scope.
- Present this preview to the local owner. Only after explicit
  confirmation call `registry.review(source, "approve",
  review_sha256=..., confirmed=True)`.
- `registry.preview(source, "revoke")` plus a separate confirmed review
  invalidates the previous approval and increments the revision. Reapproval
  uses another new revision; older signed messages must not resume.
- `registry.is_current(source, revision)` fails closed on absent, stale
  or revoked sources and can be passed to either synthetic bridge journal
  or the `SyntheticExchange` revision callback.

A caller that can run Python locally can pass `confirmed=True`;
the registry **does not prove that caller is the owner**. The SHA-256
review digest is a stale-preview guard, not a consent signature.
There is currently no GUI prompt, password, OS session attestation,
owner identity binding, model permission, or real private identity-source
mapping.

## Terminal review workflow

This standalone command opens **only** the synthetic grant registry and does
not initialize the private human-memory database:

```bash
python -m athenz.developmental_consent_cli status synthetic:trial
python -m athenz.developmental_consent_cli preview synthetic:trial approve
# Inspect the source, action, scope, revision and review_sha256 shown above.
python -m athenz.developmental_consent_cli review synthetic:trial approve --review-sha256 <preview-sha256> --confirm

python -m athenz.developmental_consent_cli preview synthetic:trial revoke
python -m athenz.developmental_consent_cli review synthetic:trial revoke --review-sha256 <new-preview-sha256> --confirm
```

The command prints bounded JSON metadata, rejects stale/mismatched digests,
and never has a `--force` or an auto-approve option. A shared
`--home <private-dir>` override works when testing a separate local
profile, but Git-checkout homes are rejected. This local command checks
**affirmation only**, not human identity or an OS-authenticated session.
No profile data is exported, model weights are updated, or system command
is authorized by this approval.

## Binding to the durable outbox

```python
from pathlib import Path
from athenz.developmental_consent import SyntheticSourceRegistry
from athenz.developmental_exchange import SyntheticExchange

with SyntheticSourceRegistry() as grants:
    preview = grants.preview("synthetic:trial", "approve")
    # Show preview in a trusted local UI before accepting real human input.
    # This example deliberately does not auto-confirm it.
    with SyntheticExchange.from_registry(
        grants.home / "d2_synthetic_exchange.sqlite3",
        keys={"athenz": b"a" * 32, "learner": b"l" * 32},  # test-only keys
        registry=grants, enabled=False,
    ) as queue:
        assert queue.pending() == []  # off by default
```

`from_registry` enforces that the exchange and approval database live in
the **same private home** and keeps an always-current callback to that
registry. An unapproved source cannot stage a reply pair. After a confirmed
revocation, previously staged messages cannot be delivered or acknowledged
under the old source revision, even after a process restart. Revocation is
not a retrospective memory-erasure mechanism; any downstream state
derived before the revoke would require a separate provenance-aware deletion.

## Remaining gaps

No authenticated owner session or portable Windows ACL verifier exists.
Revocation across the registry and the separate exchange SQLite file is
checked at method boundaries, not joined by one cross-file transaction;
a concurrent grant change after the final check may still race with use.
Production D2 must unify consent with AthenZ's real private identity and
source-deletion lifecycle, authenticate the local calling process and remote
learner, protect/rotate signing keys, adopt reliable IPC and signed ACK
receipts, and gate downstream effects under the latest authorization epoch.
The older synthetic checker and registry are **not** substitutes.
