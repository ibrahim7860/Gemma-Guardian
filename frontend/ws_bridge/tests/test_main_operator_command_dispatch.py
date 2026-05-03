"""Phase 4: ``operator_command_dispatch`` frames are republished to
``egs.operator_actions`` with ``kind=operator_command_dispatch``. The bridge
stamps ``bridge_received_at_iso_ms`` and the resulting envelope must validate
against the ``operator_actions`` schema (which has a ``oneOf`` over
``finding_approval`` and ``operator_command_dispatch`` discriminated by
``kind``).

Test harness convention (see plan section "Test harness convention for
Tasks 7-10"): uses ``httpx.AsyncClient`` + ``pytest_asyncio`` + ``httpx-ws``
instead of FastAPI's ``TestClient``. Single-loop ownership (FastAPI app +
WS transport + fakeredis client all on the same pytest-asyncio loop)
eliminates silent hangs and false-pass results.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

import pytest
from httpx_ws import aconnect_ws

from frontend.ws_bridge.tests._helpers import drain_until
from shared.contracts import validate


# ---- helpers ---------------------------------------------------------------


def _dispatch_frame(
    *,
    command_id: str = "abcd-1700000000000-7",
) -> Dict[str, Any]:
    return {
        "type": "operator_command_dispatch",
        "command_id": command_id,
        "contract_version": "1.0.0",
    }


# ---- tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_publishes_to_operator_actions(app_and_client):
    """A schema-valid ``operator_command_dispatch`` is acked AND republished
    onto ``egs.operator_actions`` with ``kind=operator_command_dispatch``.
    """
    app, http_client, fake = app_and_client

    pubsub = fake.pubsub()
    await pubsub.subscribe("egs.operator_actions")
    try:
        async with aconnect_ws("ws://testserver/", client=http_client) as ws:
            await ws.receive_text()  # initial state envelope
            await ws.send_text(json.dumps(_dispatch_frame()))
            ack = await drain_until(
                ws, lambda m: m.get("ack") == "operator_command_dispatch"
            )

        assert ack["type"] == "echo"
        assert ack["ack"] == "operator_command_dispatch"
        assert ack["command_id"] == "abcd-1700000000000-7"

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
            "expected a publish on egs.operator_actions"
        )
        assert published["kind"] == "operator_command_dispatch"
        assert published["command_id"] == "abcd-1700000000000-7"
        assert "bridge_received_at_iso_ms" in published
        assert published["bridge_received_at_iso_ms"].endswith("Z")

        # And the published envelope must validate against the operator_actions
        # schema (which oneOfs over finding_approval and operator_command_dispatch).
        outcome = validate("operator_actions", published)
        assert outcome.valid, outcome.errors
    finally:
        await pubsub.aclose()
