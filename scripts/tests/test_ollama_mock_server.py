"""Direct coverage for scripts/ollama_mock_server.py.

The mock server is used implicitly by the GATE 2 e2e
(frontend/ws_bridge/tests/test_e2e_playwright_real_drone_findings.py); this
test asserts its tool-call shape and /api/tags response directly so a future
refactor that breaks the mock surfaces here, not in a flaky e2e.
"""
from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    # Reload the module so the per-test request counter starts fresh.
    import scripts.ollama_mock_server as mod
    importlib.reload(mod)
    return TestClient(mod.app)


def test_tags_endpoint_advertises_gemma4(client):
    r = client.get("/api/tags")
    assert r.status_code == 200
    body = r.json()
    names = [m["name"] for m in body["models"]]
    assert "gemma4:e2b" in names
    assert "gemma4:e4b" in names


def test_first_chat_returns_canned_report_finding(client):
    r = client.post("/api/chat", json={"model": "gemma4:e2b", "messages": []})
    assert r.status_code == 200
    body = r.json()
    tc = body["message"]["tool_calls"][0]["function"]
    assert tc["name"] == "report_finding"
    args = json.loads(tc["arguments"])
    assert args["type"] == "victim"
    assert args["severity"] == 4
    assert 0.0 <= args["confidence"] <= 1.0
    assert len(args["visual_description"]) >= 10


def test_subsequent_chats_return_continue_mission(client):
    # First call burns the canned report_finding.
    client.post("/api/chat", json={"model": "gemma4:e2b", "messages": []})
    # Second + third calls should be continue_mission.
    for _ in range(2):
        r = client.post("/api/chat", json={"model": "gemma4:e2b", "messages": []})
        assert r.status_code == 200
        tc = r.json()["message"]["tool_calls"][0]["function"]
        assert tc["name"] == "continue_mission"
        assert tc["arguments"] == "{}"
