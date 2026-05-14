"""Unit coverage for `shared.contracts.zones`.

The module is consumed by both EGS (`agents/egs_agent/scenario_state.py`) and
the drone agent (`agents/drone_agent/zone_provider.py`). It is the single
source of truth for mission-zone bbox/polygon math after the 2026-05-13
plan-eng-review A1 fix.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from shared.contracts.zones import (
    ZONE_BUFFER_M,
    mission_zone_bbox,
    mission_zone_polygon,
    polygon_to_bbox,
)
from sim.scenario import load_scenario

_SCENARIO_DIR = Path(__file__).resolve().parents[2] / "sim" / "scenarios"


def _scenario(name: str = "disaster_zone_v1"):
    return load_scenario(_SCENARIO_DIR / f"{name}.yaml")


def test_mission_zone_polygon_is_closed_ccw():
    poly = mission_zone_polygon(_scenario())
    assert len(poly) == 5
    assert poly[0] == poly[-1], "polygon must be closed"
    # CCW signed area: shoelace formula; positive => CCW (lat=y, lon=x basis).
    area = 0.0
    for i in range(len(poly) - 1):
        x1, y1 = poly[i][1], poly[i][0]
        x2, y2 = poly[i + 1][1], poly[i + 1][0]
        area += (x2 - x1) * (y2 + y1)
    # Shoelace signed-area is positive for CW in standard (x,y) basis; flipped
    # because we ordered SW->SE->NE->NW which is CCW in lat/lon space.
    assert area < 0, f"polygon must be CCW; signed area = {area}"


def test_mission_zone_polygon_encloses_all_waypoints():
    scenario = _scenario()
    poly = mission_zone_polygon(scenario, buffer_m=0.0)  # tight, no slack
    lat_min = poly[0][0]
    lat_max = poly[2][0]
    lon_min = poly[0][1]
    lon_max = poly[2][1]
    for drone in scenario.drones:
        for wp in drone.waypoints:
            assert lat_min <= wp.lat <= lat_max, f"{wp.id} lat {wp.lat} outside [{lat_min}, {lat_max}]"
            assert lon_min <= wp.lon <= lon_max, f"{wp.id} lon {wp.lon} outside [{lon_min}, {lon_max}]"


def test_mission_zone_polygon_default_buffer_outsets_50m():
    scenario = _scenario()
    tight = mission_zone_polygon(scenario, buffer_m=0.0)
    loose = mission_zone_polygon(scenario)  # default ZONE_BUFFER_M = 50.0
    # Buffer adds dlat = 50 / 111320 ~ 4.49e-4 to each side.
    expected_dlat = ZONE_BUFFER_M / 111_320.0
    assert loose[0][0] == pytest.approx(tight[0][0] - expected_dlat, abs=1e-9)
    assert loose[2][0] == pytest.approx(tight[2][0] + expected_dlat, abs=1e-9)


def test_polygon_to_bbox_rectangular():
    poly = [[34.0, -118.5], [34.0, -118.4], [34.1, -118.4], [34.1, -118.5], [34.0, -118.5]]
    bbox = polygon_to_bbox(poly)
    assert bbox == {"lat_min": 34.0, "lat_max": 34.1, "lon_min": -118.5, "lon_max": -118.4}


def test_polygon_to_bbox_non_rectangular_returns_enclosing_bbox():
    # L-shaped polygon: bbox is strict superset, by design.
    poly = [[0.0, 0.0], [0.0, 2.0], [1.0, 2.0], [1.0, 1.0], [2.0, 1.0], [2.0, 0.0], [0.0, 0.0]]
    bbox = polygon_to_bbox(poly)
    assert bbox == {"lat_min": 0.0, "lat_max": 2.0, "lon_min": 0.0, "lon_max": 2.0}


def test_polygon_to_bbox_rejects_too_few_points():
    with pytest.raises(ValueError):
        polygon_to_bbox([[0.0, 0.0], [1.0, 1.0]])


def test_polygon_to_bbox_rejects_empty():
    with pytest.raises(ValueError):
        polygon_to_bbox([])


def test_polygon_to_bbox_rejects_malformed_point():
    with pytest.raises(ValueError):
        polygon_to_bbox([[0.0, 0.0], [1.0], [2.0, 2.0]])


def test_mission_zone_bbox_matches_polygon_corner_extraction():
    scenario = _scenario()
    poly = mission_zone_polygon(scenario)
    bbox = mission_zone_bbox(scenario)
    assert bbox["lat_min"] == poly[0][0]
    assert bbox["lat_max"] == poly[2][0]
    assert bbox["lon_min"] == poly[0][1]
    assert bbox["lon_max"] == poly[2][1]
