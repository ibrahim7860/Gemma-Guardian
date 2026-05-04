"""Wire-level tests for MeshSimulator: ingest drone states, forward broadcasts.

Exercises the simulator against fakeredis. Avoids spinning up the run_forever
loop — tests drive ingest_state / forward_broadcast directly so flakiness from
threading is excluded.
"""
from __future__ import annotations

import json
from typing import List

import pytest

from agents.mesh_simulator.main import MeshSimulator
from agents.mesh_simulator.range_filter import EGS_NODE_ID
from shared.contracts.topics import (
    swarm_broadcast_channel,
    swarm_visible_to_channel,
    per_drone_state_channel,
)


def _subscribe(fake_redis, channel: str):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(channel)
    pubsub.get_message(timeout=0.1)
    return pubsub


def _drain_messages(pubsub) -> List[bytes]:
    out = []
    while True:
        msg = pubsub.get_message(timeout=0.05)
        if msg is None:
            break
        if msg["type"] == "message":
            out.append(msg["data"])
    return out


# Reusable state-message factory.
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


def _broadcast(sender_id: str, lat: float, lon: float) -> dict:
    return {
        "broadcast_id": f"{sender_id}_b001",
        "sender_id": sender_id,
        "sender_position": {"lat": lat, "lon": lon, "alt": 25.0},
        "timestamp": "2026-05-15T14:23:11.342Z",
        "broadcast_type": "finding",
        "payload": {
            "type": "victim",
            "severity": 4,
            "gps_lat": lat,
            "gps_lon": lon,
            "confidence": 0.78,
            "visual_description": "Person prone, partially covered by debris.",
        },
    }


class TestForwardBroadcast:
    def test_in_range_drone_receives_broadcast(self, fake_redis):
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.ingest_state(_state_msg("drone1", 34.0000, -118.5))
        sim.ingest_state(_state_msg("drone2", 34.000898, -118.5))  # ~100m north
        ps = _subscribe(fake_redis, swarm_visible_to_channel("drone2"))
        bcast = _broadcast("drone1", 34.0000, -118.5)
        sim.forward_broadcast("drone1", json.dumps(bcast).encode())
        msgs = _drain_messages(ps)
        assert len(msgs) == 1
        decoded = json.loads(msgs[0])
        assert decoded["sender_id"] == "drone1"

    def test_out_of_range_drone_does_not_receive_broadcast(self, fake_redis):
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.ingest_state(_state_msg("drone1", 34.0000, -118.5))
        sim.ingest_state(_state_msg("drone3", 34.00898, -118.5))  # ~1km north
        ps = _subscribe(fake_redis, swarm_visible_to_channel("drone3"))
        bcast = _broadcast("drone1", 34.0000, -118.5)
        sim.forward_broadcast("drone1", json.dumps(bcast).encode())
        msgs = _drain_messages(ps)
        assert msgs == []

    def test_sender_does_not_receive_own_broadcast(self, fake_redis):
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.ingest_state(_state_msg("drone1", 34.0000, -118.5))
        sim.ingest_state(_state_msg("drone2", 34.000898, -118.5))
        ps = _subscribe(fake_redis, swarm_visible_to_channel("drone1"))
        bcast = _broadcast("drone1", 34.0000, -118.5)
        sim.forward_broadcast("drone1", json.dumps(bcast).encode())
        msgs = _drain_messages(ps)
        assert msgs == []

    def test_broadcast_with_unknown_sender_id_dropped(self, fake_redis):
        """If we have no position for the sender yet, we cannot range-gate. Drop quietly."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.ingest_state(_state_msg("drone2", 34.000898, -118.5))
        ps = _subscribe(fake_redis, swarm_visible_to_channel("drone2"))
        bcast = _broadcast("drone1", 34.0, -118.5)
        sim.forward_broadcast("drone1", json.dumps(bcast).encode())
        msgs = _drain_messages(ps)
        assert msgs == []


class TestChannelExtraction:
    def test_extracts_drone_id_from_state_channel(self):
        from agents.mesh_simulator.main import drone_id_from_state_channel
        assert drone_id_from_state_channel("drones.drone1.state") == "drone1"
        assert drone_id_from_state_channel("drones.drone42.state") == "drone42"
        assert drone_id_from_state_channel("not.a.channel") is None

    def test_extracts_drone_id_from_broadcast_channel(self):
        from agents.mesh_simulator.main import drone_id_from_broadcast_channel
        assert drone_id_from_broadcast_channel("swarm.broadcasts.drone1") == "drone1"
        assert drone_id_from_broadcast_channel("swarm.broadcasts.drone7") == "drone7"
        assert drone_id_from_broadcast_channel("foo.bar") is None
