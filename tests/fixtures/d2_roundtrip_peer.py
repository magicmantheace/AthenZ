"""Single-use, deliberately non-learning D2 peer for cross-process CI.

Only public synthetic schema fixture material. Reads 96 random session bytes
from the caller's stdin *before* D2 handshake. Does not read private history,
execute tools, generate model weights, open listeners or mutate the owner profile.
"""
from __future__ import annotations

import sys
from pathlib import Path

from athenz.developmental_ack import SyntheticDeliveryAck
from athenz.developmental_bridge import BridgeError, synthetic_event
from athenz.developmental_consent import SyntheticSourceRegistry
from athenz.developmental_exchange import SyntheticExchange
from athenz.developmental_pipe import learner_handshake


def exactly(stream, n):
    result = bytearray()
    while len(result) < n:
        chunk = stream.read(n - len(result))
        if not chunk:
            raise BridgeError("Truncated private test-only bootstrap")
        result.extend(chunk)
    return bytes(result)


def run(home: Path) -> None:
    root, akey, lkey = (lambda b: (b[:32], b[32:64], b[64:]))(
        exactly(sys.stdin.buffer, 96))
    keys = {"athenz": akey, "learner": lkey}
    with SyntheticSourceRegistry(home) as registry:
        session = learner_handshake(
            sys.stdin.buffer, sys.stdout.buffer, root_secret=root,
            producer_keys=keys, revision_check=registry.is_current, enabled=True)
        request = session.receive(sys.stdin.buffer, expected_producer="athenz")
        if (request["kind"] != "observation"
                or request["source_ref"] != "synthetic:interop"
                or request["payload"] != {
                    "signal": "trace_sha256", "value": "a" * 64}):
            raise BridgeError("Synthetic trace did not match the frozen fixture")
        common = dict(task_id=request["task_id"],
                      source_ref=request["source_ref"],
                      source_revision=request["source_revision"])
        proposal = synthetic_event(
            **common, producer="learner", seq=1, kind="action_proposed",
            payload={"summary": "synthetic proposal only; no system action"},
            secret=lkey)
        receipt = synthetic_event(
            **common, producer="learner", seq=2, kind="evaluation_receipt",
            payload={"result": "independently replayed 4 simulator events"},
            secret=lkey)
        with SyntheticExchange.from_registry(
            home / "d2_fixture_peer_outbox.sqlite3", keys=keys,
            registry=registry, enabled=True) as outbox:
            outbox.stage_pair(request, proposal, receipt)
            for item in outbox.pending():
                session.send(sys.stdout.buffer, item)
            ack = SyntheticDeliveryAck(session, enabled=True)
            for _ in range(2):
                ack.receive(sys.stdin.buffer, outbox)
            if outbox.pending():
                raise BridgeError("Fixture peer still has unacknowledged messages")


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "--synthetic-d2-test":
        return 2
    try:
        run(Path(sys.argv[2]))
        return 0
    except Exception as exc:
        print("Synthetic D2 peer rejected session: " + type(exc).__name__,
              file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
