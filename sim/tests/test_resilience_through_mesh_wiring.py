"""Resilience scenario validated through the actual MeshSimulator wiring.

The geometry-only checks in ``test_resilience_scenario.py`` call
``in_range_pairs()`` against positions read straight from the scenario or
from ``WaypointRunner._drones`` — pure math, no Redis. This file closes the
last unverified hop: every drone state goes through

    WaypointRunner.tick(t)
        → fakeredis.publish("drones.<id>.state", json)
        → fakeredis.subscribe pulls the message back
        → MeshSimulator.ingest_state(payload)
        → MeshSimulator.adjacency_snapshot()

so a future change that breaks the publish→subscribe→ingest plumbing (a
channel rename, schema field rename, ingest_state silently dropping
malformed payloads) trips here even when the unit-level adjacency math
still passes. Production-equivalent thresholds: ``range_m=200`` and
``egs_link_range_m=500`` from ``shared/config.yaml``.

Marked ``e2e`` to match the convention of ``test_smoke_full_loop.py`` —
``pytest -m "not e2e"`` skips it for fast iteration; the sim_mesh CI job
runs without that filter so it lands on every push.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.mesh_simulator.main import MeshSimulator
from agents.mesh_simulator.range_filter import EGS_NODE_ID
from shared.contracts.topics import per_drone_state_channel
from sim.scenario import load_scenario
from sim.waypoint_runner import WaypointRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIO_PATH = REPO_ROOT / "sim" / "scenarios" / "resilience_v1.yaml"

# Production thresholds. The resilience scenario was authored against these
# specific numbers — drift either here or in shared/config.yaml will
# desynchronise tests from the real swarm. See the slice-A note in
# sim/ROADMAP.md "Done (shipped on feature/sim-resilience-and-pilot)".
MESH_RANGE_M = 200
EGS_LINK_RANGE_M = 500


pytestmark = pytest.mark.e2e


def _subscribe(fake_redis, channel: str):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(channel)
    pubsub.get_message(timeout=0.1)  # drop subscribe ack
    return pubsub


def _drain(pubsub):
    """Drain every pending message on a pubsub channel."""
    out = []
    while True:
        msg = pubsub.get_message(timeout=0.1)
        if msg is None:
            break
        if msg["type"] == "message":
            out.append(msg["data"])
    return out


@pytest.fixture
def harness(fake_redis):
    """Wire WaypointRunner + MeshSimulator + per-drone state subscribers
    against a single fakeredis instance. Returns ``(runner, mesh, ps_by_drone)``.
    """
    scenario = load_scenario(SCENARIO_PATH)
    runner = WaypointRunner(scenario, fake_redis)
    mesh = MeshSimulator(
        fake_redis,
        range_m=MESH_RANGE_M,
        egs_link_range_m=EGS_LINK_RANGE_M,
    )
    # EGS sits at scenario origin so adjacency snapshots include the egs
    # node and the drone1/drone3 EGS-link drop is observable.
    mesh.set_egs_position(scenario.origin.lat, scenario.origin.lon)
    ps_by_drone = {
        d.drone_id: _subscribe(fake_redis, per_drone_state_channel(d.drone_id))
        for d in scenario.drones
    }
    return runner, mesh, ps_by_drone


def _tick_and_ingest(runner: WaypointRunner, mesh: MeshSimulator, ps_by_drone, *, t_seconds: float) -> dict:
    """Advance the sim, drain every drone's state channel, feed the mesh,
    return the resulting adjacency snapshot."""
    runner.tick(t_seconds=t_seconds)
    for ps in ps_by_drone.values():
        for raw in _drain(ps):
            mesh.ingest_state(json.loads(raw))
    return mesh.adjacency_snapshot()


class TestResilienceThroughMeshWiring:
    def test_t0_full_mesh_observed_via_publish_subscribe(self, harness):
        """At t=0 every drone is within 25m of every other and within 12m
        of the EGS — full adjacency must come through the wiring."""
        runner, mesh, ps_by_drone = harness
        adj = _tick_and_ingest(runner, mesh, ps_by_drone, t_seconds=0.0)

        drone_ids = sorted(ps_by_drone.keys())
        for d in drone_ids:
            others = sorted(set(drone_ids) - {d})
            # Every drone neighbours every other drone + the egs node.
            assert sorted(set(adj[d]) - {EGS_NODE_ID}) == others, (
                f"{d} should see {others} at t=0; got {adj[d]}"
            )
            assert EGS_NODE_ID in adj[d], (
                f"{d} should reach EGS at t=0 (within 500m); got {adj[d]}"
            )
        assert sorted(adj[EGS_NODE_ID]) == drone_ids

    def test_drone1_drone3_dropped_past_t20_via_publish_subscribe(self, harness):
        """The headline geometry assertion through the publish→ingest path:
        drone1 and drone3 fan apart at 5 m/s in opposite directions, so by
        t=20s their separation (~222m) exceeds the 200m mesh threshold and
        the adjacency snapshot drops them from each other's neighbour list.
        """
        runner, mesh, ps_by_drone = harness
        adj = _tick_and_ingest(runner, mesh, ps_by_drone, t_seconds=20.0)

        assert "drone3" not in adj["drone1"], (
            f"drone1 should have lost drone3 by t=20s through the publish→"
            f"subscribe→ingest path; adj[drone1]={adj['drone1']}"
        )
        assert "drone1" not in adj["drone3"], (
            f"drone3 should have lost drone1 by t=20s; adj[drone3]={adj['drone3']}"
        )
        # drone2 is still mid-flight east of origin (not yet at the t=30
        # scripted-failure event), separation from drone1/drone3 is below
        # the 200m diagonal — should still be a neighbour to both.
        assert "drone2" in adj["drone1"]
        assert "drone2" in adj["drone3"]

    def test_drone1_drone3_lose_egs_link_past_t100_via_publish_subscribe(self, harness):
        """drone1 and drone3 each travel 5 m/s straight away from origin
        and cross the 500m EGS-link radius at t≈98s. Past t=100 the
        adjacency snapshot must drop both drone↔EGS edges; drone2 (which
        froze at ~150m E of origin under the t=30 drone_failure event)
        stays linked.
        """
        runner, mesh, ps_by_drone = harness
        # Walk forward through the t=30 scripted_event tick so drone2
        # actually freezes en route rather than at home — gives drone2
        # a realistic position for the EGS-link assertion below.
        for t in (15.0, 30.0, 60.0, 100.0):
            adj = _tick_and_ingest(runner, mesh, ps_by_drone, t_seconds=t)

        # drone1 and drone3 past the 500m radius — egs edge dropped.
        assert EGS_NODE_ID not in adj["drone1"], (
            f"drone1 should have lost EGS link by t=100s; adj[drone1]={adj['drone1']}"
        )
        assert EGS_NODE_ID not in adj["drone3"], (
            f"drone3 should have lost EGS link by t=100s; adj[drone3]={adj['drone3']}"
        )
        # drone2 frozen at ~150m E of origin → still inside 500m EGS link.
        assert EGS_NODE_ID in adj["drone2"], (
            f"drone2 (frozen by drone_failure at t=30) should still see EGS; "
            f"adj[drone2]={adj['drone2']}"
        )
        # And from EGS's vantage: only drone2 remains.
        assert sorted(adj[EGS_NODE_ID]) == ["drone2"]

    def test_published_state_is_schema_shaped_enough_for_ingest(self, harness):
        """ingest_state silently drops malformed payloads (KeyError /
        TypeError → return). If WaypointRunner ever publishes without
        ``drone_id`` / ``position.lat`` / ``position.lon``, the mesh
        position cache stays empty and adjacency goes silent. Pin the
        contract surface ingest_state actually depends on.
        """
        runner, mesh, ps_by_drone = harness
        runner.tick(t_seconds=0.0)
        for drone_id, ps in ps_by_drone.items():
            raw_msgs = _drain(ps)
            assert raw_msgs, f"no state published for {drone_id}"
            payload = json.loads(raw_msgs[0])
            assert payload["drone_id"] == drone_id
            assert "lat" in payload["position"] and "lon" in payload["position"]
            # Feed it; mesh must accept and cache the position.
            mesh.ingest_state(payload)
            cached = mesh.known_positions().get(drone_id)
            assert cached is not None, f"mesh dropped a valid {drone_id} payload"
