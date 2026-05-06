"""Zone bounds derivation: bbox of (home + waypoints) plus a buffer."""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.drone_agent.zone_bounds import derive_zone_bounds_from_scenario
from sim.scenario import load_scenario


REPO_ROOT = Path(__file__).resolve().parents[3]
DISASTER_ZONE = REPO_ROOT / "sim" / "scenarios" / "disaster_zone_v1.yaml"


def test_drone1_bbox_covers_home_and_all_waypoints():
    scenario = load_scenario(DISASTER_ZONE)
    bounds = derive_zone_bounds_from_scenario(scenario, "drone1", buffer_m=0.0)

    # drone1 home (34.0001, -118.5001), waypoints span 34.0002–34.0008 in lat
    # and -118.5004–-118.5002 in lon.
    assert bounds["lat_min"] == pytest.approx(34.0001)
    assert bounds["lat_max"] == pytest.approx(34.0008)
    assert bounds["lon_min"] == pytest.approx(-118.5004)
    assert bounds["lon_max"] == pytest.approx(-118.5001)


def test_buffer_expands_bounds_in_meters():
    scenario = load_scenario(DISASTER_ZONE)
    tight = derive_zone_bounds_from_scenario(scenario, "drone1", buffer_m=0.0)
    loose = derive_zone_bounds_from_scenario(scenario, "drone1", buffer_m=100.0)

    # 100m buffer ≈ 0.0009 deg latitude, ≈ 0.00109 deg longitude at lat 34.
    assert loose["lat_min"] < tight["lat_min"]
    assert loose["lat_max"] > tight["lat_max"]
    assert loose["lon_min"] < tight["lon_min"]
    assert loose["lon_max"] > tight["lon_max"]
    assert (tight["lat_min"] - loose["lat_min"]) == pytest.approx(0.0009, abs=1e-4)


def test_unknown_drone_raises_keyerror():
    scenario = load_scenario(DISASTER_ZONE)
    with pytest.raises(KeyError, match="ghost_drone"):
        derive_zone_bounds_from_scenario(scenario, "ghost_drone", buffer_m=0.0)
