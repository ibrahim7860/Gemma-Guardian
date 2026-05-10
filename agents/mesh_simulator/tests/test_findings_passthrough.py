"""Wire test: mesh sim republishes findings verbatim onto `.delivered`.

Originally a pure-passthrough test (PR1). Wave 2 Lane D added a real gate
(haversine vs egs_link_range + scripted-override set), so these tests now
seed an EGS position + an in-range drone position before asserting the
forwarding behavior. The byte-identical passthrough invariant is still
enforced — the gate either drops or republishes unchanged.
"""
from __future__ import annotations

import json
from typing import List

from agents.mesh_simulator.main import MeshSimulator
from shared.contracts.topics import (
    per_drone_findings_channel,
    per_drone_findings_delivered_channel,
)


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


_ORIGIN = (34.0, -118.5)
_NORTH_100M = (34.000898, -118.5)  # ~100 m from origin; well inside 500 m EGS link


def _state_payload(drone_id: str, lat: float, lon: float) -> dict:
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


def _seed_in_range(sim, drone_ids):
    """Place EGS at origin, every drone 100 m north — all inside 500 m EGS link."""
    sim.set_egs_position(*_ORIGIN)
    for did in drone_ids:
        sim.ingest_state(_state_payload(did, *_NORTH_100M))


def _finding_payload(drone_id: str, finding_id: str) -> dict:
    """Minimal Contract-4-shaped finding (only the fields the passthrough
    cares about, which is none — the payload is opaque bytes to the sim)."""
    return {
        "finding_id": finding_id,
        "source_drone_id": drone_id,
        "type": "victim",
        "gps_lat": 34.0,
        "gps_lon": -118.0,
        "timestamp": "2026-05-15T14:23:11.342Z",
    }


class TestForwardFinding:
    def test_forward_finding_publishes_on_delivered_channel(self, fake_redis):
        """Calling forward_finding republishes verbatim on `.delivered`."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        _seed_in_range(sim, ["drone1"])
        sub = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone1"),
        )

        payload = _finding_payload("drone1", "f_drone1_1")
        raw = json.dumps(payload).encode()
        sim.forward_finding("drone1", raw)

        msgs = _drain_messages(sub)
        assert len(msgs) == 1
        # Byte-identical passthrough — the mesh sim does not reserialize.
        assert msgs[0] == raw

    def test_forward_finding_does_not_touch_raw_findings_channel(self, fake_redis):
        """The mesh sim must NOT echo back to the input channel."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        _seed_in_range(sim, ["drone1"])
        # Subscribe to the raw findings channel — anyone listening should see
        # nothing produced by the sim itself (the drone is the only producer).
        sub = _subscribe(fake_redis, per_drone_findings_channel("drone1"))

        sim.forward_finding(
            "drone1", json.dumps(_finding_payload("drone1", "f_drone1_1")).encode(),
        )

        msgs = _drain_messages(sub)
        assert msgs == [], (
            f"mesh sim should not republish onto the raw .findings channel, "
            f"got {msgs!r}"
        )

    def test_forward_finding_isolates_per_drone(self, fake_redis):
        """Each drone's `.delivered` channel only carries that drone's bytes."""
        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        _seed_in_range(sim, ["drone1", "drone2"])
        sub1 = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone1"),
        )
        sub2 = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone2"),
        )

        raw1 = json.dumps(_finding_payload("drone1", "f_drone1_1")).encode()
        raw2 = json.dumps(_finding_payload("drone2", "f_drone2_1")).encode()
        sim.forward_finding("drone1", raw1)
        sim.forward_finding("drone2", raw2)

        msgs1 = _drain_messages(sub1)
        msgs2 = _drain_messages(sub2)
        assert msgs1 == [raw1]
        assert msgs2 == [raw2]


class TestPubSubRoundTrip:
    """Simulate the full psub flow: a drone publishes to the raw findings
    channel, mesh sim forwards from the dispatch loop, EGS-side subscribers
    see the message on `.delivered`. Drives the dispatch by hand (calling
    the same code path as run_forever's dispatch branch) so we don't depend
    on threading."""

    def test_dispatch_branch_routes_findings_to_delivered(self, fake_redis):
        from agents.mesh_simulator.main import drone_id_from_findings_channel

        sim = MeshSimulator(fake_redis, range_m=200.0, egs_link_range_m=500.0)
        _seed_in_range(sim, ["drone1"])
        sub = _subscribe(
            fake_redis, per_drone_findings_delivered_channel("drone1"),
        )

        # Mimic what run_forever does on a pmessage: extract drone_id then
        # forward verbatim.
        channel = per_drone_findings_channel("drone1")
        drone_id = drone_id_from_findings_channel(channel)
        assert drone_id == "drone1"
        raw = json.dumps(_finding_payload("drone1", "f_drone1_42")).encode()
        sim.forward_finding(drone_id, raw)

        msgs = _drain_messages(sub)
        assert msgs == [raw]
