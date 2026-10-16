"""Local-only, owner-entered longitudinal preference observations.

Never exported to Git, prompt contexts, feedback training, or model inference.
Measured repeat consistency does not establish a stable human personality.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import json
import os
from pathlib import Path
import re
import tempfile

from .family_audit import _read_private
from .store import private_home_path

_FILENAME = "decision-timeline.json"
_LOCK = "decision-timeline.lock"
_PATTERN = re.compile(r"[a-z][a-z0-9_-]{2,63}\Z")
_MAX_RECORDS = 1000
_MAX_FILE = 262144


def _home(value: Path | None) -> Path:
    location = private_home_path(value)
    if not location.is_dir():
        raise ValueError("Private AthenZ profile directory does not exist")
    if os.name != "nt" and location.stat().st_mode & 0o077:
        raise ValueError("Private AthenZ directory must be owner-only")
    return location


def _path(home: Path | None) -> Path:
    return _home(home) / _FILENAME


def _observation(raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) != {
        "family", "choice", "context", "observed_on"
    }:
        raise ValueError("Invalid owner observation")
    for name in ("family", "choice", "context"):
        if type(raw[name]) is not str or not _PATTERN.fullmatch(raw[name]):
            raise ValueError("Observation uses invalid labels")
    observed = raw["observed_on"]
    if not isinstance(observed, str):
        raise ValueError("Invalid observation date")
    try:
        parsed = date.fromisoformat(observed)
    except ValueError:
        raise ValueError("Invalid observation date") from None
    if parsed.isoformat() != observed:
        raise ValueError("Observation dates must use YYYY-MM-DD")
    return {
        "family": raw["family"], "choice": raw["choice"],
        "context": raw["context"], "observed_on": observed,
    }


def _validate(data: object) -> list[dict]:
    if (not isinstance(data, dict) or set(data) != {"schema", "observations"}
            or type(data["schema"]) is not int or data["schema"] != 1
            or not isinstance(data["observations"], list)
            or len(data["observations"]) > _MAX_RECORDS):
        raise ValueError("Longitudinal journal is malformed or unsupported")
    seen: set[tuple[str, str, str]] = set()
    observations = []
    for raw in data["observations"]:
        row = _observation(raw)
        key = (row["family"], row["context"], row["observed_on"])
        if key in seen:
            raise ValueError("Duplicate family/context/day observation")
        seen.add(key)
        observations.append(row)
    return observations


def _load(path: Path) -> tuple[bytes, list[dict]]:
    raw = _read_private(path)
    if len(raw) > _MAX_FILE:
        raise ValueError("Private timeline file exceeds the size limit")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("Invalid private longitudinal JSON") from None
    return raw, _validate(data)


def initialize(home: Path | None) -> None:
    """Create an empty owner-only journal once; never overwrite any existing file."""
    location = _home(home)
    path = location / _FILENAME
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        raise ValueError("Private journal exists or cannot be created") from None
    with os.fdopen(fd, "wb") as stream:
        stream.write(b'{"schema":1,"observations":[]}\n')


def record(home: Path | None, *, family: str, choice: str,
           context: str, observed_on: str) -> None:
    """Write an explicitly approved observation with an exclusive local lock."""
    entry = _observation({
        "family": family, "choice": choice,
        "context": context, "observed_on": observed_on,
    })
    location = _home(home)
    path = location / _FILENAME
    lock = location / _LOCK
    lock_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock, lock_flags, 0o600)
    except OSError:
        raise ValueError("Longitudinal journal is currently locked") from None
    os.close(fd)
    temporary: Path | None = None
    try:
        original, rows = _load(path)
        if len(rows) >= _MAX_RECORDS:
            raise ValueError("Longitudinal journal is full")
        if any((row["family"], row["context"], row["observed_on"]) ==
               (entry["family"], entry["context"], entry["observed_on"])
               for row in rows):
            raise ValueError("Already recorded a decision for that family/context/day")
        body = (json.dumps(
            {"schema": 1, "observations": [*rows, entry]},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ) + "\n").encode("utf-8")
        if len(body) > _MAX_FILE:
            raise ValueError("Longitudinal journal exceeds the file size limit")
        temp_fd, temp_name = tempfile.mkstemp(prefix=".timeline-", dir=location)
        temporary = Path(temp_name)
        with os.fdopen(temp_fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        # Revalidate the old file before atomic swap. Cooperative writers
        # cannot interleave because both must own the exclusive lock.
        if _read_private(path) != original:
            raise ValueError("Journal changed during an owner-reviewed update")
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink(missing_ok=True)


def summarize(home: Path | None, *, min_days: int = 7) -> dict:
    """Compare consecutive, same-context owner choices separated in time.

    No text, labels, exact dates, record-level outcomes or group details leave
    the private journal. Small-cohort metrics are suppressed.
    """
    if type(min_days) is not int or not 1 <= min_days <= 365:
        raise ValueError("Choose a bounded minimum gap in days")
    _, observations = _load(_path(home))
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in observations:
        groups[(item["family"], item["context"])].append(item)
    pairs = 0
    matched = 0
    qualifying_families: set[str] = set()
    for (family, _context), items in groups.items():
        sorted_items = sorted(items, key=lambda item: item["observed_on"])
        for left, right in zip(sorted_items, sorted_items[1:]):
            interval = (date.fromisoformat(right["observed_on"]) -
                        date.fromisoformat(left["observed_on"])).days
            if interval < min_days:
                continue
            qualifying_families.add(family)
            pairs += 1
            matched += int(left["choice"] == right["choice"])
    # The number of repeats is not an independent-case sample size.
    reportable = pairs >= 5 and len(qualifying_families) >= 3
    return {
        "schema": 1,
        "kind": "owner-confirmed-time-separated-decision-consistency",
        "status": "reportable" if reportable else "insufficient-coverage",
        "min_days": min_days,
        "metrics_suppressed": not reportable,
        "compared_adjacent_pairs": pairs if reportable else None,
        "independent_families": len(qualifying_families) if reportable else None,
        "matching_choices": matched if reportable else None,
        "observed_agreement": matched / pairs if reportable else None,
        "names_choices_dates_or_contexts_in_report": False,
        "owner_decisions_independently_attested": False,
        "twin_predictive_fidelity_measured": False,
        "note": ("Consecutive within-context owner-reported choices only; "
                 "a change can reflect genuine preference evolution, "
                 "and even repeated families and observations are correlated."),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Private longitudinal owner decision journal")
    parser.add_argument("--home", type=Path)
    actions = parser.add_subparsers(dest="action", required=True)
    init = actions.add_parser("init", help="Create private empty journal")
    init.add_argument("--confirm", action="store_true")
    add = actions.add_parser("record", help="Owner-confirm one dated observation")
    add.add_argument("--family", required=True)
    add.add_argument("--choice", required=True)
    add.add_argument("--context", required=True)
    add.add_argument("--on", dest="observed_on", required=True)
    add.add_argument("--confirm", action="store_true")
    report = actions.add_parser("report", help="Private aggregate consistency report")
    report.add_argument("--min-days", type=int, default=7)
    args = parser.parse_args(argv)
    if args.action in {"init", "record"} and not args.confirm:
        parser.error("Explicit --confirm is required for owner data writes")
    try:
        if args.action == "init":
            initialize(args.home)
            print("Private longitudinal journal created. No model calls made.")
        elif args.action == "record":
            record(args.home, family=args.family, choice=args.choice,
                   context=args.context, observed_on=args.observed_on)
            print("Owner-confirmed observation stored privately.")
        else:
            print(json.dumps(summarize(args.home, min_days=args.min_days),
                             sort_keys=True))
    except (ValueError, OSError):
        raise SystemExit("Longitudinal journal operation refused; check private "
                         "path, permissions, schema, dates and owner review") from None


if __name__ == "__main__":
    main()
