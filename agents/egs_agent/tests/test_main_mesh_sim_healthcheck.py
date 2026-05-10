"""Wave 3a (Component 4) — mesh-sim availability healthcheck on EGS startup.

The mesh sim is the gateway between drones and EGS in PR2. If it isn't
running, the ``drones.*.findings.delivered`` channel is silent forever
and EGS sees zero findings — but with no error. The healthcheck blocks
EGS startup until at least one ``mesh.adjacency_matrix`` heartbeat
arrives, then either proceeds or raises a remediation-rich
``RuntimeError`` after a configurable timeout.

These tests pin three properties:
  1. presence of mesh sim (any single message on the channel) → fast OK;
  2. absence past the timeout → ``RuntimeError`` raised;
  3. the error message contains the literal launch command so an
     operator following the log can act without consulting docs.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.egs_agent.main import _await_mesh_sim


def _build_fake_redis_client(messages: list[dict | None] | None = None):
    """Build a redis-asyncio-shaped mock whose pubsub returns the queued
    messages from ``messages`` in order on successive ``get_message``
    calls. ``None`` entries simulate a no-message tick (timeout). After
    the queue exhausts, every subsequent call returns ``None`` (still
    "no messages").
    """
    queue = list(messages or [])

    fake_pubsub = MagicMock()

    async def _get_message(*args, **kwargs):
        if queue:
            return queue.pop(0)
        return None

    fake_pubsub.subscribe = AsyncMock(return_value=None)
    fake_pubsub.unsubscribe = AsyncMock(return_value=None)
    fake_pubsub.get_message = AsyncMock(side_effect=_get_message)

    fake_client = MagicMock()
    fake_client.pubsub = MagicMock(return_value=fake_pubsub)
    return fake_client, fake_pubsub


@pytest.mark.asyncio
async def test_startup_succeeds_when_mesh_adjacency_present():
    """Single mesh.adjacency_matrix message → healthcheck returns
    promptly (well under 1s)."""
    fake_client, fake_pubsub = _build_fake_redis_client(
        messages=[{
            "type": "message",
            "channel": b"mesh.adjacency_matrix",
            "data": b"{}",
        }],
    )

    start = asyncio.get_event_loop().time()
    await _await_mesh_sim(fake_client, timeout_s=5.0)
    elapsed = asyncio.get_event_loop().time() - start

    assert elapsed < 1.0, (
        f"healthcheck should complete promptly when mesh sim is alive; "
        f"took {elapsed:.3f}s"
    )
    fake_pubsub.subscribe.assert_awaited_once_with("mesh.adjacency_matrix")


@pytest.mark.asyncio
async def test_startup_fails_without_mesh_sim():
    """No publisher → healthcheck times out and raises RuntimeError.

    Uses a tight timeout (0.3s) so the test runs fast; the real default
    is 5s but that's irrelevant to the contract being pinned here.
    """
    fake_client, _ = _build_fake_redis_client(messages=[])

    with pytest.raises(RuntimeError) as excinfo:
        await _await_mesh_sim(fake_client, timeout_s=0.3)

    msg = str(excinfo.value)
    assert "mesh_simulator not detected" in msg, msg
    assert "mesh.adjacency_matrix" in msg, msg


@pytest.mark.asyncio
async def test_startup_failure_message_includes_remediation():
    """The RuntimeError text must contain the literal launch command so
    an operator following the EGS log knows exactly what to do."""
    fake_client, _ = _build_fake_redis_client(messages=[])

    with pytest.raises(RuntimeError) as excinfo:
        await _await_mesh_sim(fake_client, timeout_s=0.2)

    assert "python -m agents.mesh_simulator" in str(excinfo.value), (
        f"healthcheck failure must surface the launch command verbatim; "
        f"got: {excinfo.value}"
    )
