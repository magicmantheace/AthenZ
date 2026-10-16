"""Opt-in, owner-private frozen final-test protocol (not a training artifact).

The unmodified private plan binds the owner-approved held-out sample,
all approved decision/reference evidence, local model digest, and evaluation
settings before a final test. No private scenarios/choices enter the plan.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from .evaluation import (
    _fingerprint, _heldout_prompt_messages, _heldout_rows,
    _reference_fingerprint, _reject_overlapping_decision_splits,
    _reject_repeated_heldout_scenarios,
)
from .family_audit import (
    FamilyAudit, _approved_rows, _digest, _read_private,
    category_diversity_gate,
)
from .store import IdentityStore, private_home_path
from .paired_stats import SelectiveConfidenceAccumulator

_FILENAME = "decision-final-test-plan.json"
_DIGEST = re.compile(r"[a-fA-F0-9]{64}\Z")
_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SOURCE_MODULES = (
    "paired_decisions.py", "evaluation.py", "family_audit.py",
    "paired_stats.py", "prompting.py", "chat.py", "runtime.py",
    "store.py", "frozen_decision_plan.py",
)
_KEYS = frozenset({
    "limit", "seed", "allow_abstain", "score_confidence", "confidence_cutoff",
    "family_audit",
    "require_category_diversity", "stability_trials",
})


def _implementation_digest() -> str:
    """Fingerprint directly involved local source implementations.

    This is a change detector, not a signature or trusted software attestation.
    """
    directory = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in _SOURCE_MODULES:
        path = directory / name
        try:
            content = path.read_bytes()
        except OSError:
            raise ValueError("Frozen study code fingerprint unavailable") from None
        digest.update(name.encode("ascii") + b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _path(store: IdentityStore) -> Path:
    return private_home_path(store.home) / _FILENAME


def _settings(**kw) -> dict:
    if set(kw) != _KEYS:
        raise ValueError("Frozen study settings are incomplete")
    if (type(kw["limit"]) is not int or not 1 <= kw["limit"] <= 1000
            or type(kw["seed"]) is not int or not 0 <= kw["seed"] < 2 ** 32
            or any(type(kw[k]) is not bool for k in (
                "allow_abstain", "score_confidence", "family_audit",
                "require_category_diversity"))
            or type(kw["stability_trials"]) is not int
            or not 1 <= kw["stability_trials"] <= 3
            or kw["limit"] * kw["stability_trials"] > 300
            or (kw["confidence_cutoff"] is not None
                and (not kw["score_confidence"]
                     or SelectiveConfidenceAccumulator.validate_cutoff(
                         kw["confidence_cutoff"]) is None))
            or (kw["allow_abstain"] and kw["score_confidence"])
            or (kw["require_category_diversity"] and not kw["family_audit"])):
        raise ValueError("Invalid frozen test settings or excessive local workload")
    return dict(kw)


def _evidence(store: IdentityStore, settings: dict, *,
              preflight: bool = True) -> tuple[dict, FamilyAudit | None]:
    _reject_overlapping_decision_splits(store)
    _reject_repeated_heldout_scenarios(store, "test", settings["limit"])
    rows = _heldout_rows(store, "test", settings["limit"])
    if not rows:
        raise ValueError("Final test needs approved, independent held-out decisions")
    audit = FamilyAudit(store) if settings["family_audit"] else None
    if audit is not None:
        audit.verify(store)
        cats = audit.selected_categories([r[0] for r in rows])
        if settings["require_category_diversity"] and not category_diversity_gate(cats):
            raise ValueError("Final study needs balanced reviewed decision categories")
    if preflight:
        for row in rows:
            for index in range(settings["stability_trials"]):
                seed = (settings["seed"] + index * 1_000_003) % (2 ** 32)
                _heldout_prompt_messages(store, row, seed)
    data = {
        "heldout_sha256": _fingerprint(rows),
        "reference_sha256": _reference_fingerprint(store),
        "all_approved_decisions_sha256": _digest(_approved_rows(store)),
        "review_sha256": audit.manifest_sha if audit is not None else None,
        "selected_count": len(rows),
    }
    return data, audit


def _validate_model(model_tag: str, model_digest: str) -> None:
    if (type(model_tag) is not str or _TAG.fullmatch(model_tag) is None
            or type(model_digest) is not str
            or _DIGEST.fullmatch(model_digest) is None):
        raise ValueError("Final test needs one identified local model/digest")


def freeze_test_plan(store: IdentityStore, *, model_tag: str, model_digest: str,
                     **options) -> None:
    """Create exactly once, with owner confirmation enforced by the caller."""
    settings = _settings(**options)
    _validate_model(model_tag, model_digest)
    first, _audit = _evidence(store, settings)
    payload = {
        "schema": 1, "kind": "owner-frozen-twin-final-decision-study",
        "model_tag": model_tag, "model_digest": model_digest,
        "settings": settings, "evidence": first,
        "implementation_sha256": _implementation_digest(),
    }
    if first != _evidence(store, settings)[0]:
        raise ValueError("Final test source changed during freezing")
    body = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    path = _path(store)
    flags = os.O_WRONLY | os.O_EXCL | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError:
        raise ValueError("Private final plan exists or cannot be written") from None
    try:
        with os.fdopen(fd, "wb") as writer:
            writer.write(body)
            writer.flush()
            os.fsync(writer.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


class FrozenTestPlan:
    """Verify immutable plan bytes, exact model/settings and source snapshots."""

    def __init__(self, store: IdentityStore):
        self.path = _path(store)
        raw = _read_private(self.path)
        if len(raw) > 8192:
            raise ValueError("Final plan exceeds bounded size")
        self.plan_sha256 = hashlib.sha256(raw).hexdigest()
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise ValueError("Malformed private final-test plan") from None
        if (not isinstance(payload, dict) or set(payload) != {
                "schema", "kind", "model_tag", "model_digest", "settings",
                "evidence", "implementation_sha256"}
                or type(payload["schema"]) is not int or payload["schema"] != 1
                or payload["kind"] != "owner-frozen-twin-final-decision-study"
                or not isinstance(payload["settings"], dict)
                or set(payload["settings"]) != _KEYS
                or not isinstance(payload["evidence"], dict)
                or set(payload["evidence"]) != {
                    "heldout_sha256", "reference_sha256",
                    "all_approved_decisions_sha256", "review_sha256",
                    "selected_count"}):
            raise ValueError("Unsupported or incomplete private final-test plan")
        _validate_model(payload["model_tag"], payload["model_digest"])
        if (type(payload["implementation_sha256"]) is not str or
                _DIGEST.fullmatch(payload["implementation_sha256"]) is None):
            raise ValueError("Invalid frozen study implementation fingerprint")
        self.settings = _settings(**payload["settings"])
        ev = payload["evidence"]
        if (any(type(ev[k]) is not str or _DIGEST.fullmatch(ev[k]) is None
                for k in ("heldout_sha256", "reference_sha256",
                          "all_approved_decisions_sha256"))
                or (ev["review_sha256"] is not None and
                    (type(ev["review_sha256"]) is not str or
                     _DIGEST.fullmatch(ev["review_sha256"]) is None))
                or (ev["review_sha256"] is None) == self.settings["family_audit"]
                or type(ev["selected_count"]) is not int
                or not 1 <= ev["selected_count"] <= self.settings["limit"]):
            raise ValueError("Invalid frozen evidence fingerprints")
        self.payload = payload

    def verify(self, store: IdentityStore, *, model_tag: str,
               model_digest: str, **options) -> None:
        _validate_model(model_tag, model_digest)
        if (self.payload["model_tag"] != model_tag
                or self.payload["model_digest"] != model_digest
                or self.settings != _settings(**options)
                or self.payload["implementation_sha256"] != _implementation_digest()):
            raise ValueError("Final-test model or protocol does not match frozen plan")
        raw = _read_private(self.path)
        if hashlib.sha256(raw).hexdigest() != self.plan_sha256:
            raise ValueError("Frozen test-plan bytes changed during evaluation")
        current, _ = _evidence(store, self.settings, preflight=False)
        if current != self.payload["evidence"]:
            raise ValueError("Approved final-test evidence changed since freezing")
