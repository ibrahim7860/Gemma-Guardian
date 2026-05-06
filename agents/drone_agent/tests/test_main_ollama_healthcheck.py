"""Coverage for agents.drone_agent.__main__._ollama_healthcheck.

Three branches: model present, model absent, daemon unreachable.
All three paths must NEVER raise — the healthcheck is best-effort and the
agent must boot regardless of Ollama state.
"""
from __future__ import annotations

import httpx
import pytest

from agents.drone_agent.__main__ import _ollama_healthcheck


@pytest.mark.asyncio
async def test_healthcheck_model_present(monkeypatch, capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [
            {"name": "gemma4:e2b"}, {"name": "gemma4:e4b"},
        ]})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda *a, **kw: real_client(*a, transport=transport, **kw),
    )

    await _ollama_healthcheck("http://localhost:11434", "gemma4:e2b")
    captured = capsys.readouterr().out
    assert "ollama OK" in captured
    assert "gemma4:e2b present" in captured


@pytest.mark.asyncio
async def test_healthcheck_model_absent_warns(monkeypatch, capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "llama3:8b"}]})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda *a, **kw: real_client(*a, transport=transport, **kw),
    )

    await _ollama_healthcheck("http://localhost:11434", "gemma4:e2b")
    captured = capsys.readouterr().out
    assert "WARNING" in captured
    assert "not in pulled list" in captured
    assert "ollama pull gemma4:e2b" in captured


@pytest.mark.asyncio
async def test_healthcheck_daemon_unreachable_warns(monkeypatch, capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda *a, **kw: real_client(*a, transport=transport, **kw),
    )

    # Must not raise.
    await _ollama_healthcheck("http://localhost:11434", "gemma4:e2b")
    captured = capsys.readouterr().out
    assert "WARNING" in captured
    assert "ollama healthcheck failed" in captured
