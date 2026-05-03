"""Phase 4 follow-up: cover the error paths the happy-path Phase 4 tests
intentionally skipped — ``bridge_internal`` (envelope re-validation
fails) and ``redis_publish_failed`` (publisher raises) for each of the
three command branches in ``frontend/ws_bridge/main.py``.

Test harness mirrors ``test_main_operator_command_publish.py``: single
event loop, ASGI WS transport, fakeredis bound to the same loop, lifespan
driven manually so subscriber + emit tasks run inline.

Eng-review 1A: ``_now_iso_ms`` monkeypatch is wrapped in
``_IsoMsCounter`` so the test asserts the bridge actually invoked it. If
the symbol is ever refactored to a local import, the test fails loudly
instead of passing for the wrong reason.

Eng-review 1B simplification: instead of the planned
publish-state_update-and-wait dance, this file pokes
``app.state.aggregator.add_finding(...)`` directly using the canonical
fixture at ``shared/schemas/fixtures/valid/finding/01_victim.json``.
The aggregator has a documented public API and the fixture is already
schema-validated by Phase 1 tests, so seed-payload drift is impossible.
"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import fakeredis.aioredis as fakeredis_async
import httpx
import pytest
import pytest_asyncio
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport


_FINDING_FIXTURE = (
    Path(__file__).parent.parent.parent.parent
    / "shared" / "schemas" / "fixtures" / "valid" / "finding" / "01_victim.json"
)


# ---- fixtures --------------------------------------------------------------


@pytest_asyncio.fixture
async def fake_client():
    client = fakeredis_async.FakeRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def app_and_client(monkeypatch, fake_client):
    import redis.asyncio as redis_async

    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )

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
            transport.exit_stack = None
            await client.aclose()


# ---- helpers ---------------------------------------------------------------


async def _drain_until(ws, predicate, *, max_frames: int = 20) -> Dict[str, Any]:
    for _ in range(max_frames):
        raw = await ws.receive_text()
        msg = json.loads(raw)
        if predicate(msg):
            return msg
    raise AssertionError(
        f"no frame matched predicate after {max_frames} frames"
    )


class _IsoMsCounter:
    """Wraps a fixed return value with an invocation counter so tests can
    assert the bridge's stamping path actually executed (eng-review 1A —
    silent decoupling guard if ``_now_iso_ms`` is ever refactored to a
    local import or aliased symbol).
    """

    def __init__(self, value: str = "not-an-iso") -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.value


def _seed_finding(app, finding_id: str) -> None:
    """Seed a finding directly into the bridge's aggregator so the
    allowlist guard accepts ``finding_id``. Uses the canonical victim
    fixture and swaps the id; the aggregator's ``add_finding`` API
    enforces schema validity internally on snapshot, but the fixture is
    already validated upstream by ``test_aggregator.py``.
    """
    payload = json.loads(_FINDING_FIXTURE.read_text())
    payload = deepcopy(payload)
    payload["finding_id"] = finding_id
    app.state.aggregator.add_finding(payload)


# ---- operator_command branch -----------------------------------------------


@pytest.mark.asyncio
async def test_operator_command_redis_publish_failed_emits_echo(
    app_and_client, monkeypatch
):
    """When the publisher raises during ``operator_command`` republish,
    the bridge MUST echo ``redis_publish_failed`` and MUST NOT ack with
    ``operator_command_received``.
    """
    app, http_client, _fake = app_and_client

    async def _boom(*_a, **_kw):
        raise RuntimeError("redis is on fire")

    monkeypatch.setattr(app.state.publisher, "publish", _boom)

    frame = {
        "type": "operator_command",
        "command_id": "err-cmd-1",
        "language": "en",
        "raw_text": "recall drone1",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()  # initial state envelope
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "redis_publish_failed"
        )

    assert echo["type"] == "echo"
    assert echo["error"] == "redis_publish_failed"
    assert echo["command_id"] == "err-cmd-1"


@pytest.mark.asyncio
async def test_operator_command_bridge_internal_when_envelope_invalid(
    app_and_client, monkeypatch
):
    """Force the bridge's envelope re-validation to fail by stamping a
    non-ISO timestamp. The inbound frame is well-formed, so the only
    path that fires here is ``bridge_internal``.
    """
    import frontend.ws_bridge.main as bridge_main

    iso = _IsoMsCounter()
    monkeypatch.setattr(bridge_main, "_now_iso_ms", iso)

    app, http_client, _fake = app_and_client

    frame = {
        "type": "operator_command",
        "command_id": "err-cmd-2",
        "language": "en",
        "raw_text": "recall drone1",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "bridge_internal"
        )

    assert echo["type"] == "echo"
    assert echo["error"] == "bridge_internal"
    assert echo["command_id"] == "err-cmd-2"
    assert "detail" in echo and isinstance(echo["detail"], list)
    assert iso.calls >= 1, "monkeypatched _now_iso_ms was never called"


# ---- finding_approval branch -----------------------------------------------


@pytest.mark.asyncio
async def test_finding_approval_redis_publish_failed_emits_echo(
    app_and_client, monkeypatch
):
    app, http_client, _fake = app_and_client
    _seed_finding(app, "f_drone1_001")

    async def _boom(*_a, **_kw):
        raise RuntimeError("redis is on fire")

    monkeypatch.setattr(app.state.publisher, "publish", _boom)

    frame = {
        "type": "finding_approval",
        "command_id": "err-cmd-3",
        "finding_id": "f_drone1_001",
        "action": "approve",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "redis_publish_failed"
        )

    assert echo["error"] == "redis_publish_failed"
    assert echo["command_id"] == "err-cmd-3"
    assert echo["finding_id"] == "f_drone1_001"


@pytest.mark.asyncio
async def test_finding_approval_bridge_internal_when_envelope_invalid(
    app_and_client, monkeypatch
):
    import frontend.ws_bridge.main as bridge_main

    app, http_client, _fake = app_and_client
    _seed_finding(app, "f_drone1_002")
    iso = _IsoMsCounter()
    monkeypatch.setattr(bridge_main, "_now_iso_ms", iso)

    frame = {
        "type": "finding_approval",
        "command_id": "err-cmd-4",
        "finding_id": "f_drone1_002",
        "action": "approve",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "bridge_internal"
        )

    assert echo["error"] == "bridge_internal"
    assert echo["command_id"] == "err-cmd-4"
    assert echo["finding_id"] == "f_drone1_002"
    assert iso.calls >= 1, "monkeypatched _now_iso_ms was never called"


# ---- operator_command_dispatch branch --------------------------------------


@pytest.mark.asyncio
async def test_dispatch_redis_publish_failed_emits_echo(
    app_and_client, monkeypatch
):
    app, http_client, _fake = app_and_client

    async def _boom(*_a, **_kw):
        raise RuntimeError("redis is on fire")

    monkeypatch.setattr(app.state.publisher, "publish", _boom)

    frame = {
        "type": "operator_command_dispatch",
        "command_id": "err-cmd-5",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "redis_publish_failed"
        )

    assert echo["error"] == "redis_publish_failed"
    assert echo["command_id"] == "err-cmd-5"


@pytest.mark.asyncio
async def test_dispatch_bridge_internal_when_envelope_invalid(
    app_and_client, monkeypatch
):
    import frontend.ws_bridge.main as bridge_main

    iso = _IsoMsCounter()
    monkeypatch.setattr(bridge_main, "_now_iso_ms", iso)

    app, http_client, _fake = app_and_client

    frame = {
        "type": "operator_command_dispatch",
        "command_id": "err-cmd-6",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "bridge_internal"
        )

    assert echo["error"] == "bridge_internal"
    assert echo["command_id"] == "err-cmd-6"
    assert iso.calls >= 1, "monkeypatched _now_iso_ms was never called"
