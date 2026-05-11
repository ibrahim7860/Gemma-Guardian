"""Mesh simulator CLI — `--scenario` derives EGS position from scenario YAML.

Closes the silent-zero-findings bug class (PR #41/#42/#43) by making the
scenario YAML the single source of truth for the EGS position. Explicit
``--egs-lat``/``--egs-lon`` remain available as an override (used by the four
synthetic-position e2e tests in ``frontend/ws_bridge/tests/`` that don't load
a real scenario).

Precedence under test:
  1. Explicit --egs-lat/--egs-lon wins (warn if --scenario also set).
  2. Else --scenario → origin.lat/.lon.
  3. Else exit 2 with a clear stderr ERROR.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr
from pathlib import Path
from typing import List, Optional, Tuple
from unittest.mock import patch

import pytest

from agents.mesh_simulator import main as mesh_main


_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCENARIO_ID = "disaster_zone_v1"
# All shipped scenarios share this origin; locked here so a scenario edit that
# shifts the origin is caught by this test rather than masked by it.
_EXPECTED_LAT = 34.0000
_EXPECTED_LON = -118.5000


class _FakeRedisFactory:
    """Stand-in for ``redis.Redis.from_url`` so tests don't need a live broker."""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def __call__(self, url: str):  # mimics redis.Redis.from_url signature
        self.calls.append(url)

        class _StubRedis:
            def pubsub(self_inner):  # pragma: no cover — never reached
                raise RuntimeError("pubsub() should not be called in CLI tests")

        return _StubRedis()


class _CapturedSim:
    """Captures set_egs_position calls; aborts before run_forever."""

    instances: List["_CapturedSim"] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.egs_position: Optional[Tuple[float, float]] = None
        _CapturedSim.instances.append(self)

    def set_egs_position(self, lat: float, lon: float) -> None:
        self.egs_position = (lat, lon)

    def run_forever(self, *_args, **_kwargs) -> None:
        # Stop main() before it blocks. Tests assert on state captured up to here.
        raise _StopBeforeRun


class _StopBeforeRun(Exception):
    pass


@pytest.fixture(autouse=True)
def _reset_captured() -> None:
    _CapturedSim.instances.clear()


def _run_main(argv: List[str]) -> Tuple[int, str]:
    """Invoke mesh_main.main(argv) with redis + MeshSimulator stubbed.

    Returns (return_code, captured_stderr). run_forever is short-circuited via
    _StopBeforeRun; if the precedence logic returns early (exit 2 path), the
    return code is captured directly.
    """
    factory = _FakeRedisFactory()
    stderr_buf = io.StringIO()
    rc = 0
    with patch.object(mesh_main, "MeshSimulator", _CapturedSim), \
         patch("redis.Redis.from_url", factory), \
         redirect_stderr(stderr_buf):
        try:
            rc = mesh_main.main(argv)
        except _StopBeforeRun:
            rc = 0  # would have entered the blocking loop — success
    return rc, stderr_buf.getvalue()


def test_scenario_flag_loads_origin_for_known_id():
    rc, stderr = _run_main(["--scenario", _SCENARIO_ID])
    assert rc == 0, f"unexpected non-zero rc; stderr={stderr!r}"
    assert _CapturedSim.instances, "MeshSimulator was never instantiated"
    captured = _CapturedSim.instances[-1]
    assert captured.egs_position == (_EXPECTED_LAT, _EXPECTED_LON), (
        f"expected EGS at ({_EXPECTED_LAT}, {_EXPECTED_LON}) from scenario {_SCENARIO_ID!r}, "
        f"got {captured.egs_position}"
    )


def test_scenario_flag_accepts_path():
    scenario_path = _REPO_ROOT / "sim" / "scenarios" / f"{_SCENARIO_ID}.yaml"
    assert scenario_path.exists(), "scenario file is missing; test fixture broken"
    rc, stderr = _run_main(["--scenario", str(scenario_path)])
    assert rc == 0, f"unexpected non-zero rc; stderr={stderr!r}"
    assert _CapturedSim.instances[-1].egs_position == (_EXPECTED_LAT, _EXPECTED_LON)


def test_scenario_flag_unknown_id_errors():
    rc, stderr = _run_main(["--scenario", "definitely_not_a_real_scenario"])
    assert rc == 2, (
        f"main() must exit 2 on unknown scenario id (was: {rc}). "
        "A typo should give a clean error, not a Python stack trace."
    )
    assert "ERROR: scenario not found" in stderr, (
        f"clean stderr ERROR must explain the failure; got {stderr!r}"
    )
    assert "definitely_not_a_real_scenario" in stderr, (
        f"error must echo the bad scenario id; got {stderr!r}"
    )
    assert "scenarios" in stderr, (
        f"error must mention the path tried; got {stderr!r}"
    )
    # No MeshSimulator should be constructed when scenario load fails.
    assert not _CapturedSim.instances, (
        "MeshSimulator must not be constructed when scenario load fails"
    )


def test_explicit_egs_overrides_scenario_with_warning():
    rc, stderr = _run_main([
        "--scenario", _SCENARIO_ID,
        "--egs-lat", "12.3456",
        "--egs-lon", "-78.9012",
    ])
    assert rc == 0
    assert _CapturedSim.instances[-1].egs_position == (12.3456, -78.9012), (
        "explicit --egs-lat/--egs-lon must win when both flags are passed"
    )
    assert "WARN: --egs-lat/--egs-lon override" in stderr, (
        f"override warning must appear on stderr; got {stderr!r}"
    )


def test_no_flags_exits_with_clear_error():
    rc, stderr = _run_main([])
    assert rc == 2, (
        f"main() must exit 2 when no EGS configured (was: {rc}). "
        "Without this fail-fast guard, forward_finding silently drops every payload."
    )
    assert "ERROR: no EGS configured" in stderr, (
        f"clear stderr ERROR must explain the fix; got {stderr!r}"
    )
    assert "--scenario" in stderr and "--egs-lat" in stderr, (
        f"error message must list both valid flag forms; got {stderr!r}"
    )
    # No MeshSimulator should be instantiated when we exit early.
    assert not _CapturedSim.instances, (
        "MeshSimulator must not be constructed on the no-EGS-configured path"
    )
