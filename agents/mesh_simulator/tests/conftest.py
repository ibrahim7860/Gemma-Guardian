"""Shared fixtures for agents/mesh_simulator/tests/."""
from __future__ import annotations

import pytest
import fakeredis


@pytest.fixture
def fake_redis():
    server = fakeredis.FakeServer()
    return fakeredis.FakeStrictRedis(server=server, decode_responses=False)
