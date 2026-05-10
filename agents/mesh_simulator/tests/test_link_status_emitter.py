"""Tests for mesh.link_status emission (Wave 2 Lane D).

Covers:
  - Geometric transitions (drone crosses egs_link_range boundary).
  - Scripted overrides (egs_link_drop / egs_link_restore).
  - 1 Hz heartbeat re-emit.
  - Schema-validation of every emitted payload.
"""
from __future__ import annotations

import json
import time
from typing import List

import pytest

from agents.mesh_simulator.main import MeshSimulator
from shared.contracts.schemas import validate_or_raise
from shared.contracts.topics import MESH_LINK_STATUS


ORIGIN = (34.0, -118.5)
NORTH_100M = (34.000898, -118.5)   # ~100 m
NORTH_1KM = (34.00898, -118.5)     # ~1 km — outside 500 m EGS link


def _subscribe(fake_redis, channel: str):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(channel)
    pubsub.get_message(timeout=0.1)
    return pubsub


def _drain_link_status(pubsub) -> List[dict]:
    """Drain all mesh.link_status payloads as decoded dicts."""
    out: List[dict] = []
    while True:
        msg = pubsub.get_message(timeout=0.05)
        if msg is None:
            break
        if msg["type"] == "message":
            out.append(json.loads(msg["data"]))
    return out


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


class TestGeometricTransitions:
    def test_link_status_emitted_on_geometric_drop(self, fake_redis):
        """Drone moves from 100 m to 1 km from EGS → one link=down event."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))  # baseline up
        sub = _subscribe(fake_redis, MESH_LINK_STATUS)

        sim.ingest_state(_state_msg("drone1", *NORTH_1KM))   # drop

        events = _drain_link_status(sub)
        assert len(events) == 1
        assert events[0]["drone_id"] == "drone1"
        assert events[0]["link"] == "down"
        assert events[0]["reason"] == "geometric"

    def test_link_status_emitted_on_geometric_restore(self, fake_redis):
        """Drone moves from 1 km to 100 m from EGS → one link=up event."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_1KM))   # baseline down
        sub = _subscribe(fake_redis, MESH_LINK_STATUS)

        sim.ingest_state(_state_msg("drone1", *NORTH_100M))  # restore

        events = _drain_link_status(sub)
        assert len(events) == 1
        assert events[0]["drone_id"] == "drone1"
        assert events[0]["link"] == "up"
        assert events[0]["reason"] == "geometric"

    def test_no_emission_when_state_unchanged(self, fake_redis):
        """Repeated in-range positions should not flood the channel."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))  # baseline
        sub = _subscribe(fake_redis, MESH_LINK_STATUS)

        sim.ingest_state(_state_msg("drone1", *NORTH_100M))
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))

        assert _drain_link_status(sub) == []


class TestScriptedTransitions:
    def test_link_status_emitted_on_scripted_drop(self, fake_redis):
        """egs_link_drop event → link_status with link=down, reason=scripted."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))  # baseline up
        sub = _subscribe(fake_redis, MESH_LINK_STATUS)

        sim.apply_scripted_event({
            "t": 120,
            "type": "egs_link_drop",
            "drone_id": "drone1",
            "wall_clock_iso_ms": "2026-05-15T14:23:11.342Z",
        })

        events = _drain_link_status(sub)
        assert len(events) == 1
        assert events[0]["drone_id"] == "drone1"
        assert events[0]["link"] == "down"
        assert events[0]["reason"] == "scripted"
        assert events[0]["t"] == 120

    def test_link_status_emitted_on_scripted_restore(self, fake_redis):
        """egs_link_restore event → link_status with link=up, reason=scripted."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))  # baseline up
        sim.apply_scripted_event({
            "t": 120,
            "type": "egs_link_drop",
            "drone_id": "drone1",
            "wall_clock_iso_ms": "2026-05-15T14:23:11.342Z",
        })
        sub = _subscribe(fake_redis, MESH_LINK_STATUS)

        sim.apply_scripted_event({
            "t": 180,
            "type": "egs_link_restore",
            "drone_id": "drone1",
            "wall_clock_iso_ms": "2026-05-15T14:24:11.342Z",
        })

        events = _drain_link_status(sub)
        assert len(events) == 1
        assert events[0]["drone_id"] == "drone1"
        assert events[0]["link"] == "up"
        assert events[0]["reason"] == "scripted"
        assert events[0]["t"] == 180

    def test_unknown_event_type_is_no_op(self, fake_redis):
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))
        sub = _subscribe(fake_redis, MESH_LINK_STATUS)

        sim.apply_scripted_event({
            "t": 60,
            "type": "drone_failure",
            "drone_id": "drone1",
            "wall_clock_iso_ms": "2026-05-15T14:22:11.342Z",
        })

        assert _drain_link_status(sub) == []


class TestHeartbeat:
    def test_heartbeat_emits_for_each_known_drone(self, fake_redis):
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))
        sim.ingest_state(_state_msg("drone2", *NORTH_100M))
        sub = _subscribe(fake_redis, MESH_LINK_STATUS)

        sim.publish_link_heartbeats()

        events = _drain_link_status(sub)
        ids = sorted(e["drone_id"] for e in events)
        assert ids == ["drone1", "drone2"]
        assert all(e["reason"] == "heartbeat" for e in events)

    def test_heartbeat_payload_reflects_effective_state(self, fake_redis):
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))   # in range, no override
        sim.ingest_state(_state_msg("drone2", *NORTH_100M))   # in range, override down
        sim.ingest_state(_state_msg("drone3", *NORTH_1KM))    # out of range
        sim.apply_scripted_event({
            "t": 120,
            "type": "egs_link_drop",
            "drone_id": "drone2",
            "wall_clock_iso_ms": "2026-05-15T14:23:11.342Z",
        })
        sub = _subscribe(fake_redis, MESH_LINK_STATUS)

        sim.publish_link_heartbeats()
        events = _drain_link_status(sub)
        by_id = {e["drone_id"]: e for e in events}
        assert by_id["drone1"]["link"] == "up"
        assert by_id["drone2"]["link"] == "down"   # forced by override
        assert by_id["drone3"]["link"] == "down"   # geometry
        assert all(e["reason"] == "heartbeat" for e in events)

    def test_heartbeat_emits_at_1hz_in_run_loop(self, fake_redis):
        """Run the simulator loop ~2.5 s and expect 2-3 heartbeats per drone."""
        import threading

        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))
        sub = _subscribe(fake_redis, MESH_LINK_STATUS)

        runner = threading.Thread(
            target=sim.run_forever,
            kwargs={"adjacency_hz": 1.0},
            daemon=True,
        )
        runner.start()
        try:
            time.sleep(2.5)
        finally:
            # The run_forever loop blocks on pubsub.listen(); raise KeyboardInterrupt
            # equivalent by closing the redis connection isn't trivial with fakeredis.
            # Instead, drain heartbeats and let the daemon thread die when the test ends.
            pass

        events = [
            e for e in _drain_link_status(sub)
            if e["reason"] == "heartbeat" and e["drone_id"] == "drone1"
        ]
        assert 2 <= len(events) <= 4, (
            f"expected 2-4 heartbeats in 2.5s, got {len(events)}: {events!r}"
        )


class TestSchemaValidation:
    def test_payload_validates_against_schema(self, fake_redis):
        """Every emitted payload (geometric / scripted / heartbeat) validates."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))
        sub = _subscribe(fake_redis, MESH_LINK_STATUS)

        # Trigger one of each kind.
        sim.ingest_state(_state_msg("drone1", *NORTH_1KM))   # geometric down
        sim.apply_scripted_event({                            # scripted (no-op flip)
            "t": 130,
            "type": "egs_link_drop",
            "drone_id": "drone1",
            "wall_clock_iso_ms": "2026-05-15T14:23:31.342Z",
        })
        sim.publish_link_heartbeats()                         # heartbeat

        events = _drain_link_status(sub)
        assert events  # we should have at least one
        for ev in events:
            validate_or_raise("mesh_link_status", ev)
