"""Tests for sim/waypoint_runner.py.

Drives the runner with a frozen clock so cadence assertions don't depend on
wall-time. Validates every published message against drone_state.json, the
schema locked in shared/schemas/.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from shared.contracts import validate
from shared.contracts.topics import per_drone_state_channel
from sim.scenario import load_scenario
from sim.waypoint_runner import WaypointRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def smoke_scenario():
    return load_scenario(REPO_ROOT / "sim" / "scenarios" / "single_drone_smoke.yaml")


@pytest.fixture
def two_drone_scenario(tmp_path: Path):
    """A minimal 2-drone scenario for the cross-talk test."""
    spec = {
        "scenario_id": "two_drone",
        "origin": {"lat": 34.0, "lon": -118.5},
        "area_m": 200,
        "drones": [
            {
                "drone_id": "drone1",
                "home": {"lat": 34.0001, "lon": -118.5001, "alt": 0},
                "waypoints": [{"id": "sp_001", "lat": 34.0010, "lon": -118.5001, "alt": 25}],
                "speed_mps": 5,
            },
            {
                "drone_id": "drone2",
                "home": {"lat": 34.0001, "lon": -118.4990, "alt": 0},
                "waypoints": [{"id": "sp_010", "lat": 34.0010, "lon": -118.4990, "alt": 25}],
                "speed_mps": 5,
            },
        ],
        "frame_mappings": {},
        "scripted_events": [],
    }
    p = tmp_path / "two_drone.yaml"
    p.write_text(yaml.safe_dump(spec))
    return load_scenario(p)


def _subscribe(fake_redis, channel: str):
    """Subscribe to ``channel`` and drain the subscribe-confirmation frame.

    Subscription must happen *before* the publisher emits, otherwise Redis
    pub/sub drops the message — there is no buffering for non-subscribed
    channels.
    """
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
        if msg["type"] != "message":
            continue
        out.append(json.loads(msg["data"]))
    return out


class TestWaypointRunnerBasics:
    def test_publishes_on_per_drone_state_channel(self, smoke_scenario, fake_redis):
        runner = WaypointRunner(smoke_scenario, fake_redis)
        pubsub = fake_redis.pubsub()
        pubsub.subscribe(per_drone_state_channel("drone1"))
        pubsub.get_message(timeout=0.1)  # subscribe ack
        runner.tick(t_seconds=0.0)
        msg = pubsub.get_message(timeout=0.1)
        assert msg is not None
        assert msg["type"] == "message"
        payload = json.loads(msg["data"])
        assert payload["drone_id"] == "drone1"

    def test_payload_validates_against_drone_state_schema(self, smoke_scenario, fake_redis):
        runner = WaypointRunner(smoke_scenario, fake_redis)
        ps = _subscribe(fake_redis, per_drone_state_channel("drone1"))
        for t in (0.0, 0.5, 1.0):
            runner.tick(t_seconds=t)
        msgs = _drain(ps, count=3)
        assert len(msgs) == 3
        for m in msgs:
            outcome = validate("drone_state", m)
            assert outcome.valid, f"schema-invalid msg: {outcome.errors}"

    def test_position_at_t0_equals_home(self, smoke_scenario, fake_redis):
        runner = WaypointRunner(smoke_scenario, fake_redis)
        ps = _subscribe(fake_redis, per_drone_state_channel("drone1"))
        runner.tick(t_seconds=0.0)
        msgs = _drain(ps, count=1)
        assert msgs, "no message published"
        # smoke scenario home: 34.0001, -118.5001, alt 0
        # but drone immediately heads toward first waypoint, so at t=0 it sits at home
        assert msgs[0]["position"]["lat"] == pytest.approx(34.0001, abs=1e-6)
        assert msgs[0]["position"]["lon"] == pytest.approx(-118.5001, abs=1e-6)

    def test_position_advances_toward_first_waypoint(self, smoke_scenario, fake_redis):
        runner = WaypointRunner(smoke_scenario, fake_redis)
        ps = _subscribe(fake_redis, per_drone_state_channel("drone1"))
        # The first waypoint is ~11m north-west of home. At 5 m/s, the drone
        # needs ~2.2s to reach it. After 1.0s, expect to be partway there.
        runner.tick(t_seconds=0.0)
        runner.tick(t_seconds=1.0)
        msgs = _drain(ps, count=2)
        assert len(msgs) == 2
        lat0, lat1 = msgs[0]["position"]["lat"], msgs[1]["position"]["lat"]
        assert lat1 > lat0, "drone should be moving north toward first waypoint"

    def test_holds_position_after_final_waypoint(self, smoke_scenario, fake_redis):
        runner = WaypointRunner(smoke_scenario, fake_redis)
        ps = _subscribe(fake_redis, per_drone_state_channel("drone1"))
        # 600s is well past the time needed to traverse all waypoints.
        runner.tick(t_seconds=0.0)
        runner.tick(t_seconds=600.0)
        runner.tick(t_seconds=601.0)
        msgs = _drain(ps, count=3)
        assert len(msgs) == 3
        # Last two messages should be at the same (final waypoint) position.
        assert msgs[1]["position"]["lat"] == pytest.approx(msgs[2]["position"]["lat"], abs=1e-7)
        assert msgs[1]["position"]["lon"] == pytest.approx(msgs[2]["position"]["lon"], abs=1e-7)
        assert msgs[2]["agent_status"] == "active"

    def test_battery_decreases_monotonically(self, smoke_scenario, fake_redis):
        runner = WaypointRunner(smoke_scenario, fake_redis, battery_drain_pct_per_sec=0.5)
        ps = _subscribe(fake_redis, per_drone_state_channel("drone1"))
        for t in (0.0, 1.0, 2.0, 5.0, 10.0):
            runner.tick(t_seconds=t)
        msgs = _drain(ps, count=5)
        assert len(msgs) == 5
        batteries = [m["battery_pct"] for m in msgs]
        assert batteries == sorted(batteries, reverse=True)
        # 10s @ 0.5%/s drains 5 from a starting 100 → expect ≤ 95
        assert batteries[-1] <= 95


class TestWaypointRunnerScriptedEvents:
    def test_drone_failure_event_flips_agent_status(self, tmp_path: Path, fake_redis):
        spec = {
            "scenario_id": "fail_test",
            "origin": {"lat": 34.0, "lon": -118.5},
            "area_m": 200,
            "drones": [
                {
                    "drone_id": "drone1",
                    "home": {"lat": 34.0, "lon": -118.5, "alt": 0},
                    "waypoints": [{"id": "sp_001", "lat": 34.001, "lon": -118.5, "alt": 25}],
                    "speed_mps": 5,
                }
            ],
            "frame_mappings": {},
            "scripted_events": [
                {"t": 5, "type": "drone_failure", "drone_id": "drone1", "detail": "battery_depleted"},
            ],
        }
        p = tmp_path / "s.yaml"
        p.write_text(yaml.safe_dump(spec))
        scenario = load_scenario(p)
        runner = WaypointRunner(scenario, fake_redis)
        ps = _subscribe(fake_redis, per_drone_state_channel("drone1"))
        runner.tick(t_seconds=0.0)
        runner.tick(t_seconds=4.5)
        runner.tick(t_seconds=5.5)
        msgs = _drain(ps, count=3)
        assert len(msgs) == 3
        assert msgs[0]["agent_status"] == "active"
        assert msgs[1]["agent_status"] == "active"
        assert msgs[2]["agent_status"] == "offline"


class TestWaypointRunnerMultiDrone:
    def test_each_drone_publishes_on_own_channel(self, two_drone_scenario, fake_redis):
        runner = WaypointRunner(two_drone_scenario, fake_redis)
        ps1 = _subscribe(fake_redis, per_drone_state_channel("drone1"))
        ps2 = _subscribe(fake_redis, per_drone_state_channel("drone2"))
        runner.tick(t_seconds=0.0)
        m1 = _drain(ps1, count=1)
        m2 = _drain(ps2, count=1)
        assert len(m1) == 1 and m1[0]["drone_id"] == "drone1"
        assert len(m2) == 1 and m2[0]["drone_id"] == "drone2"

    def test_no_cross_drone_message_leakage(self, two_drone_scenario, fake_redis):
        """drone1's channel must never carry drone2 payloads."""
        runner = WaypointRunner(two_drone_scenario, fake_redis)
        ps = _subscribe(fake_redis, per_drone_state_channel("drone1"))
        for t in (0.0, 0.5, 1.0):
            runner.tick(t_seconds=t)
        msgs = _drain(ps, count=3)
        assert len(msgs) == 3
        for m in msgs:
            assert m["drone_id"] == "drone1"


class TestWaypointRunnerSchemaDefaults:
    """Sim publishes safe defaults for agent-state fields the drone agent will overwrite."""

    def test_default_agent_state_fields(self, smoke_scenario, fake_redis):
        runner = WaypointRunner(smoke_scenario, fake_redis)
        ps = _subscribe(fake_redis, per_drone_state_channel("drone1"))
        runner.tick(t_seconds=0.0)
        msgs = _drain(ps, count=1)
        m = msgs[0]
        assert m["current_task"] is None
        assert m["last_action"] == "none"
        assert m["last_action_timestamp"] is None
        assert m["validation_failures_total"] == 0
        assert m["findings_count"] == 0
        assert m["in_mesh_range_of"] == []
