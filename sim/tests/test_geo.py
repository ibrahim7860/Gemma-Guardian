"""Tests for sim/geo.py — haversine, meters↔degrees, interpolation.

Reference values: 1° latitude ≈ 111,319 m. WGS-84 ellipsoidal corrections are out
of scope for the 200m × 200m demo grid — sphere approximation is fine to <0.5%.
"""
from __future__ import annotations

import math

import pytest

from sim.geo import (
    haversine_meters,
    interpolate,
    meters_to_lat_degrees,
    meters_to_lon_degrees,
)


# Demo origin per docs/14-disaster-scene-design.md.
ORIGIN = (34.0000, -118.5000)


class TestHaversineMeters:
    def test_identical_points_zero(self):
        assert haversine_meters(ORIGIN, ORIGIN) == pytest.approx(0.0, abs=1e-6)

    def test_one_degree_latitude_is_about_111km(self):
        north = (ORIGIN[0] + 1.0, ORIGIN[1])
        d = haversine_meters(ORIGIN, north)
        assert d == pytest.approx(111_320, rel=0.005)

    def test_symmetric(self):
        a = ORIGIN
        b = (34.001, -118.501)
        assert haversine_meters(a, b) == pytest.approx(haversine_meters(b, a))

    def test_known_short_distance_about_100m(self):
        # 100 m east at lat 34: 100 / (111319 * cos(34°)) ≈ 0.001084°
        east = (ORIGIN[0], ORIGIN[1] + 0.001084)
        d = haversine_meters(ORIGIN, east)
        assert d == pytest.approx(100, rel=0.01)


class TestMetersToDegrees:
    def test_lat_degrees_round_trip(self):
        # 1 m → ~1/111319 degrees, regardless of latitude
        deg = meters_to_lat_degrees(1.0)
        assert deg == pytest.approx(1 / 111_319, rel=1e-4)

    def test_lon_degrees_scales_with_cos_lat(self):
        deg_eq = meters_to_lon_degrees(1.0, latitude_deg=0.0)
        deg_la = meters_to_lon_degrees(1.0, latitude_deg=34.0)
        # cos(34°) ≈ 0.829
        assert deg_la == pytest.approx(deg_eq / math.cos(math.radians(34.0)), rel=1e-4)

    def test_lon_degrees_at_equator_equals_lat_degrees(self):
        assert meters_to_lon_degrees(50.0, latitude_deg=0.0) == pytest.approx(
            meters_to_lat_degrees(50.0), rel=1e-4
        )


class TestInterpolate:
    def test_zero_fraction_returns_start(self):
        a = (34.0001, -118.5001, 25.0)
        b = (34.0010, -118.5010, 50.0)
        assert interpolate(a, b, 0.0) == pytest.approx(a)

    def test_one_fraction_returns_end(self):
        a = (34.0001, -118.5001, 25.0)
        b = (34.0010, -118.5010, 50.0)
        assert interpolate(a, b, 1.0) == pytest.approx(b)

    def test_half_fraction_is_midpoint(self):
        a = (34.0001, -118.5001, 25.0)
        b = (34.0011, -118.5011, 75.0)
        mid = interpolate(a, b, 0.5)
        assert mid[0] == pytest.approx(34.0006, abs=1e-6)
        assert mid[1] == pytest.approx(-118.5006, abs=1e-6)
        assert mid[2] == pytest.approx(50.0, abs=1e-6)

    def test_clamps_below_zero(self):
        a = (34.0, -118.0, 0.0)
        b = (34.1, -118.1, 100.0)
        assert interpolate(a, b, -0.5) == pytest.approx(a)

    def test_clamps_above_one(self):
        a = (34.0, -118.0, 0.0)
        b = (34.1, -118.1, 100.0)
        assert interpolate(a, b, 1.5) == pytest.approx(b)
