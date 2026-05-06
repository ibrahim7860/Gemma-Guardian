"""Contract test: ReasoningNode's HTTP request matches Ollama /api/chat shape.

Uses httpx.MockTransport to intercept the call. No Ollama needed. Validates
that future changes to ReasoningNode don't silently break the wire format.
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from agents.drone_agent.perception import DroneState, PerceptionBundle
from agents.drone_agent.reasoning import DRONE_TOOLS, ReasoningNode


def _bundle() -> PerceptionBundle:
    state = DroneState(
        drone_id="drone1", lat=34.0, lon=-118.5, alt=25.0,
        battery_pct=87.0, heading_deg=0.0, current_task="survey",
        assigned_survey_points_remaining=5,
        zone_bounds={"lat_min": 33.99, "lat_max": 34.01,
                     "lon_min": -118.51, "lon_max": -118.49},
    )
    # A minimal real JPEG (SOI + EOI bytes is enough for base64-encode test).
    return PerceptionBundle(frame_jpeg=b"\xff\xd8\xff\xd9", state=state)


@pytest.mark.asyncio
async def test_request_url_path_matches_ollama_api_chat(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={
            "message": {"tool_calls": [{
                "function": {"name": "continue_mission", "arguments": "{}"},
            }]},
        })

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    def patched(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return real_client(*args, **kwargs)
    monkeypatch.setattr("agents.drone_agent.reasoning.httpx.AsyncClient", patched)

    node = ReasoningNode(model="gemma4:e2b", endpoint="http://localhost:11434")
    bundle = _bundle()
    response = await node.call(bundle)

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/chat")
    body = captured["body"]
    assert body["model"] == "gemma4:e2b"
    assert body["stream"] is False
    assert body["tools"] == DRONE_TOOLS
    # Two messages: system + user-with-image.
    assert len(body["messages"]) == 2
    assert body["messages"][0]["role"] == "system"
    user = body["messages"][1]
    assert user["role"] == "user"
    assert isinstance(user["content"], str)
    assert user["images"] == [base64.b64encode(b"\xff\xd8\xff\xd9").decode("ascii")]
    # Response parsing path also exercised.
    parsed = ReasoningNode.parse_function_call(response)
    assert parsed == {"function": "continue_mission", "arguments": {}}


@pytest.mark.asyncio
async def test_text_only_mode_omits_images(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"message": {"tool_calls": []}})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "agents.drone_agent.reasoning.httpx.AsyncClient",
        lambda *a, **kw: real_client(*a, transport=transport, **kw),
    )

    node = ReasoningNode(model="gemma4:e2b", endpoint="http://localhost:11434", send_image=False)
    await node.call(_bundle())

    user = captured["body"]["messages"][1]
    assert "images" not in user


@pytest.mark.asyncio
async def test_extra_options_threaded_through(monkeypatch):
    captured: dict = {}
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"message": {"tool_calls": []}})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "agents.drone_agent.reasoning.httpx.AsyncClient",
        lambda *a, **kw: real_client(*a, transport=transport, **kw),
    )

    node = ReasoningNode(model="gemma4:e2b", endpoint="http://localhost:11434",
                         extra_options={"num_gpu": 0})
    await node.call(_bundle())
    assert captured["body"]["options"]["num_gpu"] == 0
    assert captured["body"]["options"]["temperature"] == 0.2


def test_default_timeout_is_120s():
    """Regression guard: cold-loading 7.2GB gemma4:e2b + first vision+tools call
    on Apple Silicon CPU exceeds 30s. The default was bumped from 30 to 120 in
    the live-smoke commit; if anyone reverts it, the live runbook breaks again."""
    node = ReasoningNode(model="gemma4:e2b")
    assert node.timeout_s == 120.0
