"""PR1 wire test: mesh sim republishes findings verbatim onto `.delivered`.

PR1 is a pure refactor. The mesh simulator psubs `drones.*.findings`, and on
each message republishes the raw payload bytes onto
`drones.<id>.findings.delivered`. PR2 adds the actual range / scripted-event
gate; in PR1 every input must produce exactly one output, byte-identical.
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
