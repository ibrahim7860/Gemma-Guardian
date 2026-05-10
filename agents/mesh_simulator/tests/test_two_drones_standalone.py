"""Multi-drone isolation tests for mesh sim's findings gate + link_status.

Closes the test gap from /plan-eng-review: when multiple drones are forced
into standalone via scripted overrides, each drone's gate state is tracked
independently and emissions / drops do not leak across drone IDs.
"""
from __future__ import annotations

import json
from typing import List

from agents.mesh_simulator.main import MeshSimulator
from shared.contracts.topics import (
    MESH_LINK_STATUS,
    per_drone_findings_delivered_channel,
)


ORIGIN = (34.0, -118.5)
NORTH_100M = (34.000898, -118.5)


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


def _drain_link_status(pubsub) -> List[dict]:
    out = []
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


def _finding_payload(drone_id: str, finding_id: str) -> dict:
    return {
        "finding_id": finding_id,
        "source_drone_id": drone_id,
        "type": "victim",
        "gps_lat": 34.0,
        "gps_lon": -118.0,
        "timestamp": "2026-05-15T14:23:11.342Z",
    }


class TestTwoDronesStandalone:
    def test_two_drones_concurrent_overrides_isolated(self, fake_redis):
        """drone1 + drone3 overridden down → drone2 unaffected, events fire only for the two."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        for did in ("drone1", "drone2", "drone3"):
            sim.ingest_state(_state_msg(did, *NORTH_100M))

        link_sub = _subscribe(fake_redis, MESH_LINK_STATUS)
        sub1 = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone1"),
        )
        sub2 = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone2"),
        )
        sub3 = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone3"),
        )

        sim.apply_scripted_event({
            "t": 120,
            "type": "egs_link_drop",
            "drone_id": "drone1",
            "wall_clock_iso_ms": "2026-05-15T14:23:11.342Z",
        })
        sim.apply_scripted_event({
            "t": 121,
            "type": "egs_link_drop",
            "drone_id": "drone3",
            "wall_clock_iso_ms": "2026-05-15T14:23:12.342Z",
        })

        # Both overrides set
        assert sim._link_down_overrides == {"drone1", "drone3"}

        # drone2 finding should still flow; drone1 + drone3 dropped.
        raw1 = json.dumps(_finding_payload("drone1", "f_drone1_1")).encode()
        raw2 = json.dumps(_finding_payload("drone2", "f_drone2_1")).encode()
        raw3 = json.dumps(_finding_payload("drone3", "f_drone3_1")).encode()
        sim.forward_finding("drone1", raw1)
        sim.forward_finding("drone2", raw2)
        sim.forward_finding("drone3", raw3)

        assert _drain_messages(sub1) == []
        assert _drain_messages(sub2) == [raw2]
        assert _drain_messages(sub3) == []

        # link_status events fired for drone1 and drone3 only.
        events = _drain_link_status(link_sub)
        ids = sorted(e["drone_id"] for e in events)
        assert ids == ["drone1", "drone3"]
        assert all(e["link"] == "down" and e["reason"] == "scripted" for e in events)

    def test_partial_restore(self, fake_redis):
        """drone1 restored, drone3 still down → drone1 flows, drone3 dropped."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        sim.set_egs_position(*ORIGIN)
        for did in ("drone1", "drone3"):
            sim.ingest_state(_state_msg(did, *NORTH_100M))

        sim.apply_scripted_event({
            "t": 120, "type": "egs_link_drop", "drone_id": "drone1",
            "wall_clock_iso_ms": "2026-05-15T14:23:11.342Z",
        })
        sim.apply_scripted_event({
            "t": 121, "type": "egs_link_drop", "drone_id": "drone3",
            "wall_clock_iso_ms": "2026-05-15T14:23:12.342Z",
        })

        sub1 = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone1"),
        )
        sub3 = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone3"),
        )

        sim.apply_scripted_event({
            "t": 180, "type": "egs_link_restore", "drone_id": "drone1",
            "wall_clock_iso_ms": "2026-05-15T14:24:11.342Z",
        })

        raw1 = json.dumps(_finding_payload("drone1", "f_drone1_2")).encode()
        raw3 = json.dumps(_finding_payload("drone3", "f_drone3_2")).encode()
        sim.forward_finding("drone1", raw1)
        sim.forward_finding("drone3", raw3)

        assert _drain_messages(sub1) == [raw1]
        assert _drain_messages(sub3) == []
        assert sim._link_down_overrides == {"drone3"}
