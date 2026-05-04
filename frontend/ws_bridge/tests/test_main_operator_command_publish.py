"""Phase 4: ``operator_command`` frames are republished to
``egs.operator_commands`` after schema validation. The bridge stamps
``bridge_received_at_iso_ms`` and the resulting envelope must validate
against the ``operator_commands_envelope`` schema. A schema-invalid
inbound frame must echo ``invalid_operator_command`` and never reach
Redis.

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
from shared.contracts import validate


# ---- helpers ---------------------------------------------------------------


def _command_frame(
    *,
    command_id: str = "abcd-1700000000000-3",
    language: str = "en",
    raw_text: str = "recall drone1 to base",
    drop_raw_text: bool = False,
) -> Dict[str, Any]:
    frame: Dict[str, Any] = {
        "type": "operator_command",
        "command_id": command_id,
        "language": language,
        "raw_text": raw_text,
        "contract_version": "1.0.0",
    }
    if drop_raw_text:
        frame.pop("raw_text")
    return frame


# ---- tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_operator_command_publishes_envelope(app_and_redis):
    """A schema-valid ``operator_command`` is acked AND republished onto
    ``egs.operator_commands`` as a stamped ``operator_commands_envelope``.
    """
    app, fake = app_and_redis

    pubsub = fake.pubsub()
    await pubsub.subscribe("egs.operator_commands")
    try:
        async with make_test_client(app) as http_client:
            async with aconnect_ws("ws://testserver/", client=http_client) as ws:
                await ws.receive_text()  # initial state envelope
                await ws.send_text(json.dumps(_command_frame()))
                ack = await drain_until(
                    ws, lambda m: m.get("ack") == "operator_command_received"
                )

        assert ack["type"] == "echo"
        assert ack["ack"] == "operator_command_received"
        assert ack["command_id"] == "abcd-1700000000000-3"

        # And the bridge should have actually published the envelope.
        published = None
        for _ in range(40):
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=0.05
            )
            if msg is not None:
                published = json.loads(msg["data"])
                break
            await asyncio.sleep(0.01)

        assert published is not None, (
            "expected a publish on egs.operator_commands"
        )
        assert published["kind"] == "operator_command"
        assert published["command_id"] == "abcd-1700000000000-3"
        assert published["language"] == "en"
        assert published["raw_text"] == "recall drone1 to base"
        assert "bridge_received_at_iso_ms" in published
        assert published["bridge_received_at_iso_ms"].endswith("Z")

        # And the published envelope must validate against its own schema.
        outcome = validate("operator_commands_envelope", published)
        assert outcome.valid, outcome.errors
    finally:
        await pubsub.aclose()


@pytest.mark.asyncio
async def test_invalid_operator_command_no_publish(app_and_redis):
    """A schema-invalid ``operator_command`` (missing ``raw_text``) must
    echo ``invalid_operator_command`` and must NOT publish to Redis.
    """
    app, fake = app_and_redis

    pubsub = fake.pubsub()
    await pubsub.subscribe("egs.operator_commands")
    try:
        async with make_test_client(app) as http_client:
            async with aconnect_ws("ws://testserver/", client=http_client) as ws:
                await ws.receive_text()  # initial state envelope
                await ws.send_text(json.dumps(_command_frame(drop_raw_text=True)))
                echo = await drain_until(
                    ws, lambda m: m.get("error") == "invalid_operator_command"
                )

        assert echo["type"] == "echo"
        assert echo["error"] == "invalid_operator_command"
        assert echo["command_id"] == "abcd-1700000000000-3"

        # Nothing should have been published. Poll briefly to make sure no
        # message landed on the channel.
        for _ in range(10):
            msg = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=0.05
            )
            assert msg is None, (
                f"unexpected publish on egs.operator_commands: {msg!r}"
            )
            await asyncio.sleep(0.01)
    finally:
        await pubsub.aclose()
