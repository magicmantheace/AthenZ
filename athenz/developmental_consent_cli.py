"""Explicit local CLI for reviewing strictly synthetic D2 source grants.

Preview first; review requires the exact pinned digest and --confirm.
This terminal workflow is NOT authentication of the human owner.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from .developmental_bridge import BridgeError
from .developmental_consent import SyntheticSourceRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m athenz.developmental_consent_cli",
        description="Review private, synthetic-only Developmental AI source grants",
    )
    parser.add_argument("--home", type=Path, default=None,
                        help="Existing or new AthenZ private home, never a Git checkout")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="Inspect one synthetic source revision")
    status.add_argument("source_ref")
    preview = commands.add_parser("preview", help="Preview approve/revoke; does not mutate")
    preview.add_argument("source_ref")
    preview.add_argument("decision", choices=("approve", "revoke"))
    review = commands.add_parser("review", help="Commit exactly one reviewed revision")
    review.add_argument("source_ref")
    review.add_argument("decision", choices=("approve", "revoke"))
    review.add_argument("--review-sha256", required=True,
                        help="Digest obtained from a separate preview")
    review.add_argument("--confirm", action="store_true",
                        help="Local explicit source review; not proof of owner identity")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        # Never initialize the personal memory database just to review a
        # synthetic reference. Only a separate, small registry is touched.
        with SyntheticSourceRegistry(args.home) as registry:
            if args.command == "status":
                result = registry.status(args.source_ref)
            elif args.command == "preview":
                result = registry.preview(args.source_ref, args.decision)
            elif args.command == "review":
                result = registry.review(
                    args.source_ref, args.decision,
                    review_sha256=args.review_sha256, confirmed=args.confirm)
            else:
                parser.error("Unsupported synthetic source command")
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (BridgeError, sqlite3.Error, OSError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
