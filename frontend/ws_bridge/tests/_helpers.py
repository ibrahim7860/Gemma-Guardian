"""Shared async helpers for bridge WS tests.

These are NOT fixtures — they're plain functions imported explicitly by
the test files. Fixtures live in conftest.py; everything else lives here.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict

import httpx
from httpx_ws.transport import ASGIWebSocketTransport


async def drain_until(
    ws,
    predicate: Callable[[Dict[str, Any]], bool],
    *,
    max_frames: int = 20,
) -> Dict[str, Any]:
    """Receive up to ``max_frames`` frames; return the first one matching
    ``predicate``. Raises ``AssertionError`` if no frame matches.

    The default ``max_frames=20`` was chosen as the ceiling that covered
    every existing call site (the previous per-file defaults ranged from
    10 to 30). Tests that need a different ceiling pass it explicitly.
    """
    for _ in range(max_frames):
        raw = await ws.receive_text()
        msg = json.loads(raw)
        if predicate(msg):
            return msg
    raise AssertionError(
        f"no frame matched predicate after {max_frames} frames"
    )


@asynccontextmanager
async def make_test_client(app) -> AsyncIterator[httpx.AsyncClient]:
    """Construct an ``httpx.AsyncClient`` bound to an ``ASGIWebSocketTransport``
    against ``app``, scoped to a single test's task.

    Why this is a helper, not a fixture: ``httpx-ws`` 0.8+ enforces strict
    same-task entry/exit on the transport's ``async with`` (anyio 4.x cancel
    scope check). pytest-asyncio splits fixture setup and teardown across
    separate ``runner.run()`` invocations, so any transport entered in a
    fixture would fail at teardown. Used as a plain async context manager
    inside the test body, both ``__aenter__`` and ``__aexit__`` run in the
    test function's task and the check passes.
    """
    async with ASGIWebSocketTransport(app=app) as transport:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client
