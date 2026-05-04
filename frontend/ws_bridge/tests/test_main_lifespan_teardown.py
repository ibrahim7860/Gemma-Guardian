"""Phase 5+: bridge lifespan teardown must NOT produce
``RuntimeError: Event loop is closed`` noise on shutdown.

The fix orders teardown as:

    1. signal_stop on subscriber (flag flips, no pubsub close yet)
    2. cancel emit/subscribe/translation tasks
    3. await ALL THREE background tasks
    4. ONLY THEN close the subscriber's pubsub
    5. close the publisher

Today's (Task 1) sequence cancels and then closes the pubsub before the
subscribe task has had a chance to exit its read loop, leaving the task
mid-``pubsub.get_message()`` when ``aclose()`` runs. We verify the
new ordering by capturing the call order on a stub subscriber that
parks indefinitely until cancelled (verifying eng-review 1B: cancel,
not just signal, must drive the exit).
"""
from __future__ import annotations

import asyncio
from typing import List

import fakeredis.aioredis as fakeredis_async
import pytest

from frontend.ws_bridge.main import create_app


class _OrderRecordingSubscriber:
    """Stand-in subscriber that records the order of lifecycle calls."""

    def __init__(self, order: List[str]) -> None:
        self._order = order
        self._stopping = False
        self._run_started = asyncio.Event()
        self._run_done = asyncio.Event()

    async def run(self) -> None:
        self._order.append("run_start")
        self._run_started.set()
        # Park forever — we exit ONLY on cancel. Verifies eng-review 1B:
        # the lifespan must cancel subscribe_task, not just rely on the
        # _stopping flag draining the read loop.
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self._order.append("run_cancelled")
            raise
        finally:
            self._order.append("run_exit")
            self._run_done.set()

    def signal_stop(self) -> None:
        self._order.append("signal_stop")
        self._stopping = True

    async def close(self) -> None:
        self._order.append("close")

    # Legacy shim — must NOT be called by the new lifespan.
    async def stop(self) -> None:  # pragma: no cover
        self._order.append("LEGACY_STOP_CALLED")
        self.signal_stop()
        await self.close()


@pytest.mark.asyncio
async def test_lifespan_signals_stop_before_closing_pubsub(monkeypatch):
    order: List[str] = []
    stub = _OrderRecordingSubscriber(order)

    # Patch Redis so create_app() and publisher don't try to connect.
    fake_client = fakeredis_async.FakeRedis()
    import redis.asyncio as redis_async
    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )

    app = create_app()
    # Swap in our recording subscriber BEFORE the lifespan starts.
    # The lifespan reads app.state.subscriber when it runs, so this
    # replacement is picked up correctly.
    app.state.subscriber = stub

    async with app.router.lifespan_context(app):
        # Give the subscribe task a tick to enter its run loop.
        await asyncio.wait_for(stub._run_started.wait(), timeout=1.0)

    # lifespan_context exit -> lifespan finally block ran.
    assert "signal_stop" in order, order
    assert "close" in order, order
    assert "run_cancelled" in order, (
        "subscribe_task must be cancel()ed, not just signalled (eng-review 1B): "
        f"{order}"
    )
    assert "run_exit" in order, order
    assert order.index("signal_stop") < order.index("close"), order
    assert order.index("run_exit") < order.index("close"), order
    assert "LEGACY_STOP_CALLED" not in order, order

    await fake_client.aclose()
