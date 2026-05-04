"""Sim CLI argparse defaults + scenario / config consistency.

If a developer overrides ``shared/config.yaml`` (e.g. to point at a
non-default port for a test bench), every runner should pick up that
URL automatically. The previous behaviour hardcoded
``redis://localhost:6379/0`` in each module's argparse default, which
silently diverged from the contract once anyone touched the config.

The "binding" tests below mutate ``CONFIG.transport.redis_url`` and
re-parse — the default must follow the live CONFIG value, proving the
default is *read from CONFIG at parse time*, not captured as a string
literal at module-import time.

The drone-count consistency tests guard a different failure mode: if
``CONFIG.mission.drone_count`` and the scenario's ``len(drones)``
disagree, the swarm under-provisions or over-provisions silently. Fail
fast at scenario load with a clear message naming both numbers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from shared.contracts.config import CONFIG
from sim import frame_server as fs
from sim import waypoint_runner as wr
from sim.scenario import load_scenario

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

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


# --- mission.drone_count consistency check (slice C) ---------------------------


@pytest.fixture
def smoke_scenario():
    return load_scenario(REPO_ROOT / "sim" / "scenarios" / "single_drone_smoke.yaml")


@pytest.fixture
def disaster_zone_scenario():
    return load_scenario(REPO_ROOT / "sim" / "scenarios" / "disaster_zone_v1.yaml")


def test_check_drone_count_passes_when_matching(monkeypatch, disaster_zone_scenario):
    monkeypatch.setattr(CONFIG.mission, "drone_count", len(disaster_zone_scenario.drones))
    # No exception.
    wr._check_drone_count(disaster_zone_scenario)


def test_check_drone_count_passes_for_smoke_when_matching(monkeypatch, smoke_scenario):
    monkeypatch.setattr(CONFIG.mission, "drone_count", 1)
    wr._check_drone_count(smoke_scenario)


def test_check_drone_count_fails_when_config_too_high(monkeypatch, smoke_scenario):
    monkeypatch.setattr(CONFIG.mission, "drone_count", 3)
    with pytest.raises(SystemExit, match="drone_count=3"):
        wr._check_drone_count(smoke_scenario)


def test_check_drone_count_fails_when_config_too_low(monkeypatch, disaster_zone_scenario):
    monkeypatch.setattr(CONFIG.mission, "drone_count", 1)
    with pytest.raises(SystemExit, match="len\\(drones\\)=3"):
        wr._check_drone_count(disaster_zone_scenario)


def test_check_drone_count_message_names_scenario_id(monkeypatch, smoke_scenario):
    monkeypatch.setattr(CONFIG.mission, "drone_count", 5)
    with pytest.raises(SystemExit) as exc_info:
        wr._check_drone_count(smoke_scenario)
    assert smoke_scenario.scenario_id in str(exc_info.value)


# --- --duration flag (slice E) -------------------------------------------------


def test_waypoint_runner_duration_default_is_none():
    args = wr._parse_args(["--scenario", "single_drone_smoke"])
    assert args.duration is None


def test_waypoint_runner_duration_parsed_as_float():
    args = wr._parse_args(["--scenario", "single_drone_smoke", "--duration", "12.5"])
    assert args.duration == 12.5


def test_frame_server_duration_default_is_none():
    args = fs._parse_args(["--scenario", "single_drone_smoke"])
    assert args.duration is None


def test_frame_server_duration_parsed_as_float():
    args = fs._parse_args(["--scenario", "single_drone_smoke", "--duration", "7"])
    assert args.duration == 7.0


def test_waypoint_runner_main_exits_after_duration(monkeypatch, fake_redis):
    """End-to-end: main() must return 0 within roughly --duration seconds
    when the flag is set. We use a very short duration + fast tick rate so
    the test wraps up under the 30s pytest timeout cap."""
    import time

    monkeypatch.setattr(CONFIG.mission, "drone_count", 1)  # smoke has 1 drone
    monkeypatch.setattr("redis.Redis.from_url", staticmethod(lambda url, **kw: fake_redis))

    t0 = time.monotonic()
    rc = wr.main(
        [
            "--scenario", "single_drone_smoke",
            "--duration", "0.3",
            "--tick-hz", "10",
        ]
    )
    elapsed = time.monotonic() - t0
    assert rc == 0
    # Should exit within ~duration plus one tick — generous upper bound for
    # CI noise. Lower bound: at least the duration itself.
    assert 0.2 <= elapsed <= 2.0, f"elapsed={elapsed}"


def test_frame_server_main_exits_after_duration(monkeypatch, fake_redis, tmp_path):
    """Same end-to-end check on frame_server — needs the fixtures dir present
    (single_drone_smoke references one frame file)."""
    import time

    monkeypatch.setattr("redis.Redis.from_url", staticmethod(lambda url, **kw: fake_redis))

    t0 = time.monotonic()
    rc = fs.main(
        [
            "--scenario", "single_drone_smoke",
            "--duration", "0.3",
            "--frame-hz", "10",
        ]
    )
    elapsed = time.monotonic() - t0
    assert rc == 0
    assert 0.2 <= elapsed <= 2.0, f"elapsed={elapsed}"
