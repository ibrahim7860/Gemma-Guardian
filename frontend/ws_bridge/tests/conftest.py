"""Shared fixtures for bridge WS tests.

Discovered automatically by pytest — no import needed at call site.

Convention: every fixture here is function-scoped, monkeypatch-aware,
and pinned to the running pytest-asyncio loop. The pytest.ini setting
``asyncio_default_fixture_loop_scope = function`` is what makes
fakeredis bind to the same loop as the test.
"""
from __future__ import annotations

import fakeredis.aioredis as fakeredis_async
import pytest_asyncio


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
async def app_and_redis(monkeypatch, fake_client):
    """Yields ``(app, fake_redis)`` with the bridge's lifespan active.

    Each test constructs its own ``ASGIWebSocketTransport`` +
    ``httpx.AsyncClient`` via ``make_test_client(app)`` from ``_helpers.py``.
    This avoids httpx-ws 0.8's strict same-task entry/exit check, which
    pytest-asyncio's split fixture setup/teardown otherwise violates.
    """
    import redis.asyncio as redis_async

    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )

    from frontend.ws_bridge.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app, fake_client
