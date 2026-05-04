"""Phase 4: the bridge must reject ``finding_approval`` frames whose
``finding_id`` is not in the aggregator's known set, before republishing
to Redis.

Closes the Phase 3 adversarial-review finding that any well-formed
``finding_id`` was being republished verbatim.

Test harness convention (see plan section "Test harness convention for
Tasks 7-10"): uses ``httpx.AsyncClient`` + ``pytest_asyncio`` + ``httpx-ws``
instead of FastAPI's ``TestClient``. The TestClient pattern binds
``fakeredis.aioredis.FakeRedis()`` to one event loop while the test
publishes / awaits on another, which yields silent hangs or false-pass
results. Single-loop ownership (FastAPI app + WS transport + fakeredis
client all on the same pytest-asyncio loop) eliminates that class of bug.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

import pytest
from httpx_ws import aconnect_ws

from frontend.ws_bridge.tests._helpers import drain_until, make_test_client


# ---- helpers ---------------------------------------------------------------


def _approval_frame(
    finding_id: str, command_id: str = "abcd-1700000000000-1"
) -> Dict[str, Any]:
    return {
        "type": "finding_approval",
        "command_id": command_id,
        "finding_id": finding_id,
        "action": "approve",
        "contract_version": "1.0.0",
    }


_KNOWN_FINDING: Dict[str, Any] = {
    "finding_id": "f_drone1_5",
    "source_drone_id": "drone1",
    "timestamp": "2026-05-02T12:00:00.000Z",
    "type": "victim",
    "severity": 4,
    "gps_lat": 34.12,
    "gps_lon": -118.56,
    "altitude": 0,
    "confidence": 0.8,
    "visual_description": "person prone in debris",
    "image_path": "/tmp/x.jpg",
    "validated": True,
    "validation_retries": 0,
    "operator_status": "pending",
}


# ---- tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_finding_id_returns_echo_error_and_no_publish(
    app_and_redis,
):
    """An approval for a finding_id the aggregator doesn't know about must
    be rejected with an ``unknown_finding_id`` echo error, and nothing
    must be published to ``egs.operator_actions``.
    """
    app, fake = app_and_redis

    pubsub = fake.pubsub()
    await pubsub.subscribe("egs.operator_actions")
    try:
        async with make_test_client(app) as http_client:
            async with aconnect_ws("ws://testserver/", client=http_client) as ws:
                # Drain initial state envelope.
                await ws.receive_text()
                await ws.send_text(json.dumps(_approval_frame("f_drone99_999")))
                echo = await drain_until(
                    ws, lambda m: m.get("error") == "unknown_finding_id"
                )

        assert echo["type"] == "echo"
        assert echo["error"] == "unknown_finding_id"
        assert echo["finding_id"] == "f_drone99_999"
        assert echo["command_id"] == "abcd-1700000000000-1"

        # Nothing should have been published. Poll briefly to make sure no
        # message landed on the channel.
        for _ in range(10):
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=0.05
            )
            assert msg is None, (
                f"unexpected publish on egs.operator_actions: {msg!r}"
            )
            await asyncio.sleep(0.01)
    finally:
        await pubsub.aclose()


@pytest.mark.asyncio
async def test_known_finding_id_publishes_normally(app_and_redis):
    """Positive case: an approval for a finding the aggregator knows about
    is acked AND republished onto ``egs.operator_actions``.
    """
    app, fake = app_and_redis

    # Seed the aggregator directly so the allowlist contains this id.
    app.state.aggregator.add_finding(_KNOWN_FINDING)

    pubsub = fake.pubsub()
    await pubsub.subscribe("egs.operator_actions")
    try:
        async with make_test_client(app) as http_client:
            async with aconnect_ws("ws://testserver/", client=http_client) as ws:
                await ws.receive_text()  # initial state envelope
                await ws.send_text(json.dumps(_approval_frame("f_drone1_5")))
                ack = await drain_until(
                    ws, lambda m: m.get("ack") == "finding_approval"
                )

        assert ack["type"] == "echo"
        assert ack["ack"] == "finding_approval"
        assert ack["finding_id"] == "f_drone1_5"
        assert ack["command_id"] == "abcd-1700000000000-1"

        # And the bridge should have actually published the action.
        published = None
        for _ in range(40):
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=0.05
            )
            if msg is not None:
                published = json.loads(msg["data"])
                break
            await asyncio.sleep(0.01)

        assert published is not None, "expected a publish on egs.operator_actions"
        assert published["kind"] == "finding_approval"
        assert published["finding_id"] == "f_drone1_5"
        assert published["command_id"] == "abcd-1700000000000-1"
        assert published["action"] == "approve"
        assert published["bridge_received_at_iso_ms"].endswith("Z")
    finally:
        await pubsub.aclose()
