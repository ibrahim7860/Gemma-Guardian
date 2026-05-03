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

import fakeredis.aioredis as fakeredis_async
import httpx
import pytest
import pytest_asyncio
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport

from shared.contracts import validate


# ---- fixtures --------------------------------------------------------------


@pytest_asyncio.fixture
async def fake_client():
    """A fakeredis client bound to the running pytest-asyncio loop."""
    client = fakeredis_async.FakeRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def app_and_client(monkeypatch, fake_client):
    """Start the bridge with a fakeredis-backed publisher + subscriber on
    the running loop.

    Patches ``redis.asyncio.Redis.from_url`` to return ``fake_client`` so the
    bridge's ``RedisPublisher`` and ``RedisSubscriber`` share state with the
    test's pubsub. Drives FastAPI lifespan manually via
    ``app.router.lifespan_context`` so subscriber/emit tasks start on the
    same loop the test runs on.
    """
    import redis.asyncio as redis_async

    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )

    # Import after the patch so any module-level client construction picks
    # up the fakeredis factory.
    from frontend.ws_bridge.main import create_app

    app = create_app()
    transport = ASGIWebSocketTransport(app=app)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    )
    async with app.router.lifespan_context(app):
        try:
            yield app, client, fake_client
        finally:
            # Deviation note: ``ASGIWebSocketTransport`` retains a per-WS
            # ``exit_stack`` whose anyio cancel scope was entered inside the
            # ``aconnect_ws`` task. If we let ``httpx.AsyncClient.aclose()``
            # re-enter that stack from the fixture's task, anyio raises
            # "Attempted to exit cancel scope in a different task". The
            # ``aconnect_ws`` context manager has already drained the
            # network stream by the time it exits, so the residual
            # ``exit_stack`` has no real cleanup left to do — clear it
            # from the same task that owns it before AsyncClient teardown.
            transport.exit_stack = None
            await client.aclose()


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


async def _drain_until(ws, predicate, *, max_frames: int = 10) -> Dict[str, Any]:
    """Receive frames until ``predicate(msg)`` is True. Skips state_update
    frames emitted by ``_emit_loop``.
    """
    for _ in range(max_frames):
        raw = await ws.receive_text()
        msg = json.loads(raw)
        if predicate(msg):
            return msg
    raise AssertionError(
        f"no frame matched predicate after {max_frames} frames"
    )


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
            ack = await _drain_until(
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
