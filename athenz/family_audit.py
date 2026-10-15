"""Private, owner-reviewed decision-family independence audit.

A manifest is *local owner data*, never a public repository asset. The owner
assigns broad categories and common family IDs to semantically equivalent
scenarios. Unlike automatic lexical checks this can flag paraphrases, but its
quality relies on correct independent owner review. No network or LLM needed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from collections import Counter

from .store import IdentityStore, private_home_path

_FILENAME = "decision-family-audit.json"
_CATEGORIES = frozenset({"work", "relationships", "planning", "creative", "other"})
_FAMILY = re.compile(r"[a-z][a-z0-9_-]{2,63}\Z")
_LIMIT = 2 * 1024 * 1024
_MIN_REPORT = 5


def _approved_rows(store: IdentityStore) -> list:
    return [dict(row) for row in store.db.execute(
        "SELECT id,scenario,choice,rationale,exception,options_json,source,"
        "source_ref,created_at,split,status FROM decisions "
        "WHERE status='approved' AND split IN ('train','calibration','test') "
        "ORDER BY id")]


def _digest(data: object) -> str:
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"),
                     sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _manifest_path(store: IdentityStore) -> Path:
    return private_home_path(store.home) / _FILENAME


def _read_private(path: Path) -> bytes:
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        raise ValueError("Family audit requires a regular private manifest")
    try:
        st = path.stat()
        if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or
                st.st_size > _LIMIT or
                (os.name != "nt" and st.st_mode & 0o077)):
            raise ValueError("Family audit manifest must be owner-only and bounded")
        # Guard against symlink replacement after stat: O_NOFOLLOW where present.
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            actual = os.fstat(fd)
            if (not stat.S_ISREG(actual.st_mode) or actual.st_nlink != 1
                    or actual.st_size > _LIMIT
                    or (os.name != "nt" and actual.st_mode & 0o077)):
                raise ValueError("Family audit manifest changed")
            with os.fdopen(fd, "rb", closefd=False) as handle:
                data = handle.read(_LIMIT + 1)
            if len(data) > _LIMIT:
                raise ValueError("Family audit manifest too large")
            return data
        finally:
            os.close(fd)
    except OSError:
        raise ValueError("Private family audit manifest cannot be read") from None


def create_family_template(store: IdentityStore) -> None:
    """Create once under ATHENZ_HOME, never overwrite manual labels."""
    path = _manifest_path(store)
    rows = _approved_rows(store)
    if not rows:
        raise ValueError("No approved decisions available for family review")
    payload = {"schema": 2, "approved_source_sha256": _digest(rows),
               "cases": [
        {"id": row["id"], "scenario": row["scenario"],
         "scenario_sha256": _digest(row["scenario"]), "split": row["split"],
         "family": "", "category": ""}
        for row in rows]}
    body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(body) > _LIMIT:
        raise ValueError("Family template exceeds private size limit")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        raise ValueError("Family template already exists or private path is invalid") from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class FamilyAudit:
    """Immutable audit plan; verify() fails closed on any source-file drift."""

    def __init__(self, store: IdentityStore):
        self.path = _manifest_path(store)
        rows = _approved_rows(store)
        if not rows:
            raise ValueError("Family audit needs approved decisions")
        self.source_sha = _digest(rows)
        raw = _read_private(self.path)
        self.manifest_sha = hashlib.sha256(raw).hexdigest()
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise ValueError("Family audit manifest is invalid JSON") from None
        if (not isinstance(manifest, dict)
                or set(manifest) != {"schema", "cases", "approved_source_sha256"}
                or type(manifest["schema"]) is not int or manifest["schema"] != 2
                or manifest["approved_source_sha256"] != self.source_sha
                or not isinstance(manifest["cases"], list)
                or len(manifest["cases"]) != len(rows)):
            raise ValueError("Family audit manifest is incomplete or stale")

        expected = {row["id"]: row for row in rows}
        self.by_id: dict[int, str] = {}
        families: dict[str, str] = {}
        heldout: set[tuple[str, str]] = set()
        for item in manifest["cases"]:
            if (not isinstance(item, dict) or
                    set(item) != {"id", "scenario", "scenario_sha256",
                                  "split", "family", "category"}
                    or type(item["id"]) is not int or item["id"] not in expected
                    or item["id"] in self.by_id):
                raise ValueError("Family audit contains duplicate or unknown decisions")
            row = expected[item["id"]]
            if (item["scenario"] != row["scenario"]
                    or item["scenario_sha256"] != _digest(row["scenario"])
                    or item["split"] != row["split"]
                    or not isinstance(item["category"], str)
                    or not isinstance(item["family"], str)
                    or _FAMILY.fullmatch(item["family"]) is None
                    or item["category"] not in _CATEGORIES):
                raise ValueError("Family audit contains stale or unreviewed labels")
            family = item["family"]
            prior_split = families.setdefault(family, row["split"])
            if prior_split != row["split"]:
                raise ValueError("Family audit finds a cross-split related decision")
            if row["split"] in {"calibration", "test"}:
                key = (row["split"], family)
                if key in heldout:
                    raise ValueError("Family audit finds repeated held-out families")
                heldout.add(key)
            self.by_id[item["id"]] = item["category"]
        self.audited_records = len(rows)

    def verify(self, store: IdentityStore) -> None:
        if (self.source_sha != _digest(_approved_rows(store)) or
                self.manifest_sha != hashlib.sha256(
                    _read_private(self.path)).hexdigest()):
            raise ValueError("Family audit sources or owner labels changed; discard results")

    def selected_categories(self, case_ids: list[int]) -> dict[int, str]:
        if any(type(i) is not int or i not in self.by_id for i in case_ids):
            raise ValueError("Family audit does not cover selected decisions")
        return {i: self.by_id[i] for i in case_ids}


def category_diversity_gate(categories: dict[int, str]) -> bool:
    """Opt-in broad, reviewed held-out category coverage requirement.

    At least three non-catchall categories with five independent cases each;
    no sparse tail categories, and no category exceeds 60% of selected cases.
    This is a study-design safeguard, not a claim of personality fidelity.
    """
    if not isinstance(categories, dict):
        raise ValueError("Invalid category selection")
    if any(type(i) is not int or type(category) is not str
           or category not in _CATEGORIES
           for i, category in categories.items()):
        raise ValueError("Invalid reviewed category labels")
    totals = Counter(categories.values())
    n = len(categories)
    return (n >= 15 and len(totals) >= 3
            and "other" not in totals
            and all(size >= _MIN_REPORT for size in totals.values())
            and max(totals.values(), default=0) * 5 <= n * 3)


class CategoryScores:
    """Aggregate category scores, with small categories always suppressed."""

    def __init__(self) -> None:
        self._groups: dict[str, list[int]] = {}

    def add(self, category: str, *, twin_correct: bool, neutral_correct: bool) -> None:
        if category not in _CATEGORIES or type(twin_correct) is not bool or type(neutral_correct) is not bool:
            raise ValueError("Invalid family category result")
        counts = self._groups.setdefault(category, [0, 0, 0])
        counts[0] += 1
        counts[1] += int(twin_correct)
        counts[2] += int(neutral_correct)

    def report(self, audited_records: int) -> dict:
        visible = {
            category: {"cases": n, "twin_correct": twin, "neutral_correct": neutral,
                       "twin_accuracy": twin / n, "neutral_accuracy": neutral / n}
            for category, (n, twin, neutral) in sorted(self._groups.items())
            if n >= _MIN_REPORT
        }
        # Equal category weight guards against a large topic dominating micro
        # accuracy. Only published categories with >=5 cases contribute.
        eligible = list(visible.values())
        macro_twin = (sum(v["twin_accuracy"] for v in eligible) / len(eligible)
                      if len(eligible) >= 3 else None)
        macro_neutral = (sum(v["neutral_accuracy"] for v in eligible) / len(eligible)
                         if len(eligible) >= 3 else None)
        groups = {name: totals[0] for name, totals in self._groups.items()}
        selected = sum(groups.values())
        broad = (selected >= 15 and len(groups) >= 3
                 and "other" not in groups
                 and all(count >= _MIN_REPORT for count in groups.values())
                 and max(groups.values(), default=0) * 5 <= selected * 3)
        return {
            "enabled": True,
            "approved_records_audited": audited_records,
            "broad_coverage_gate_met": broad,
            "eligible_category_count": len(eligible),
            "macro_twin_accuracy": macro_twin,
            "macro_neutral_accuracy": macro_neutral,
            "macro_paired_accuracy_difference": (
                macro_twin - macro_neutral if macro_twin is not None else None),
            "selected_cases": sum(x[0] for x in self._groups.values()),
            "category_metrics_minimum_cases": _MIN_REPORT,
            "category_metrics": visible,
            "small_categories_suppressed": len(self._groups) - len(visible),
            "semantic_independence_certified": False,
        }
