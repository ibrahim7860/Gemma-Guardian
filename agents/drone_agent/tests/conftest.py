"""Shared fixtures for agents/drone_agent/tests/."""
from __future__ import annotations

import fakeredis
import pytest


@pytest.fixture
def fake_redis():
    server = fakeredis.FakeServer()
    return fakeredis.FakeStrictRedis(server=server, decode_responses=False)
