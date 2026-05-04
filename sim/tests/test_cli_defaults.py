"""Sim CLI argparse defaults — `--redis-url` derives from CONFIG.

If a developer overrides ``shared/config.yaml`` (e.g. to point at a
non-default port for a test bench), every runner should pick up that
URL automatically. The previous behaviour hardcoded
``redis://localhost:6379/0`` in each module's argparse default, which
silently diverged from the contract once anyone touched the config.

The "binding" tests below mutate ``CONFIG.transport.redis_url`` and
re-parse — the default must follow the live CONFIG value, proving the
default is *read from CONFIG at parse time*, not captured as a string
literal at module-import time.
"""
from __future__ import annotations

import pytest

from shared.contracts.config import CONFIG
from sim import frame_server as fs
from sim import waypoint_runner as wr

_SENTINEL_URL = "redis://sentinel.invalid:65535/7"


def test_waypoint_runner_redis_url_default_comes_from_config():
    args = wr._parse_args(["--scenario", "single_drone_smoke"])
    assert args.redis_url == CONFIG.transport.redis_url


def test_frame_server_redis_url_default_comes_from_config():
    args = fs._parse_args(["--scenario", "single_drone_smoke"])
    assert args.redis_url == CONFIG.transport.redis_url


def test_waypoint_runner_redis_url_explicit_override_wins():
    args = wr._parse_args(
        ["--scenario", "single_drone_smoke", "--redis-url", "redis://example.invalid:9999/0"]
    )
    assert args.redis_url == "redis://example.invalid:9999/0"


def test_frame_server_redis_url_explicit_override_wins():
    args = fs._parse_args(
        ["--scenario", "single_drone_smoke", "--redis-url", "redis://example.invalid:9999/0"]
    )
    assert args.redis_url == "redis://example.invalid:9999/0"


def test_waypoint_runner_redis_url_default_follows_live_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(CONFIG.transport, "redis_url", _SENTINEL_URL)
    args = wr._parse_args(["--scenario", "single_drone_smoke"])
    assert args.redis_url == _SENTINEL_URL


def test_frame_server_redis_url_default_follows_live_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(CONFIG.transport, "redis_url", _SENTINEL_URL)
    args = fs._parse_args(["--scenario", "single_drone_smoke"])
    assert args.redis_url == _SENTINEL_URL
