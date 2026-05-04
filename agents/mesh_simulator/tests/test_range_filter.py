"""Tests for agents/mesh_simulator/range_filter.py — pure logic, no Redis.

Covers receiver enumeration, sender exclusion, range thresholds, and
EGS-link gating. All distances use the haversine helper from sim/geo.py.
"""
from __future__ import annotations

import pytest

from agents.mesh_simulator.range_filter import (
    EGS_NODE_ID,
    filter_recipients,
    in_range_pairs,
)


# Demo origin per docs/14-disaster-scene-design.md
ORIGIN_LAT = 34.0
ORIGIN_LON = -118.5

# 100 m north of origin, 100 m east, 1 km north (out of 200 m mesh range).
NORTH_100M = (34.000898, -118.5)        # ~100 m
EAST_100M = (34.0, -118.498917)         # ~100 m
NORTH_1KM = (34.00898, -118.5)          # ~1 km


@pytest.fixture
def positions_three_drones():
    # drone1 at origin, drone2 100m north (in range), drone3 1km north (out of range).
    return {
        "drone1": (ORIGIN_LAT, ORIGIN_LON),
        "drone2": NORTH_100M,
        "drone3": NORTH_1KM,
    }


class TestFilterRecipients:
    def test_in_range_peers_returned(self, positions_three_drones):
        recv = filter_recipients(
            sender_id="drone1",
            sender_pos=positions_three_drones["drone1"],
            drone_positions=positions_three_drones,
            range_m=200.0,
        )
        assert "drone2" in recv

    def test_out_of_range_peers_dropped(self, positions_three_drones):
        recv = filter_recipients(
            sender_id="drone1",
            sender_pos=positions_three_drones["drone1"],
            drone_positions=positions_three_drones,
            range_m=200.0,
        )
        assert "drone3" not in recv

    def test_sender_excluded_from_recipients(self, positions_three_drones):
        recv = filter_recipients(
            sender_id="drone1",
            sender_pos=positions_three_drones["drone1"],
            drone_positions=positions_three_drones,
            range_m=10_000.0,
        )
        assert "drone1" not in recv

    def test_recipients_deterministically_sorted(self):
        positions = {
            "drone3": NORTH_100M,
            "drone1": (ORIGIN_LAT, ORIGIN_LON),
            "drone2": EAST_100M,
        }
        recv = filter_recipients(
            sender_id="drone1",
            sender_pos=positions["drone1"],
            drone_positions=positions,
            range_m=200.0,
        )
        assert recv == sorted(recv)

    def test_egs_position_treated_as_drone_when_provided(self, positions_three_drones):
        # If "egs" is in drone_positions, it should be considered a recipient
        # within the same range (the dedicated EGS-link range is enforced
        # separately by in_range_pairs / the runner's dispatch path).
        positions = {**positions_three_drones, EGS_NODE_ID: NORTH_100M}
        recv = filter_recipients(
            sender_id="drone1",
            sender_pos=positions["drone1"],
            drone_positions=positions,
            range_m=200.0,
        )
        assert EGS_NODE_ID in recv


class TestInRangePairs:
    def test_full_adjacency_for_close_swarm(self):
        positions = {
            "drone1": (ORIGIN_LAT, ORIGIN_LON),
            "drone2": NORTH_100M,
            "drone3": EAST_100M,
        }
        adj = in_range_pairs(positions, range_m=200.0)
        # Each drone should see the other two as in-range.
        assert sorted(adj["drone1"]) == ["drone2", "drone3"]
        assert sorted(adj["drone2"]) == ["drone1", "drone3"]
        assert sorted(adj["drone3"]) == ["drone1", "drone2"]

    def test_isolated_drone_has_empty_neighbours(self):
        positions = {
            "drone1": (ORIGIN_LAT, ORIGIN_LON),
            "drone2": NORTH_100M,
            "drone3": NORTH_1KM,
        }
        adj = in_range_pairs(positions, range_m=200.0)
        assert adj["drone3"] == []

    def test_egs_link_range_separately_enforced(self):
        positions = {
            "drone1": (ORIGIN_LAT, ORIGIN_LON),
            "drone2": NORTH_1KM,            # 1km, outside 500m EGS link
            EGS_NODE_ID: (ORIGIN_LAT, ORIGIN_LON),
        }
        adj = in_range_pairs(
            positions,
            range_m=200.0,
            egs_link_range_m=500.0,
        )
        # drone1 within 500m of EGS → linked
        assert EGS_NODE_ID in adj["drone1"]
        # drone2 beyond 500m → not linked
        assert EGS_NODE_ID not in adj["drone2"]
