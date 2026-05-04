"""Full-loop sim+mesh smoke test.

Runs against fakeredis. Exercises the path:

    waypoint_runner.tick → drones.<id>.state
    frame_server.tick    → drones.<id>.camera (JPEG)
    MeshSimulator.ingest_state → position cache
    MeshSimulator.forward_broadcast → swarm.<rid>.visible_to.<rid>

This is the regression net Hazim leans on at Day 7 Gate 2. Marked ``e2e``
so quick runs (``pytest -m "not e2e"``) skip it; CI runs the full suite.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.mesh_simulator.main import MeshSimulator
from shared.contracts.topics import (
    per_drone_camera_channel,
    per_drone_state_channel,
    swarm_broadcast_channel,
    swarm_visible_to_channel,
)
from sim.frame_server import FrameServer
from sim.scenario import load_scenario
from sim.waypoint_runner import WaypointRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRAMES_DIR = REPO_ROOT / "sim" / "fixtures" / "frames"


pytestmark = pytest.mark.e2e


def _subscribe(fake_redis, channel: str):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(channel)
    pubsub.get_message(timeout=0.1)
    return pubsub


def _drain(pubsub, *, count: int):
    out = []
    while len(out) < count:
        msg = pubsub.get_message(timeout=0.1)
        if msg is None:
            break
        if msg["type"] == "message":
            out.append(msg["data"])
    return out


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
            "confidence": 0.85,
            "visual_description": "Person prone, partially covered by debris.",
        },
    }


def test_full_loop_disaster_zone_v1(fake_redis):
    """Sim publishes state + frames; mesh ingests state and forwards a broadcast."""
    scenario = load_scenario(REPO_ROOT / "sim" / "scenarios" / "disaster_zone_v1.yaml")
    runner = WaypointRunner(scenario, fake_redis)
    frames = FrameServer(scenario, fake_redis, frames_dir=FRAMES_DIR)
    mesh = MeshSimulator(fake_redis, range_m=1500.0, egs_link_range_m=2000.0)
    # set EGS position at the scenario origin
    mesh.set_egs_position(scenario.origin.lat, scenario.origin.lon)

    state_d1 = _subscribe(fake_redis, per_drone_state_channel("drone1"))
    state_d2 = _subscribe(fake_redis, per_drone_state_channel("drone2"))
    cam_d1 = _subscribe(fake_redis, per_drone_camera_channel("drone1"))
    visible_d2 = _subscribe(fake_redis, swarm_visible_to_channel("drone2"))

    # 1) sim publishes drone state for all drones at t=0; manually feed mesh.
    runner.tick(t_seconds=0.0)
    s1 = _drain(state_d1, count=1)
    s2 = _drain(state_d2, count=1)
    assert s1 and s2
    mesh.ingest_state(json.loads(s1[0]))
    mesh.ingest_state(json.loads(s2[0]))

    # 2) frame server publishes drone1 camera at tick 0.
    frames.tick(tick_index=0)
    f1 = _drain(cam_d1, count=1)
    assert f1
    assert f1[0][:2] == b"\xff\xd8"  # JPEG magic

    # 3) drone1 broadcasts a finding; mesh forwards to drone2 (≈1.1km away
    #    in disaster_zone_v1 — within our enlarged 1.5km test range).
    bcast = _broadcast("drone1", scenario.drones[0].home.lat, scenario.drones[0].home.lon)
    forwarded = mesh.forward_broadcast("drone1", json.dumps(bcast).encode())
    assert forwarded >= 1, f"mesh did not forward to anyone (forwarded={forwarded})"
    received = _drain(visible_d2, count=1)
    assert len(received) == 1
    decoded = json.loads(received[0])
    assert decoded["sender_id"] == "drone1"
    assert decoded["broadcast_type"] == "finding"
