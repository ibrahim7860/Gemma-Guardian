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

import fakeredis.aioredis as fakeredis_async
import httpx
import pytest
import pytest_asyncio
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport


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
async def test_unknown_finding_id_returns_echo_error_and_no_publish(
    app_and_client,
):
    """An approval for a finding_id the aggregator doesn't know about must
    be rejected with an ``unknown_finding_id`` echo error, and nothing
    must be published to ``egs.operator_actions``.
    """
    app, http_client, fake = app_and_client

    pubsub = fake.pubsub()
    await pubsub.subscribe("egs.operator_actions")
    try:
        async with aconnect_ws("ws://testserver/", client=http_client) as ws:
            # Drain initial state envelope.
            await ws.receive_text()
            await ws.send_text(json.dumps(_approval_frame("f_drone99_999")))
            echo = await _drain_until(
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
async def test_known_finding_id_publishes_normally(app_and_client):
    """Positive case: an approval for a finding the aggregator knows about
    is acked AND republished onto ``egs.operator_actions``.
    """
    app, http_client, fake = app_and_client

    # Seed the aggregator directly so the allowlist contains this id.
    app.state.aggregator.add_finding(_KNOWN_FINDING)

    pubsub = fake.pubsub()
    await pubsub.subscribe("egs.operator_actions")
    try:
        async with aconnect_ws("ws://testserver/", client=http_client) as ws:
            await ws.receive_text()  # initial state envelope
            await ws.send_text(json.dumps(_approval_frame("f_drone1_5")))
            ack = await _drain_until(
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
