"""AthenZ identity-management CLI. All new identity assertions are pending by default."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from .store import IdentityStore, KINDS


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="athenz", description="Local-first identity foundation")
    p.add_argument("--home", type=Path, help="Private data directory")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    x = sub.add_parser("propose")
    x.add_argument("kind", choices=sorted(KINDS))
    x.add_argument("text")
    x.add_argument("--source", default="owner:cli")
    x.add_argument("--source-ref", default="")
    x.add_argument("--confidence", type=float, default=1.0)
    x = sub.add_parser("status")
    x.add_argument("id", type=int)
    x.add_argument("state", choices=["approved", "pending", "rejected"])
    x = sub.add_parser("revise")
    x.add_argument("id", type=int)
    x.add_argument("text")
    x.add_argument("--reason", required=True)
    x = sub.add_parser("forget")
    x.add_argument("table", choices=["identity", "decisions", "writing_samples"])
    x.add_argument("id", type=int)
    x = sub.add_parser("purge-source")
    x.add_argument("source")
    x.add_argument("--source-ref", default="")
    x = sub.add_parser("list")
    x.add_argument("table", choices=["identity", "decisions", "writing_samples", "events", "identity_revisions"])
    x.add_argument("--status", choices=["approved", "pending", "rejected"])
    x = sub.add_parser("decision")
    x.add_argument("scenario")
    x.add_argument("choice")
    x.add_argument("rationale")
    x.add_argument("--exception", default="")
    x.add_argument("--source", default="owner:cli")
    x = sub.add_parser("decision-status")
    x.add_argument("id", type=int)
    x.add_argument("state", choices=["approved", "pending", "rejected"])
    x = sub.add_parser("sample")
    x.add_argument("text")
    x.add_argument("--source", default="owner:cli")
    x = sub.add_parser("export")
    x.add_argument("path", type=Path)
    sub.add_parser("context")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    store = IdentityStore(args.home)
    try:
        if args.cmd == "init":
            print(f"Initialized private AthenZ store at {store.path}")
        elif args.cmd == "propose":
            print(f"Pending identity #{store.propose(args.kind, args.text, source=args.source, source_ref=args.source_ref, confidence=args.confidence)}")
        elif args.cmd == "status":
            print("Updated" if store.status(args.id, args.state) else "Unknown ID")
        elif args.cmd == "revise":
            print("Revision pending approval" if store.revise(args.id, args.text, args.reason) else "Unknown ID")
        elif args.cmd == "forget":
            print("Deleted" if store.delete(args.table, args.id) else "Unknown ID")
        elif args.cmd == "purge-source":
            print(json.dumps(store.purge_source(args.source, args.source_ref)))
        elif args.cmd == "list":
            print(json.dumps(store.list_items(args.table, args.status), indent=2))
        elif args.cmd == "decision":
            print(f"Pending decision #{store.add_decision(args.scenario, args.choice, args.rationale, source=args.source, exception=args.exception)}")
        elif args.cmd == "decision-status":
            print("Updated" if store.decision_status(args.id, args.state) else "Unknown ID")
        elif args.cmd == "sample":
            print(f"Sample #{store.add_sample(args.text, source=args.source)}")
        elif args.cmd == "export":
            if args.path.exists():
                raise FileExistsError("Refusing to overwrite identity export")
            args.path.write_text(json.dumps(store.export(), indent=2) + "\n", encoding="utf-8")
            print(f"Exported private profile to {args.path}; protect this file")
        elif args.cmd == "context":
            print(json.dumps(store.context(), indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    main()
