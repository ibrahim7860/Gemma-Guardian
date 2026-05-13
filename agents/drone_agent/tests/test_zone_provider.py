"""Unit coverage for `agents.drone_agent.zone_provider.ZoneProvider`."""
from __future__ import annotations

from pathlib import Path

from agents.drone_agent.zone_provider import ZoneProvider
from shared.contracts.zones import mission_zone_polygon
from sim.scenario import load_scenario

_SCENARIO_DIR = Path(__file__).resolve().parents[3] / "sim" / "scenarios"


def _scenario(name: str = "disaster_zone_v1"):
    return load_scenario(_SCENARIO_DIR / f"{name}.yaml")


def test_bootstrap_returns_mission_wide_polygon():
    """The provider's bootstrap must equal what EGS publishes on first egs.state."""
    scenario = _scenario()
    provider = ZoneProvider(scenario)
    assert provider.current() == {"polygon": mission_zone_polygon(scenario)}


def test_bootstrap_encloses_every_drones_waypoints():
    """Mission-wide semantics: every drone's waypoints fall inside the bootstrap polygon."""
    from agents.drone_agent.validation import _point_in_polygon

    scenario = _scenario()
    polygon = ZoneProvider(scenario).current()["polygon"]
    for drone in scenario.drones:
        for wp in drone.waypoints:
            assert _point_in_polygon(wp.lat, wp.lon, polygon, tolerance_m=0.0), (
                f"waypoint {wp.id} at ({wp.lat}, {wp.lon}) must be inside bootstrap polygon"
            )


def test_update_from_rectangular_polygon():
    provider = ZoneProvider(_scenario())
    new_poly = [
        [34.0, -118.5], [34.0, -118.4], [34.1, -118.4], [34.1, -118.5], [34.0, -118.5],
    ]
    assert provider.update_from_polygon(new_poly) is True
    assert provider.current() == {"polygon": new_poly}


def test_update_from_non_rectangular_polygon_preserved_verbatim():
    """IRON RULE: L-shaped polygon is stored verbatim, NOT bbox-compressed.

    Pins the intentional tightening of the 2026-05-13 PIP migration. Before:
    `update_from_polygon` ran `polygon_to_bbox` and stored a 4-key bbox,
    losing the L's concavity. After: the polygon is stored as-is so
    `_within_zone` can reject findings inside the bbox but outside the L.
    """
    provider = ZoneProvider(_scenario())
    l_shaped = [
        [0.0, 0.0], [0.0, 2.0], [1.0, 2.0], [1.0, 1.0], [2.0, 1.0], [2.0, 0.0], [0.0, 0.0],
    ]
    assert provider.update_from_polygon(l_shaped) is True
    assert provider.current() == {"polygon": l_shaped}


def test_update_overrides_bootstrap():
    provider = ZoneProvider(_scenario())
    bootstrap = provider.current()
    new_poly = [[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]
    provider.update_from_polygon(new_poly)
    assert provider.current() != bootstrap
    assert provider.current() == {"polygon": new_poly}


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


def test_update_coerces_string_numeric_points_to_float():
    """Defensive: schema validation upstream should reject non-float coords,
    but if a caller bypasses it (or schema rules drift), the stored polygon
    must still be all-float so `_point_in_polygon`'s numeric comparisons
    don't TypeError on str/float."""
    provider = ZoneProvider(_scenario())
    mixed = [["34.0", "-118.5"], [34.0, -118.4], [34.1, -118.4],
             [34.1, "-118.5"], ["34.0", "-118.5"]]
    assert provider.update_from_polygon(mixed) is True
    polygon = provider.current()["polygon"]
    for point in polygon:
        assert isinstance(point[0], float)
        assert isinstance(point[1], float)


def test_current_returns_deep_copy():
    """Consumers must not be able to mutate the provider's internal polygon.

    Stronger than the bbox-era shallow-copy guarantee: with lists-of-lists,
    a shallow copy would let `snapshot["polygon"][0][0] = 999` corrupt
    state. The provider must deep-copy.
    """
    provider = ZoneProvider(_scenario())
    snapshot = provider.current()
    snapshot["polygon"][0][0] = 999.0
    snapshot["polygon"].append([0.0, 0.0])
    assert provider.current()["polygon"][0][0] != 999.0
    assert provider.current()["polygon"][-1] != [0.0, 0.0]
