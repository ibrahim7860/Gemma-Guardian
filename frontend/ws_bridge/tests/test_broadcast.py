"""Per-eng-review fix 1A: _ConnectionRegistry broadcasts in parallel.

A slow or dead client must not block other clients. We exercise the
``_ConnectionRegistry.broadcast`` path with mocked WS clients (the public
``send_text`` is the only method the registry calls).
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from frontend.ws_bridge.main import _ConnectionRegistry


class _FakeWS:
    """Minimal WebSocket stand-in. Records every send_text call."""

    def __init__(self, *, delay_s: float = 0.0, raise_exc: bool = False) -> None:
        self._delay_s = delay_s
        self._raise = raise_exc
        self.received: List[str] = []

    async def send_text(self, payload: str) -> None:
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        if self._raise:
            raise ConnectionError("test: client gone")
        self.received.append(payload)


@pytest.mark.asyncio
async def test_broadcast_delivers_to_all_clients():
    reg = _ConnectionRegistry(broadcast_timeout_s=0.5)
    a, b = _FakeWS(), _FakeWS()
    await reg.add(a)  # type: ignore[arg-type]
    await reg.add(b)  # type: ignore[arg-type]

    msg: Dict[str, Any] = {"type": "state_update", "tick": 1}
    await reg.broadcast(msg)

    assert len(a.received) == 1
    assert len(b.received) == 1


@pytest.mark.asyncio
async def test_broadcast_drops_slow_client_and_keeps_fast_one():
    """Eng-review 1A: a slow client gets dropped; others still receive."""
    reg = _ConnectionRegistry(broadcast_timeout_s=0.05)
    fast = _FakeWS(delay_s=0.0)
    slow = _FakeWS(delay_s=0.5)   # 10x the timeout
    await reg.add(fast)  # type: ignore[arg-type]
    await reg.add(slow)  # type: ignore[arg-type]

    await reg.broadcast({"type": "state_update", "tick": 1})

    assert len(fast.received) == 1
    # Slow client times out; not registered as having received the message
    # and is dropped from the registry.
    assert len(slow.received) == 0
    # A second broadcast should reach only fast.
    await reg.broadcast({"type": "state_update", "tick": 2})
    assert len(fast.received) == 2
    assert len(slow.received) == 0


@pytest.mark.asyncio
async def test_broadcast_drops_raising_client():
    reg = _ConnectionRegistry(broadcast_timeout_s=0.5)
    healthy = _FakeWS()
    dead = _FakeWS(raise_exc=True)
    await reg.add(healthy)  # type: ignore[arg-type]
    await reg.add(dead)     # type: ignore[arg-type]

    await reg.broadcast({"type": "state_update", "tick": 1})

    assert len(healthy.received) == 1
    assert len(dead.received) == 0
    # dead client is dropped; second broadcast goes only to healthy.
    await reg.broadcast({"type": "state_update", "tick": 2})
    assert len(healthy.received) == 2


@pytest.mark.asyncio
async def test_broadcast_with_zero_clients_is_noop():
    reg = _ConnectionRegistry(broadcast_timeout_s=0.5)
    # Should not raise.
    await reg.broadcast({"type": "state_update"})


@pytest.mark.asyncio
async def test_broadcast_runs_in_parallel():
    """All sends start concurrently; total wall time ~= slowest client.

    Three clients each delay 0.1s. Serial would take ~0.3s; parallel ~0.1s.
    Add generous slack for CI noise.
    """
    reg = _ConnectionRegistry(broadcast_timeout_s=1.0)
    clients = [_FakeWS(delay_s=0.1) for _ in range(3)]
    for c in clients:
        await reg.add(c)  # type: ignore[arg-type]

    start = asyncio.get_event_loop().time()
    await reg.broadcast({"type": "state_update"})
    elapsed = asyncio.get_event_loop().time() - start

    assert elapsed < 0.25, f"broadcast was serial, took {elapsed:.3f}s"
    for c in clients:
        assert len(c.received) == 1
