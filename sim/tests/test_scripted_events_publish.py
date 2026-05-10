"""Tests for waypoint_runner publishing on `sim.scripted_events`.

Wave 1 Lane C of the Beat 5 Path A-full plan
(docs/plans/2026-05-10-beat5-path-a-full.md §4 Component 6) makes the
scenario-defined scripted events more than observational — they're also
mirrored to the `sim.scripted_events` Redis channel so mesh sim (Wave 2
Lane D) and any future EGS replan consumer can react to them.

These tests exercise the publish surface only. Cross-component behaviour
(mesh sim consuming egs_link_drop, EGS consuming drone_failure) is covered
by their respective lanes' tests.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from shared.contracts import validate
from shared.contracts.topics import SIM_SCRIPTED_EVENTS
from sim.scenario import ScriptedEvent, load_scenario
from sim.waypoint_runner import WaypointRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RESILIENCE_SCENARIO = REPO_ROOT / "sim" / "scenarios" / "resilience_v1.yaml"


def _subscribe(fake_redis, channel: str):
    """Subscribe to ``channel`` and drain the subscribe-confirmation frame."""
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(channel)
    pubsub.get_message(timeout=0.1)
    return pubsub


def _drain_events(pubsub) -> list[dict[str, Any]]:
    """Drain all available `message` frames on `pubsub` and return parsed payloads."""
    out: list[dict[str, Any]] = []
    while True:
        msg = pubsub.get_message(timeout=0.05)
        if msg is None:
            break
        if msg["type"] != "message":
            continue
        out.append(json.loads(msg["data"]))
    return out


@pytest.fixture
def resilience_scenario():
    return load_scenario(RESILIENCE_SCENARIO)


def test_egs_link_drop_event_published(resilience_scenario, fake_redis):
    """At t=120 the resilience_v1 scenario fires `egs_link_drop drone3`.
    Asserts the runner publishes that event on `sim.scripted_events`.
    """
    runner = WaypointRunner(resilience_scenario, fake_redis)
    ps = _subscribe(fake_redis, SIM_SCRIPTED_EVENTS)
    # Tick past t=120 so the egs_link_drop fires. We have to also pass through
    # earlier events (drone_failure at t=30, fire_spread at t=60) so a single
    # tick at t=120 will fire all three at once. Filter to the egs_link_drop.
    runner.tick(t_seconds=120.5)
    events = _drain_events(ps)
    drops = [e for e in events if e["type"] == "egs_link_drop"]
    assert len(drops) == 1, f"expected one egs_link_drop, got {drops}"
    drop = drops[0]
    assert drop["t"] == 120
    assert drop["drone_id"] == "drone3"
    assert drop["detail"] == "drone3_beyond_egs_range"
    assert "wall_clock_iso_ms" in drop


def test_event_payload_schema(resilience_scenario, fake_redis):
    """Every published event must validate against `scripted_event.json`."""
    runner = WaypointRunner(resilience_scenario, fake_redis)
    ps = _subscribe(fake_redis, SIM_SCRIPTED_EVENTS)
    runner.tick(t_seconds=240.5)  # past mission_complete; fires every event
    events = _drain_events(ps)
    assert events, "expected at least one event to fire by t=240.5"
    for ev in events:
        outcome = validate("scripted_event", ev)
        assert outcome.valid, f"schema-invalid scripted_event: {ev} errors={outcome.errors}"


def test_drone_failure_event_published_and_mutates_state(resilience_scenario, fake_redis):
    """resilience_v1 fires `drone_failure drone2` at t=30. Verify both the
    publish AND the kinematics-side state mutation happen — the publish
    must not regress the existing observable behaviour.
    """
    runner = WaypointRunner(resilience_scenario, fake_redis)
    ps = _subscribe(fake_redis, SIM_SCRIPTED_EVENTS)
    runner.tick(t_seconds=30.5)
    events = _drain_events(ps)
    failures = [e for e in events if e["type"] == "drone_failure"]
    assert len(failures) == 1
    f = failures[0]
    assert f["drone_id"] == "drone2"
    assert f["t"] == 30
    assert f["detail"] == "battery_depleted"
    # Kinematic side: drone2 is now flagged as failed.
    assert runner._drones["drone2"].failed is True


def test_event_published_only_once(resilience_scenario, fake_redis):
    """Events should de-dupe across ticks — fires once at t=30, then is silent
    for the rest of the run. Drives ticks across 30→60 and asserts only ONE
    drone_failure landed on the channel.
    """
    runner = WaypointRunner(resilience_scenario, fake_redis)
    ps = _subscribe(fake_redis, SIM_SCRIPTED_EVENTS)
    for t in (29.0, 30.5, 35.0, 40.0, 50.0, 60.5):
        runner.tick(t_seconds=t)
    events = _drain_events(ps)
    failures = [e for e in events if e["type"] == "drone_failure"]
    assert len(failures) == 1, (
        f"drone_failure should publish exactly once across ticks, got {failures}"
    )


def test_invalid_event_does_not_crash_sim(
    resilience_scenario, fake_redis, monkeypatch, capsys
):
    """REGRESSION/EDGE: malformed event must NOT crash the sim. Monkeypatch
    `_fire` to inject a bogus event (negative `t`) — schema validation
    fails, the runner logs an error, and continues running cleanly.
    """
    runner = WaypointRunner(resilience_scenario, fake_redis)
    bogus = ScriptedEvent.model_construct(
        t=-1, type="drone_failure", drone_id="drone1", detail=None
    )
    # Inject the bogus event before any genuine fire — _apply_scripted_events
    # iterates the scenario list, so we shortcut and call _fire directly.
    runner._fire(bogus)
    captured = capsys.readouterr()
    assert "scripted_event validation failed" in captured.out, (
        f"expected validation-failure log, got out={captured.out!r}"
    )
    # Sim should still be capable of advancing — call tick without exception.
    runner.tick(t_seconds=0.0)
