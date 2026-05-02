"""Phase 3: ws_endpoint accepts finding_approval, validates, publishes, acks.

Uses the FastAPI TestClient with a fakeredis-backed bridge. The bridge's
RedisPublisher is monkeypatched to share a single FakeRedis instance with
the test subscriber so we can assert what landed on the channel.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

import fakeredis.aioredis as fakeredis_async
import pytest
from fastapi.testclient import TestClient

import redis.asyncio as redis_async


@pytest.fixture
def fake_client():
    return fakeredis_async.FakeRedis()


@pytest.fixture
def app_with_fake_redis(monkeypatch, fake_client):
    """Build the bridge app with redis.asyncio.from_url returning a single
    fakeredis instance for both the subscriber and the publisher.

    Phase 4: also seed the aggregator with the finding_id the existing
    tests approve (``f_drone1_42``) so the new allowlist guard does not
    reject otherwise-valid frames. Tests that want to exercise the
    unknown-id path live in ``test_main_finding_id_allowlist.py``.
    """
    monkeypatch.setattr(
        redis_async.Redis, "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )
    # Import after patching so any import-time client creation uses the patched factory.
    from frontend.ws_bridge.main import create_app
    app = create_app()
    app.state.aggregator.add_finding({
        "finding_id": "f_drone1_42",
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
    })
    return app


@pytest.fixture
def client(app_with_fake_redis):
    with TestClient(app_with_fake_redis) as c:
        yield c


def _valid_envelope(command_id: str = "test-1700000000000-1") -> Dict[str, Any]:
    return {
        "type": "finding_approval",
        "command_id": command_id,
        "finding_id": "f_drone1_42",
        "action": "approve",
        "contract_version": "1.0.0",
    }


def _drain(ws, expected_type_or_ack: str, *, max_frames: int = 20) -> Dict[str, Any]:
    """Read frames from the WS until we find one matching expected_type_or_ack
    (matches against `type`, `ack`, or `error` field). Skips state_update frames."""
    for _ in range(max_frames):
        raw = ws.receive_text()
        msg = json.loads(raw)
        if msg.get("type") == "state_update":
            continue
        if msg.get("type") == expected_type_or_ack:
            return msg
        if msg.get("ack") == expected_type_or_ack:
            return msg
        if msg.get("error") == expected_type_or_ack:
            return msg
    raise AssertionError(f"No matching frame for {expected_type_or_ack!r}")


def test_valid_finding_approval_publishes_and_acks(client, fake_client):
    """Full happy path: bridge ack arrives AND fakeredis subscriber receives the payload.

    To bridge the sync TestClient world with the async fakeredis subscriber, we
    establish the subscription on a dedicated loop *before* sending the WS frame,
    then drain incoming messages on the same loop after the bridge has published.
    """
    loop = asyncio.new_event_loop()
    pubsub = fake_client.pubsub()
    loop.run_until_complete(pubsub.subscribe("egs.operator_actions"))

    async def _drain_one_message() -> List[bytes]:
        out: List[bytes] = []
        for _ in range(40):
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if msg is not None:
                out.append(msg["data"])
                break
            await asyncio.sleep(0.01)
        return out

    with client.websocket_connect("/") as ws:
        envelope = _valid_envelope()
        ws.send_text(json.dumps(envelope))
        ack = _drain(ws, "finding_approval")
        assert ack["type"] == "echo"
        assert ack["ack"] == "finding_approval"
        assert ack["command_id"] == envelope["command_id"]
        assert ack["finding_id"] == envelope["finding_id"]

    received = loop.run_until_complete(_drain_one_message())
    loop.run_until_complete(pubsub.aclose())
    loop.close()

    assert len(received) == 1
    payload = json.loads(received[0])
    assert payload["kind"] == "finding_approval"
    assert payload["command_id"] == envelope["command_id"]
    assert payload["finding_id"] == envelope["finding_id"]
    assert payload["action"] == "approve"
    assert payload["contract_version"] == "1.0.0"
    # bridge stamps timestamp
    assert payload["bridge_received_at_iso_ms"].endswith("Z")


def test_invalid_action_returns_error_echo(client):
    bad = _valid_envelope()
    bad["action"] = "delete"  # not in enum
    with client.websocket_connect("/") as ws:
        ws.send_text(json.dumps(bad))
        echo = _drain(ws, "invalid_finding_approval")
        assert echo["error"] == "invalid_finding_approval"
        assert echo["command_id"] == bad["command_id"]
        assert echo["finding_id"] == bad["finding_id"]


def test_missing_command_id_returns_error_echo(client):
    bad = _valid_envelope()
    bad.pop("command_id")
    with client.websocket_connect("/") as ws:
        ws.send_text(json.dumps(bad))
        echo = _drain(ws, "invalid_finding_approval")
        assert echo["error"] == "invalid_finding_approval"


def test_missing_finding_id_returns_error_echo(client):
    bad = _valid_envelope()
    bad.pop("finding_id")
    with client.websocket_connect("/") as ws:
        ws.send_text(json.dumps(bad))
        echo = _drain(ws, "invalid_finding_approval")
        assert echo["error"] == "invalid_finding_approval"


def test_redis_publish_failure_returns_error_echo(monkeypatch):
    """Simulate Redis being down by patching publish() to raise."""
    from redis.exceptions import RedisError
    from frontend.ws_bridge.main import create_app

    fake = fakeredis_async.FakeRedis()
    monkeypatch.setattr(
        redis_async.Redis, "from_url",
        staticmethod(lambda url, **kw: fake),
    )
    app = create_app()
    # Phase 4: seed the aggregator so the allowlist guard does not
    # short-circuit before we get to the simulated Redis failure.
    app.state.aggregator.add_finding({
        "finding_id": "f_drone1_42",
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
    })
    # Replace the publisher with one whose publish() raises.
    async def _raise(channel, payload):
        raise RedisError("simulated redis down")
    app.state.publisher.publish = _raise  # type: ignore[assignment]

    with TestClient(app) as client:
        with client.websocket_connect("/") as ws:
            ws.send_text(json.dumps(_valid_envelope()))
            echo = _drain(ws, "redis_publish_failed")
            assert echo["error"] == "redis_publish_failed"
            assert echo["command_id"] == _valid_envelope()["command_id"]
            assert echo["finding_id"] == _valid_envelope()["finding_id"]


def test_unknown_envelope_type_still_echoes(client):
    """Regression: existing 'unknown type' echo path still works."""
    with client.websocket_connect("/") as ws:
        ws.send_text(json.dumps({"type": "totally_made_up", "x": 1}))
        # The bridge echoes the parsed payload back when it doesn't recognize the type.
        # Drain until we see the echo (skipping state_update).
        for _ in range(20):
            raw = ws.receive_text()
            msg = json.loads(raw)
            if msg.get("type") == "state_update":
                continue
            assert msg.get("type") == "echo"
            assert msg.get("received") == {"type": "totally_made_up", "x": 1}
            return
        raise AssertionError("no echo received for unknown type")


def test_existing_operator_command_path_still_passes(client):
    """Regression-guard: the existing operator_command echo path still works."""
    cmd = {
        "type": "operator_command",
        "command_id": "op-1700000000000-1",
        "language": "en",
        "raw_text": "drone 1, return to base",
        "contract_version": "1.0.0",
    }
    with client.websocket_connect("/") as ws:
        ws.send_text(json.dumps(cmd))
        ack = _drain(ws, "operator_command_received")
        assert ack["ack"] == "operator_command_received"
