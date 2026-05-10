"""Tests for the findings gate in MeshSimulator (Wave 2 Lane D).

Validates that ``forward_finding`` (a) republishes verbatim onto `.delivered`
when the drone is within ``egs_link_range_m`` of the EGS AND not in the
scripted-override set, and (b) drops in every other case (out of range,
overridden, or no position cached).
"""
from __future__ import annotations

import json
from typing import List

from agents.mesh_simulator.main import MeshSimulator
from shared.contracts.topics import per_drone_findings_delivered_channel


# Geographic fixtures: 1° lat ≈ 111 km, so 0.000898° ≈ 100 m, 0.00898° ≈ 1 km.
ORIGIN = (34.0, -118.5)
NORTH_100M = (34.000898, -118.5)   # ~100 m from EGS — inside 500 m link
NORTH_1KM = (34.00898, -118.5)     # ~1 km from EGS — outside 500 m link


def _subscribe(fake_redis, channel: str):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(channel)
    pubsub.get_message(timeout=0.1)
    return pubsub


def _drain_messages(pubsub) -> List[bytes]:
    out: List[bytes] = []
    while True:
        msg = pubsub.get_message(timeout=0.05)
        if msg is None:
            break
        if msg["type"] == "message":
            out.append(msg["data"])
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


def _finding_payload(drone_id: str, finding_id: str) -> dict:
    return {
        "finding_id": finding_id,
        "source_drone_id": drone_id,
        "type": "victim",
        "gps_lat": 34.0,
        "gps_lon": -118.0,
        "timestamp": "2026-05-15T14:23:11.342Z",
    }


class TestFindingsGate:
    def test_in_range_finding_forwarded(self, fake_redis):
        """drone1 100 m from EGS, range 500 m → finding flows verbatim."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))
        sub = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone1"),
        )

        raw = json.dumps(_finding_payload("drone1", "f_drone1_1")).encode()
        sim.forward_finding("drone1", raw)

        msgs = _drain_messages(sub)
        assert msgs == [raw]

    def test_out_of_range_finding_dropped(self, fake_redis):
        """drone1 1 km from EGS, range 500 m → no message on .delivered."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_1KM))
        sub = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone1"),
        )

        raw = json.dumps(_finding_payload("drone1", "f_drone1_1")).encode()
        sim.forward_finding("drone1", raw)

        assert _drain_messages(sub) == []

    def test_scripted_link_drop_overrides_in_range_geometry(self, fake_redis):
        """drone1 in range BUT egs_link_drop fired → finding dropped."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))
        sub = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone1"),
        )

        sim.apply_scripted_event({
            "t": 120,
            "type": "egs_link_drop",
            "drone_id": "drone1",
            "wall_clock_iso_ms": "2026-05-15T14:23:11.342Z",
        })
        raw = json.dumps(_finding_payload("drone1", "f_drone1_1")).encode()
        sim.forward_finding("drone1", raw)

        assert _drain_messages(sub) == []

    def test_link_restore_clears_override(self, fake_redis):
        """After egs_link_restore, finding flows again."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))
        sub = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone1"),
        )

        sim.apply_scripted_event({
            "t": 120,
            "type": "egs_link_drop",
            "drone_id": "drone1",
            "wall_clock_iso_ms": "2026-05-15T14:23:11.342Z",
        })
        sim.apply_scripted_event({
            "t": 180,
            "type": "egs_link_restore",
            "drone_id": "drone1",
            "wall_clock_iso_ms": "2026-05-15T14:24:11.342Z",
        })
        raw = json.dumps(_finding_payload("drone1", "f_drone1_2")).encode()
        sim.forward_finding("drone1", raw)

        assert _drain_messages(sub) == [raw]

    def test_position_cache_required(self, fake_redis):
        """A drone with no recorded position cannot be gated → drop."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        # Note: no ingest_state for drone1
        sub = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone1"),
        )

        raw = json.dumps(_finding_payload("drone1", "f_drone1_1")).encode()
        sim.forward_finding("drone1", raw)

        assert _drain_messages(sub) == []

    def test_egs_position_required(self, fake_redis):
        """Without an EGS position we can't compute distance → drop."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.ingest_state(_state_msg("drone1", *NORTH_100M))
        sub = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone1"),
        )

        raw = json.dumps(_finding_payload("drone1", "f_drone1_1")).encode()
        sim.forward_finding("drone1", raw)

        assert _drain_messages(sub) == []
