"""Tests for the scenario-origin helper used by scripts/launch_swarm.sh.

The helper is what plumbs the EGS anchor into the mesh simulator at launch
time; without it the resilience scenario can't observe drone↔EGS link drops.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from sim.scenario_origin import main, scenario_origin

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_scenario_origin_resilience_v1():
    assert scenario_origin("resilience_v1") == (34.0, -118.5)


def test_scenario_origin_disaster_zone_v1():
    assert scenario_origin("disaster_zone_v1") == (34.0, -118.5)


def test_scenario_origin_accepts_full_path():
    p = REPO_ROOT / "sim" / "scenarios" / "resilience_v1.yaml"
    assert scenario_origin(str(p)) == (34.0, -118.5)


def test_scenario_origin_unknown_scenario_raises():
    with pytest.raises(FileNotFoundError, match="scenario not found"):
        scenario_origin("nope_does_not_exist")


def test_main_prints_lat_comma_lon_no_trailing_newline(capsys):
    rc = main(["resilience_v1"])
    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == "34.0,-118.5"


def test_cli_subprocess_round_trip():
    """Regression: bash captures stdout verbatim; the script must not emit a
    trailing newline that would corrupt the EGS_LAT/EGS_LON split in
    launch_swarm.sh."""
    out = subprocess.check_output(
        [sys.executable, str(REPO_ROOT / "sim" / "scenario_origin.py"), "resilience_v1"],
    ).decode()
    assert out == "34.0,-118.5"


def test_main_unknown_scenario_returns_nonzero(capsys):
    rc = main(["definitely_not_a_scenario"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "scenario not found" in captured.err


def test_main_wrong_arg_count_returns_2(capsys):
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 2
    assert "usage:" in captured.err
