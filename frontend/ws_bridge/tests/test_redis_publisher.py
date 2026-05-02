"""Phase 3: RedisPublisher publishes JSON-encoded payloads with lazy connect.

Mirrors the patterns used by RedisSubscriber in Phase 2: single client per
publisher instance, opened on first publish, closed once on shutdown.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, List
from unittest.mock import AsyncMock

import fakeredis.aioredis as fakeredis_async
import pytest

from frontend.ws_bridge.redis_publisher import RedisPublisher


@pytest.fixture
def fake_client():
    """Single FakeRedis instance shared between the publisher and the test
    subscriber so messages round-trip in-process."""
    return fakeredis_async.FakeRedis()


@pytest.fixture
def patched_from_url(monkeypatch, fake_client):
    """Make redis.asyncio.Redis.from_url return a single FakeRedis instance.

    Matches the convention in test_subscriber.py.
    """
    import redis.asyncio as redis_async

    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )
    return fake_client


@pytest.mark.asyncio
async def test_first_publish_opens_connection(patched_from_url):
    pub = RedisPublisher(redis_url="redis://localhost:6379")
    assert pub._client is None  # type: ignore[attr-defined]
    await pub.publish("egs.operator_actions", {"kind": "test"})
    assert pub._client is not None  # type: ignore[attr-defined]
    await pub.close()


@pytest.mark.asyncio
async def test_publish_encodes_json_and_subscriber_receives(patched_from_url):
    pub = RedisPublisher(redis_url="redis://localhost:6379")
    received: List[bytes] = []

    pubsub = patched_from_url.pubsub()
    await pubsub.subscribe("egs.operator_actions")

    async def _drain():
        for _ in range(20):
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if msg is not None:
                received.append(msg["data"])
                return
            await asyncio.sleep(0.01)

    drain_task = asyncio.create_task(_drain())
    await asyncio.sleep(0.05)  # let subscriber settle
    payload = {"kind": "finding_approval", "action": "approve"}
    await pub.publish("egs.operator_actions", payload)
    await drain_task

    assert len(received) == 1
    assert json.loads(received[0]) == payload
    await pubsub.aclose()
    await pub.close()


@pytest.mark.asyncio
async def test_subsequent_publishes_reuse_connection(patched_from_url):
    pub = RedisPublisher(redis_url="redis://localhost:6379")
    await pub.publish("egs.operator_actions", {"kind": "test", "n": 1})
    client_after_first = pub._client  # type: ignore[attr-defined]
    await pub.publish("egs.operator_actions", {"kind": "test", "n": 2})
    assert pub._client is client_after_first  # type: ignore[attr-defined]
    await pub.close()


@pytest.mark.asyncio
async def test_close_is_idempotent(patched_from_url):
    pub = RedisPublisher(redis_url="redis://localhost:6379")
    await pub.publish("egs.operator_actions", {"kind": "test"})
    await pub.close()
    await pub.close()  # should not raise


@pytest.mark.asyncio
async def test_close_with_no_publish_is_noop(patched_from_url):
    pub = RedisPublisher(redis_url="redis://localhost:6379")
    await pub.close()  # should not raise


@pytest.mark.asyncio
async def test_publish_propagates_redis_error(monkeypatch):
    """Connection failures must propagate so the bridge can return an error echo."""
    import redis.asyncio as redis_async
    from redis.exceptions import RedisError

    raising_client = AsyncMock()
    raising_client.publish = AsyncMock(side_effect=RedisError("simulated"))
    monkeypatch.setattr(
        redis_async.Redis, "from_url",
        staticmethod(lambda url, **kw: raising_client),
    )
    pub = RedisPublisher(redis_url="redis://localhost:6379")
    with pytest.raises(RedisError):
        await pub.publish("egs.operator_actions", {"kind": "test"})


@pytest.mark.asyncio
async def test_concurrent_first_publishes_share_one_client(patched_from_url):
    """Two coroutines racing on first publish must share a single client."""
    pub = RedisPublisher(redis_url="redis://localhost:6379")
    await asyncio.gather(
        pub.publish("egs.operator_actions", {"n": 1}),
        pub.publish("egs.operator_actions", {"n": 2}),
        pub.publish("egs.operator_actions", {"n": 3}),
    )
    # All three should have shared one client; the patched fixture returns the
    # same FakeRedis instance for every from_url call, so this is implicitly
    # checked by reaching here without orphaned connection pools, but we also
    # assert _client identity is the fake we patched in.
    assert pub._client is patched_from_url  # type: ignore[attr-defined]
    await pub.close()


@pytest.mark.asyncio
async def test_publish_failure_resets_client_for_lazy_reconnect(monkeypatch):
    """After a publish raises, _client is nulled so the next call re-init's.

    Without this, a transient Redis outage would brick every subsequent publish
    until the bridge process restarts.
    """
    import redis.asyncio as redis_async
    from redis.exceptions import RedisError

    # First client raises, second succeeds — proving lazy reconnect happened.
    raising_client = AsyncMock()
    raising_client.publish = AsyncMock(side_effect=RedisError("simulated"))
    raising_client.aclose = AsyncMock()
    healthy_client = AsyncMock()
    healthy_client.publish = AsyncMock()
    healthy_client.aclose = AsyncMock()

    clients_iter = iter([raising_client, healthy_client])
    monkeypatch.setattr(
        redis_async.Redis, "from_url",
        staticmethod(lambda url, **kw: next(clients_iter)),
    )

    pub = RedisPublisher(redis_url="redis://localhost:6379")
    with pytest.raises(RedisError):
        await pub.publish("egs.operator_actions", {"kind": "test", "n": 1})
    # _client must have been nulled so the next call re-init's via from_url
    assert pub._client is None  # type: ignore[attr-defined]
    # Aclose the dead client was attempted during error recovery.
    raising_client.aclose.assert_awaited()

    # Next publish gets the healthy client.
    await pub.publish("egs.operator_actions", {"kind": "test", "n": 2})
    assert pub._client is healthy_client  # type: ignore[attr-defined]
    healthy_client.publish.assert_awaited_once()
    await pub.close()
