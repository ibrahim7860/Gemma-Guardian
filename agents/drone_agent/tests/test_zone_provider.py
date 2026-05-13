"""Unit coverage for `agents.drone_agent.zone_provider.ZoneProvider`."""
from __future__ import annotations

from pathlib import Path

from agents.drone_agent.zone_provider import ZoneProvider
from shared.contracts.zones import mission_zone_bbox
from sim.scenario import load_scenario

_SCENARIO_DIR = Path(__file__).resolve().parents[3] / "sim" / "scenarios"


def _scenario(name: str = "disaster_zone_v1"):
    return load_scenario(_SCENARIO_DIR / f"{name}.yaml")


def test_bootstrap_returns_mission_wide_bbox():
    """The provider's bootstrap must equal what EGS publishes on first egs.state."""
    scenario = _scenario()
    provider = ZoneProvider(scenario)
    assert provider.current() == mission_zone_bbox(scenario)


def test_bootstrap_encloses_every_drones_waypoints():
    """Mission-wide semantics: every drone's waypoints fall inside the bootstrap bbox."""
    scenario = _scenario()
    bbox = ZoneProvider(scenario).current()
    for drone in scenario.drones:
        for wp in drone.waypoints:
            assert bbox["lat_min"] <= wp.lat <= bbox["lat_max"]
            assert bbox["lon_min"] <= wp.lon <= bbox["lon_max"]


def test_update_from_rectangular_polygon():
    provider = ZoneProvider(_scenario())
    new_poly = [
        [34.0, -118.5], [34.0, -118.4], [34.1, -118.4], [34.1, -118.5], [34.0, -118.5],
    ]
    assert provider.update_from_polygon(new_poly) is True
    assert provider.current() == {
        "lat_min": 34.0, "lat_max": 34.1, "lon_min": -118.5, "lon_max": -118.4,
    }


def test_update_from_non_rectangular_polygon_returns_enclosing_bbox():
    """Bbox-of-polygon is a strict superset for non-rectangular shapes (by design)."""
    provider = ZoneProvider(_scenario())
    l_shaped = [
        [0.0, 0.0], [0.0, 2.0], [1.0, 2.0], [1.0, 1.0], [2.0, 1.0], [2.0, 0.0], [0.0, 0.0],
    ]
    assert provider.update_from_polygon(l_shaped) is True
    assert provider.current() == {"lat_min": 0.0, "lat_max": 2.0, "lon_min": 0.0, "lon_max": 2.0}


def test_update_overrides_bootstrap():
    provider = ZoneProvider(_scenario())
    bootstrap = provider.current()
    new_poly = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
    provider.update_from_polygon(new_poly)
    assert provider.current() != bootstrap
    assert provider.current() == {"lat_min": 0.0, "lat_max": 1.0, "lon_min": 0.0, "lon_max": 1.0}


def test_update_rejects_polygon_with_fewer_than_three_points():
    provider = ZoneProvider(_scenario())
    bootstrap = provider.current()
    assert provider.update_from_polygon([[0.0, 0.0], [1.0, 1.0]]) is False
    assert provider.current() == bootstrap  # preserved


def test_update_rejects_empty_polygon():
    provider = ZoneProvider(_scenario())
    bootstrap = provider.current()
    assert provider.update_from_polygon([]) is False
    assert provider.current() == bootstrap


def test_update_rejects_malformed_point():
    provider = ZoneProvider(_scenario())
    bootstrap = provider.current()
    assert provider.update_from_polygon([[0.0, 0.0], [1.0], [2.0, 2.0]]) is False
    assert provider.current() == bootstrap


def test_current_returns_defensive_copy():
    """Consumers must not be able to mutate the provider's internal state."""
    provider = ZoneProvider(_scenario())
    snapshot = provider.current()
    snapshot["lat_min"] = 999.0
    assert provider.current()["lat_min"] != 999.0
