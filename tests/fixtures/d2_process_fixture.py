"""Insecure, fixed-key synthetic D2 subprocess test fixture only.

Not a real Developmental AI service, credential provider or code executor.
The explicit flag and synthetic source guard prevent accidental live usage.
"""
from __future__ import annotations

from pathlib import Path
import sys

from athenz.developmental_bridge import synthetic_event
from athenz.developmental_consent import SyntheticSourceRegistry
from athenz.developmental_pipe import learner_handshake

TEST_ROOT = b"s" * 32  # PUBLIC TEST KEY; never use on owner records.
KEYS = {"athenz": b"a" * 32, "learner": b"l" * 32}
SOURCE = "synthetic:process"


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--synthetic-fixture":
        return 2
    with SyntheticSourceRegistry(Path(sys.argv[2])) as grants:
        session = learner_handshake(
            sys.stdin.buffer, sys.stdout.buffer,
            root_secret=TEST_ROOT, producer_keys=KEYS,
            revision_check=grants.is_current, enabled=True)
        inbound = session.receive(sys.stdin.buffer, expected_producer="athenz")
        if (inbound["source_ref"] != SOURCE
                or inbound["kind"] != "observation"
                or inbound["payload"] != {
                    "signal": "trace_sha256", "value": "a" * 64}):
            return 3
        common = dict(task_id=inbound["task_id"], source_ref=SOURCE,
                      source_revision=inbound["source_revision"])
        reply1 = synthetic_event(
            **common, producer="learner", seq=1, kind="action_proposed",
            payload={"summary": "synthetic proposal only; no system action"},
            secret=KEYS["learner"])
        reply2 = synthetic_event(
            **common, producer="learner", seq=2, kind="evaluation_receipt",
            payload={"result": "independently replayed 4 simulator events"},
            secret=KEYS["learner"])
        session.send(sys.stdout.buffer, reply1)
        session.send(sys.stdout.buffer, reply2)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Do not print raw exception text or source values.
        print("Synthetic fixture failed: " + type(exc).__name__, file=sys.stderr)
        sys.exit(4)
