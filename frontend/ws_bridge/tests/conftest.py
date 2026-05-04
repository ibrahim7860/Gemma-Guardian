"""Shared fixtures for bridge WS tests.

Discovered automatically by pytest — no import needed at call site.

Convention: every fixture here is function-scoped, monkeypatch-aware,
and pinned to the running pytest-asyncio loop. The pytest.ini setting
``asyncio_default_fixture_loop_scope = function`` is what makes
fakeredis bind to the same loop as the test.
"""
from __future__ import annotations

import fakeredis.aioredis as fakeredis_async
import httpx
import pytest_asyncio
from httpx_ws.transport import ASGIWebSocketTransport


@pytest_asyncio.fixture
async def fake_client():
    """A fakeredis client bound to the running pytest-asyncio loop.

    Used by every test that needs the bridge to talk to a Redis-compatible
    backend without spawning a real redis-server.
    """
    client = fakeredis_async.FakeRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def app_and_client(monkeypatch, fake_client):
    """Construct the FastAPI app + httpx AsyncClient + ASGI WS transport
    against the fakeredis backend, run the bridge's lifespan context, and
    yield ``(app, http_client, fake_redis)``.

    Yields:
        tuple of (FastAPI app, httpx.AsyncClient, fakeredis client)

    Teardown: ``transport.exit_stack = None`` is a documented workaround
    for the httpx-ws<0.8 transport's circular-reference at shutdown. See
    pyproject.toml ([project.optional-dependencies] dev) for the
    upper-bound pin and the migration TODO.
    """
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
