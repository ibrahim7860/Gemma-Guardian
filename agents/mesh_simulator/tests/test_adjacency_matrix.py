"""Tests for the periodic adjacency matrix publish on mesh.adjacency_matrix."""
from __future__ import annotations

import json

import pytest

from agents.mesh_simulator.main import MeshSimulator
from agents.mesh_simulator.range_filter import EGS_NODE_ID
from shared.contracts.topics import MESH_ADJACENCY


def _subscribe(fake_redis, channel: str):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(channel)
    pubsub.get_message(timeout=0.1)
    return pubsub


def _state_msg(drone_id: str, lat: float, lon: float) -> dict:
    return {
        "drone_id": drone_id,
        "timestamp": "2026-05-15T14:23:11.342Z",
        "position": {"lat": lat, "lon": lon, "alt": 25.0},
        "velocity": {"vx": 0.0, "vy": 0.0, "vz": 0.0},
        "battery_pct": 100,
        "heading_deg": 0,
        "current_task": None,
        "current_waypoint_id": None,
        "assigned_survey_points_remaining": 0,
        "last_action": "none",
        "last_action_timestamp": None,
        "validation_failures_total": 0,
        "findings_count": 0,
        "in_mesh_range_of": [],
        "agent_status": "active",
    }


class TestAdjacencyPublish:
    def test_publish_emits_json_on_mesh_adjacency_channel(self, fake_redis):
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.ingest_state(_state_msg("drone1", 34.0000, -118.5))
        sim.ingest_state(_state_msg("drone2", 34.000898, -118.5))
        ps = _subscribe(fake_redis, MESH_ADJACENCY)
        sim.publish_adjacency()
        msg = ps.get_message(timeout=0.1)
        # subscribe ack already drained; first message should be ours
        assert msg is not None
        assert msg["type"] == "message"
        decoded = json.loads(msg["data"])
        assert "drone1" in decoded
        assert "drone2" in decoded
        assert "drone2" in decoded["drone1"]

    def test_includes_egs_node_when_egs_position_seeded(self, fake_redis):
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(34.0000, -118.5)
        sim.ingest_state(_state_msg("drone1", 34.0000, -118.5))
        ps = _subscribe(fake_redis, MESH_ADJACENCY)
        sim.publish_adjacency()
        msg = ps.get_message(timeout=0.1)
        decoded = json.loads(msg["data"])
        assert EGS_NODE_ID in decoded
        assert "drone1" in decoded[EGS_NODE_ID]

    def test_isolated_drone_has_empty_neighbours(self, fake_redis):
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.ingest_state(_state_msg("drone1", 34.0000, -118.5))
        sim.ingest_state(_state_msg("drone2", 34.00898, -118.5))  # 1km away
        ps = _subscribe(fake_redis, MESH_ADJACENCY)
        sim.publish_adjacency()
        msg = ps.get_message(timeout=0.1)
        decoded = json.loads(msg["data"])
        assert decoded["drone1"] == []
        assert decoded["drone2"] == []

    def test_adjacency_is_symmetric(self, fake_redis):
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.ingest_state(_state_msg("drone1", 34.0000, -118.5))
        sim.ingest_state(_state_msg("drone2", 34.000898, -118.5))
        sim.ingest_state(_state_msg("drone3", 34.0, -118.498917))
        ps = _subscribe(fake_redis, MESH_ADJACENCY)
        sim.publish_adjacency()
        msg = ps.get_message(timeout=0.1)
        decoded = json.loads(msg["data"])
        for a, neighbours in decoded.items():
            for b in neighbours:
                assert a in decoded[b], f"asymmetric edge {a}↔{b}: {decoded}"
