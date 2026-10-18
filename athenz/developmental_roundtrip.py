"""Explicit, one-shot AthenZ D2 synthetic transport choreography.

This module does not launch or trust an executable, provision credentials,
authorize humans, or execute a learner proposal. Binary streams are provided
by an owner-controlled caller; producer and transport keys are provisioned
out-of-band. Disabled by default. No arbitrary action/prompt payloads.
"""
from __future__ import annotations

import re
from typing import BinaryIO, Mapping

from .developmental_ack import SyntheticDeliveryAck
from .developmental_bridge import BridgeError, _validate
from .developmental_consent import SyntheticSourceRegistry
from .developmental_exchange import SyntheticExchange
from .developmental_pipe import athenz_handshake
from .developmental_receiver import SyntheticDurableReceiver

_SHA = re.compile(r"[a-f0-9]{64}\Z")


def synthetic_trace_roundtrip(
    reader: BinaryIO, writer: BinaryIO, *, root_secret: bytes,
    producer_keys: Mapping[str, bytes],
    registry: SyntheticSourceRegistry,
    receiver: SyntheticDurableReceiver,
    exchange: SyntheticExchange,
    request: dict,
    enabled: bool = False,
) -> dict:
    """Send one authorized synthetic SHA-only observation, receive/ACK two replies.

    No stream is opened or closed. Returned data has only synthetic metadata.
    A caller must explicitly manage peer lifecycle, pipe I/O timeouts and
    restart/reconnect behavior; a subprocess may not be trusted by address.
    """
    if enabled is not True:
        raise BridgeError("Synthetic D2 roundtrip is disabled")
    if (not isinstance(registry, SyntheticSourceRegistry)
            or not isinstance(receiver, SyntheticDurableReceiver)
            or not isinstance(exchange, SyntheticExchange)
            or not receiver.enabled or not exchange.enabled):
        raise BridgeError("Enabled private synthetic grants, receiver and outbox required")
    if set(producer_keys) != {"athenz", "learner"}:
        raise BridgeError("Separate signed event keys required")
    if (receiver.keys != dict(producer_keys) or exchange.keys != dict(producer_keys)
            or not callable(registry.is_current)):
        raise BridgeError("Synthetic D2 stores and transport keys do not match")
    if (registry.home != exchange.db_file_home or
            registry.home != receiver.db_file_home):
        raise BridgeError("D2 stores must share one private synthetic home")
    _validate(request, producer_keys)
    if (request["producer"] != "athenz" or request["kind"] != "observation"
            or request["payload"].get("signal") != "trace_sha256"
            or type(request["payload"].get("value")) is not str
            or not _SHA.fullmatch(request["payload"]["value"])
            or request["source_ref"] != "synthetic:interop"):
        raise BridgeError("Only the fixed trace-reference interoperability fixture is allowed")
    source, revision = request["source_ref"], request["source_revision"]
    if registry.is_current(source, revision) is not True:
        raise BridgeError("Synthetic roundtrip source approval unavailable")
    session = athenz_handshake(
        reader, writer, root_secret=root_secret, producer_keys=producer_keys,
        source_ref=source, source_revision=revision,
        revision_check=registry.is_current, enabled=True)
    # A failed send must not be mistaken for delivery. The peer has its
    # independent durable event journal, and will reject unauthorized content.
    session.send(writer, request)
    replies = []
    for expected_kind in ("action_proposed", "evaluation_receipt"):
        received = receiver.receive_frame(
            session, reader, expected_producer="learner", include_event=True,
            expected_task_id=request["task_id"],
            expected_kind=expected_kind,
            expected_source_ref=source,
            expected_source_revision=revision)
        event = received["event"]
        if (event["kind"] != expected_kind
                or event["task_id"] != request["task_id"]
                or event["source_ref"] != source
                or event["source_revision"] != revision):
            raise BridgeError("Synthetic learner reply is not bound to trace request")
        replies.append(event)
    # Strict pair validation commits the original source and both replies
    # before anything is acknowledged. If the peer dies before our ACK, the
    # same signed events remain re-deliverable in the peer outbox.
    staged = exchange.stage_pair(request, replies[0], replies[1])
    acknowledgments = SyntheticDeliveryAck(session, enabled=True)
    for event in replies:
        acknowledgments.send(writer, event, receiver)
    return {
        "status": staged["status"], "received_events": len(replies),
        "acknowledgments_sent": len(replies), "actions_executed": False,
    }
