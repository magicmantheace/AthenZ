"""Synthetic-only D2 mutual-key challenge-response, with domain-separated frame keys.

Pure Python object exchange; no listener, subprocess, key storage, owner
authentication, real permission, OS peer attestation or private user content.
A protected pre-shared transport secret MUST be provisioned separately.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Callable

from .developmental_bridge import BridgeError, _canonical, _key
from .developmental_consent import _source

HELLO_SCHEMA = "athenz.d2.synthetic-hello/v1"
_HELLO_KEYS = frozenset(("schema", "sender", "source_ref",
                         "source_revision", "athenz_nonce"))
_REPLY_KEYS = frozenset(("schema", "sender", "athenz_nonce",
                         "learner_nonce", "proof"))
_CONFIRM_KEYS = frozenset(("schema", "sender", "athenz_nonce",
                           "learner_nonce", "proof"))
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_MAC = re.compile(r"[0-9a-f]{64}\Z")


def _valid_nonce(value: object) -> None:
    if type(value) is not str or not _NONCE.fullmatch(value):
        raise BridgeError("Invalid D2 handshake nonce")


def _auth(root: bytes, role: bytes, transcript: bytes) -> str:
    return hmac.new(root, b"athenz/d2/handshake/v1/" + role + b"/" + transcript,
                    hashlib.sha256).hexdigest()


def _approved(callback: Callable[[str, int], bool], hello: dict) -> None:
    if not callable(callback):
        raise BridgeError("D2 handshake requires approved synthetic source checker")
    try:
        result = callback(hello["source_ref"], hello["source_revision"]) is True
    except Exception as exc:
        raise BridgeError("D2 handshake synthetic grant check failed") from exc
    if not result:
        raise BridgeError("D2 handshake synthetic source not approved")


def _check_hello(hello: dict) -> None:
    if type(hello) is not dict or set(hello) != _HELLO_KEYS:
        raise BridgeError("Unsupported D2 handshake hello")
    if hello["schema"] != HELLO_SCHEMA or hello["sender"] != "athenz":
        raise BridgeError("Unexpected D2 handshake version or initiator")
    _source(hello["source_ref"])
    if (type(hello["source_revision"]) is not int
            or not 1 <= hello["source_revision"] <= 1000000):
        raise BridgeError("Invalid D2 handshake grant revision")
    _valid_nonce(hello["athenz_nonce"])


def _response_body(hello: dict, reply: dict) -> dict:
    if type(reply) is not dict or set(reply) != _REPLY_KEYS:
        raise BridgeError("Unsupported D2 handshake reply")
    if (reply["schema"] != HELLO_SCHEMA or reply["sender"] != "learner"
            or reply["athenz_nonce"] != hello["athenz_nonce"]):
        raise BridgeError("D2 handshake reply does not match its challenge")
    _valid_nonce(reply["learner_nonce"])
    if reply["learner_nonce"] == hello["athenz_nonce"]:
        raise BridgeError("D2 handshake nonces must differ")
    if type(reply["proof"]) is not str or not _MAC.fullmatch(reply["proof"]):
        raise BridgeError("Malformed D2 learner authentication")
    return {
        "schema": HELLO_SCHEMA,
        "source_ref": hello["source_ref"],
        "source_revision": hello["source_revision"],
        "athenz_nonce": hello["athenz_nonce"],
        "learner_nonce": reply["learner_nonce"],
    }


def _transcript(hello: dict, reply: dict) -> bytes:
    return _canonical(_response_body(hello, reply))


def initiate(source_ref: str, source_revision: int) -> dict:
    """Produce a 128-bit unpredictable client nonce (no external effects)."""
    _source(source_ref)
    if type(source_revision) is not int or not 1 <= source_revision <= 1000000:
        raise BridgeError("Invalid D2 handshake grant revision")
    return {"schema": HELLO_SCHEMA, "sender": "athenz",
            "source_ref": source_ref, "source_revision": source_revision,
            "athenz_nonce": secrets.token_hex(16)}


def respond(hello: dict, *, root_secret: bytes,
            revision_check: Callable[[str, int], bool]) -> dict:
    """Learner proves possession of a separately provisioned shared key."""
    _key(root_secret)
    _check_hello(hello)
    _approved(revision_check, hello)
    nonce = secrets.token_hex(16)
    while nonce == hello["athenz_nonce"]:
        nonce = secrets.token_hex(16)
    reply = {"schema": HELLO_SCHEMA, "sender": "learner",
             "athenz_nonce": hello["athenz_nonce"],
             "learner_nonce": nonce}
    return {**reply, "proof": _auth(
        root_secret, b"learner", _canonical({
            "schema": HELLO_SCHEMA, "source_ref": hello["source_ref"],
            "source_revision": hello["source_revision"],
            "athenz_nonce": hello["athenz_nonce"], "learner_nonce": nonce,
        }))}


def _material(root_secret: bytes, transcript: bytes) -> dict:
    """Derive ephemeral keys from the transcript; do not log the result."""
    def derive(label: bytes) -> bytes:
        return hmac.new(root_secret,
                        b"athenz/d2/session/v1/" + label + b"/" + transcript,
                        hashlib.sha256).digest()
    return {
        "session_id": derive(b"session").hex()[:32],
        "frame_keys": {
            "athenz": derive(b"frame/athenz"),
            "learner": derive(b"frame/learner"),
        },
    }


def finalize(hello: dict, reply: dict, *, root_secret: bytes,
             revision_check: Callable[[str, int], bool]) -> tuple[dict, dict]:
    """AthenZ verifies learner proof, returns authentication plus local keys."""
    _key(root_secret)
    _check_hello(hello)
    transcript = _transcript(hello, reply)
    expected = _auth(root_secret, b"learner", transcript)
    if not hmac.compare_digest(expected, reply["proof"]):
        raise BridgeError("D2 learner proof authentication failed")
    _approved(revision_check, hello)
    confirmation = {
        "schema": HELLO_SCHEMA, "sender": "athenz",
        "athenz_nonce": hello["athenz_nonce"],
        "learner_nonce": reply["learner_nonce"],
        "proof": _auth(root_secret, b"athenz", transcript),
    }
    return confirmation, _material(root_secret, transcript)


def accept(hello: dict, reply: dict, confirmation: dict, *,
           root_secret: bytes,
           revision_check: Callable[[str, int], bool]) -> dict:
    """Learner verifies client key possession and current synthetic source."""
    _key(root_secret)
    _check_hello(hello)
    transcript = _transcript(hello, reply)
    learner_proof = _auth(root_secret, b"learner", transcript)
    if not hmac.compare_digest(learner_proof, reply["proof"]):
        raise BridgeError("D2 learner reply authentication failed")
    if type(confirmation) is not dict or set(confirmation) != _CONFIRM_KEYS:
        raise BridgeError("Unsupported D2 client confirmation")
    if (confirmation["schema"] != HELLO_SCHEMA
            or confirmation["sender"] != "athenz"
            or confirmation["athenz_nonce"] != hello["athenz_nonce"]
            or confirmation["learner_nonce"] != reply["learner_nonce"]
            or type(confirmation["proof"]) is not str
            or not _MAC.fullmatch(confirmation["proof"])):
        raise BridgeError("D2 client confirmation mismatch")
    expected = _auth(root_secret, b"athenz", transcript)
    if not hmac.compare_digest(expected, confirmation["proof"]):
        raise BridgeError("D2 AthenZ authentication failed")
    _approved(revision_check, hello)
    return _material(root_secret, transcript)
