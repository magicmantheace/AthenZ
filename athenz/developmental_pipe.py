"""Explicit synthetic D2 mutual-key handshake over caller-owned binary streams.

No socket listener, process launch, key provisioning, owner authentication or
tool execution. Each caller supplies an independently protected pre-shared
secret and separately signed event-producer keys. OFF by default.
"""
from __future__ import annotations

import json
import struct
from typing import BinaryIO, Callable, Mapping

from .developmental_bridge import BridgeError, _canonical
from .developmental_frames import SyntheticFrameSession, _read_exact
from .developmental_handshake import initiate, respond, finalize, accept

_HANDSHAKE_LIMIT = 512


def _send(stream: BinaryIO, message: dict) -> None:
    raw = _canonical(message)
    if not 1 <= len(raw) <= _HANDSHAKE_LIMIT:
        raise BridgeError("Synthetic D2 handshake record too large")
    packet = struct.pack("!H", len(raw)) + raw
    try:
        sent = stream.write(packet)
        if sent == len(packet):
            stream.flush()
    except (OSError, ValueError, AttributeError) as exc:
        raise BridgeError("Synthetic D2 handshake stream write failed") from exc
    if sent != len(packet):
        raise BridgeError("Synthetic D2 handshake short stream write")


def _receive(stream: BinaryIO) -> dict:
    size = struct.unpack("!H", _read_exact(stream, 2))[0]
    if size < 1 or size > _HANDSHAKE_LIMIT:
        raise BridgeError("Synthetic D2 handshake exceeds strict length limit")
    raw = _read_exact(stream, size)
    try:
        record = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise BridgeError("Malformed synthetic D2 handshake JSON") from exc
    if type(record) is not dict or _canonical(record) != raw:
        raise BridgeError("Noncanonical synthetic D2 handshake")
    return record


def athenz_handshake(reader: BinaryIO, writer: BinaryIO, *,
                     root_secret: bytes, producer_keys: Mapping[str, bytes],
                     source_ref: str, source_revision: int,
                     revision_check: Callable[[str, int], bool],
                     enabled: bool = False) -> SyntheticFrameSession:
    """Perform one client hello, peer proof, client confirmation on binary IO."""
    if not enabled:
        raise BridgeError("D2 pipe handshake is disabled")
    hello = initiate(source_ref, source_revision)
    _send(writer, hello)
    reply = _receive(reader)
    confirmation, material = finalize(
        hello, reply, root_secret=root_secret, revision_check=revision_check)
    _send(writer, confirmation)
    return SyntheticFrameSession(
        **material, producer_keys=producer_keys,
        revision_check=revision_check, enabled=True)


def learner_handshake(reader: BinaryIO, writer: BinaryIO, *,
                      root_secret: bytes, producer_keys: Mapping[str, bytes],
                      revision_check: Callable[[str, int], bool],
                      enabled: bool = False) -> SyntheticFrameSession:
    """Verify client challenge, reply and final client proof over binary IO."""
    if not enabled:
        raise BridgeError("D2 pipe handshake is disabled")
    hello = _receive(reader)
    reply = respond(hello, root_secret=root_secret, revision_check=revision_check)
    _send(writer, reply)
    confirmation = _receive(reader)
    material = accept(
        hello, reply, confirmation,
        root_secret=root_secret, revision_check=revision_check)
    return SyntheticFrameSession(
        **material, producer_keys=producer_keys,
        revision_check=revision_check, enabled=True)
