"""Shared fixtures for sim/tests/.

`fake_redis` returns an async-compatible fakeredis client wired to behave the
same as the real redis-py sync client (publish/subscribe semantics). All sim
producers use sync redis.Redis, so the sync client is what we exercise.
"""
from __future__ import annotations

import pytest
import fakeredis


@pytest.fixture
def fake_redis():
    """Plain sync fakeredis client — drop-in for redis.Redis()."""
    server = fakeredis.FakeServer()
    return fakeredis.FakeStrictRedis(server=server, decode_responses=False)


@pytest.fixture
def fake_redis_decoded():
    """Decoded variant for tests that prefer str over bytes on the read path."""
    server = fakeredis.FakeServer()
    return fakeredis.FakeStrictRedis(server=server, decode_responses=True)
