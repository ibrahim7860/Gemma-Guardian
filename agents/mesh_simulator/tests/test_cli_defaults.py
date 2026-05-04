"""Mesh simulator CLI defaults — `--redis-url` derives from CONFIG."""
from __future__ import annotations

import pytest

from agents.mesh_simulator import main as mesh_main
from shared.contracts.config import CONFIG

_SENTINEL_URL = "redis://sentinel.invalid:65535/7"


def test_mesh_simulator_redis_url_default_comes_from_config():
    args = mesh_main._parse_args([])
    assert args.redis_url == CONFIG.transport.redis_url


def test_mesh_simulator_redis_url_explicit_override_wins():
    args = mesh_main._parse_args(["--redis-url", "redis://example.invalid:9999/0"])
    assert args.redis_url == "redis://example.invalid:9999/0"


def test_mesh_simulator_redis_url_default_follows_live_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(CONFIG.transport, "redis_url", _SENTINEL_URL)
    args = mesh_main._parse_args([])
    assert args.redis_url == _SENTINEL_URL
