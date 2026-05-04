"""Shared fixtures for bridge WS tests.

Discovered automatically by pytest — no import needed at call site.

Convention: every fixture here is function-scoped, monkeypatch-aware,
and pinned to the running pytest-asyncio loop. The pytest.ini setting
``asyncio_default_fixture_loop_scope = function`` is what makes
fakeredis bind to the same loop as the test.
"""
from __future__ import annotations

import asyncio

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

    httpx-ws 0.8 requires the transport to be entered as an async context
    manager so ``aconnect_ws`` can read ``transport._task_group``. The
    AsyncExitStack inside the transport handles its own cleanup, which
    obsoletes the ``transport.exit_stack = None`` workaround we used on
    httpx-ws 0.7.

    anyio cancel-scope constraint: BOTH the
    ``ASGIWebSocketTransport`` task group AND FastAPI's
    ``lifespan_context`` create anyio cancel scopes that must be
    exited from the SAME asyncio Task that entered them. pytest-asyncio
    runs fixture teardown in a fresh ``runner.run()`` call (a new
    Task), so we cannot let either ``async with`` span the fixture
    yield boundary directly.

    Fix: hold BOTH context managers OPEN inside one dedicated
    lifecycle task. The fixture body signals teardown via the
    ``_teardown`` event and awaits the lifecycle task's completion.
    Enter and exit always happen in the same Task, satisfying anyio's
    constraint on both Linux+CPython 3.11 and macOS+CPython 3.12 while
    keeping all test call sites unchanged.
    """
    import redis.asyncio as redis_async

    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )

    from frontend.ws_bridge.main import create_app

    app = create_app()

    _ready: asyncio.Queue = asyncio.Queue(maxsize=1)
    _teardown = asyncio.Event()
    _exc_holder: list[BaseException] = []

    async def _lifecycle() -> None:
        try:
            async with ASGIWebSocketTransport(app=app) as transport:
                async with app.router.lifespan_context(app):
                    client = httpx.AsyncClient(
                        transport=transport, base_url="http://testserver"
                    )
                    _ready.put_nowait(client)
                    try:
                        await _teardown.wait()
                    finally:
                        await client.aclose()
        except BaseException as exc:  # noqa: BLE001
            _exc_holder.append(exc)

    lifecycle_task = asyncio.create_task(_lifecycle())
    client = await _ready.get()
    try:
        yield app, client, fake_client
    finally:
        _teardown.set()
        await lifecycle_task
        if _exc_holder:
            raise _exc_holder[0]
