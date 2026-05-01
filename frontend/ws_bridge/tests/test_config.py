"""Smoke tests for BridgeConfig env loading."""
from __future__ import annotations

import os

import pytest

from frontend.ws_bridge.config import BridgeConfig


def test_defaults_when_env_unset(monkeypatch):
    for k in (
        "REDIS_URL",
        "BRIDGE_TICK_S",
        "BRIDGE_MAX_FINDINGS",
        "BRIDGE_RECONNECT_MAX_S",
        "BRIDGE_BROADCAST_TIMEOUT_S",
    ):
        monkeypatch.delenv(k, raising=False)
    cfg = BridgeConfig.from_env()
    assert cfg.redis_url == "redis://localhost:6379"
    assert cfg.tick_s == 1.0
    assert cfg.max_findings == 50
    assert cfg.reconnect_max_s == 10.0
    assert cfg.broadcast_timeout_s == 0.5


def test_overrides_from_env(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://example:6380/3")
    monkeypatch.setenv("BRIDGE_TICK_S", "0.25")
    monkeypatch.setenv("BRIDGE_MAX_FINDINGS", "10")
    monkeypatch.setenv("BRIDGE_RECONNECT_MAX_S", "30")
    monkeypatch.setenv("BRIDGE_BROADCAST_TIMEOUT_S", "1.5")
    cfg = BridgeConfig.from_env()
    assert cfg.redis_url == "redis://example:6380/3"
    assert cfg.tick_s == 0.25
    assert cfg.max_findings == 10
    assert cfg.reconnect_max_s == 30.0
    assert cfg.broadcast_timeout_s == 1.5


def test_immutable():
    cfg = BridgeConfig.from_env()
    with pytest.raises(Exception):
        cfg.tick_s = 9.9  # type: ignore[misc]
