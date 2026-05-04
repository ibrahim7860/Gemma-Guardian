"""Tests for the scenario-roster helper used by scripts/launch_swarm.sh."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sim.list_drones import list_drone_ids, main

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_list_drone_ids_disaster_zone_v1():
    assert list_drone_ids("disaster_zone_v1") == ["drone1", "drone2", "drone3"]


def test_list_drone_ids_single_drone_smoke():
    assert list_drone_ids("single_drone_smoke") == ["drone1"]


def test_list_drone_ids_accepts_full_path():
    p = REPO_ROOT / "sim" / "scenarios" / "disaster_zone_v1.yaml"
    assert list_drone_ids(str(p)) == ["drone1", "drone2", "drone3"]


def test_list_drone_ids_unknown_scenario_raises():
    with pytest.raises(FileNotFoundError, match="scenario not found"):
        list_drone_ids("nope_does_not_exist")


def test_main_prints_csv_to_stdout(capsys):
    rc = main(["disaster_zone_v1"])
    assert rc == 0
    captured = capsys.readouterr()
    assert captured.out == "drone1,drone2,drone3"
    # No trailing newline — bash will append one if it wants.
    assert not captured.out.endswith("\n")


def test_main_unknown_scenario_returns_nonzero(capsys):
    rc = main(["nope_does_not_exist"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "scenario not found" in captured.err


def test_main_wrong_argc_returns_2(capsys):
    rc = main([])
    assert rc == 2
    assert "usage" in capsys.readouterr().err


def test_helper_callable_from_subprocess():
    """End-to-end: invoke as ``python3 sim/list_drones.py <scenario>`` like
    bash does, and confirm clean stdout / no stderr."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "sim" / "list_drones.py"), "single_drone_smoke"],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert result.stdout == "drone1"
