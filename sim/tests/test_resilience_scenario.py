"""Resilience scenario v1 — geometry and event-surface invariants.

The scenario is the substrate Qasim (EGS) and Kaleel (drone agent) lean
on for Phase D (mesh dropout live on the swarm) and Phase E (Gate 4 multi-
drone coordination). It must:

1. Load cleanly via the same Pydantic models as every other scenario.
2. Reuse only the frames already on disk (Thayyil's xBD swap stays
   orthogonal — filenames preserved, bytes change later).
3. Geometry: drones start in-mesh and fan apart so the mesh range filter
   actually drops the drone1↔drone3 pair before t=60s, and at least one
   drone exits the wider EGS link range during the run.
4. Exercise the full scripted-event surface ScriptedEventType supports.

These are correctness-of-authoring checks. Live-Redis behaviour is covered
indirectly by agents/mesh_simulator/tests/test_range_filter.py (pure logic)
and sim/tests/test_smoke_full_loop.py (the e2e harness).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.mesh_simulator.range_filter import EGS_NODE_ID, in_range_pairs
from sim.scenario import load_groundtruth, load_scenario
from sim.waypoint_runner import WaypointRunner

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIOS_DIR = REPO_ROOT / "sim" / "scenarios"
FRAMES_DIR = REPO_ROOT / "sim" / "fixtures" / "frames"

SCENARIO_PATH = SCENARIOS_DIR / "resilience_v1.yaml"
GROUNDTRUTH_PATH = SCENARIOS_DIR / "resilience_v1_groundtruth.json"

# Live-config thresholds the scenario is tuned against (shared/config.yaml).
MESH_RANGE_M = 200
EGS_LINK_RANGE_M = 500


@pytest.fixture(scope="module")
def scenario():
    return load_scenario(SCENARIO_PATH)


@pytest.fixture(scope="module")
def groundtruth():
    return load_groundtruth(GROUNDTRUTH_PATH)


def test_scenario_loads(scenario):
    assert scenario.scenario_id == "resilience_v1"
    assert {d.drone_id for d in scenario.drones} == {"drone1", "drone2", "drone3"}


def test_groundtruth_loads(groundtruth):
    assert groundtruth.scenario_id == "resilience_v1"
    # The resilience demo intentionally surfaces every finding type so the
    # drone agent's perception covers the full enum on one run.
    assert groundtruth.victims, "expected at least one victim"
    assert groundtruth.fires, "expected at least one fire"
    assert groundtruth.damaged_structures, "expected at least one damaged_structure"
    assert groundtruth.blocked_routes, "expected at least one blocked_route"


def test_every_referenced_frame_exists_on_disk(scenario):
    referenced: set[str] = set()
    for mappings in scenario.frame_mappings.values():
        for m in mappings:
            referenced.add(m.frame_file)
    missing = [name for name in sorted(referenced) if not (FRAMES_DIR / name).exists()]
    assert not missing, f"frames missing for resilience_v1: {missing}"


def test_only_existing_placeholder_frames_used(scenario):
    """Thayyil's xBD swap is orthogonal — this scenario must not introduce
    new fixture filenames. New imagery lands by replacing bytes at a kept
    name, not by adding files."""
    on_disk = {p.name for p in FRAMES_DIR.glob("*.jpg")}
    referenced: set[str] = set()
    for mappings in scenario.frame_mappings.values():
        for m in mappings:
            referenced.add(m.frame_file)
    assert referenced.issubset(on_disk), (
        f"resilience_v1 references frames not on disk: {sorted(referenced - on_disk)}"
    )


def test_scripted_events_exercise_full_resilience_surface(scenario):
    """drone_failure, egs_link_drop, egs_link_restore, fire_spread,
    mission_complete must all appear so EGS replan, mesh drop, and
    end-of-run paths get exercised in one run."""
    types = {e.type for e in scenario.scripted_events}
    required = {
        "drone_failure",
        "egs_link_drop",
        "egs_link_restore",
        "fire_spread",
        "mission_complete",
    }
    missing = required - types
    assert not missing, f"resilience_v1 missing scripted event types: {sorted(missing)}"


def test_drones_start_inside_mesh_range(scenario, fake_redis):
    """At t=0 every drone-pair must be inside CONFIG.mesh.range_meters; if
    they're not, the mesh dropout demo loses its before-and-after."""
    runner = WaypointRunner(scenario, fake_redis)
    runner.tick(t_seconds=0.0)
    positions = {d.drone_id: (d.home.lat, d.home.lon) for d in scenario.drones}
    adj = in_range_pairs(positions, range_m=MESH_RANGE_M)
    # Every drone should see every other drone as a neighbour at t=0.
    for d_id, neighbours in adj.items():
        others = sorted(set(positions) - {d_id})
        assert sorted(neighbours) == others, (
            f"{d_id} should see {others} at t=0, saw {sorted(neighbours)}"
        )


def _positions_after(runner: WaypointRunner, t_seconds: float) -> dict[str, tuple[float, float]]:
    """Tick the runner forward and snapshot lat/lon per drone."""
    runner.tick(t_seconds=t_seconds)
    return {ds.drone.drone_id: (ds.position[0], ds.position[1]) for ds in runner._drones.values()}


def test_drone1_drone3_drop_out_of_mesh_range_by_t60(scenario, fake_redis):
    """Phase D resilience-demo invariant: by ~t=60s drone1 and drone3 are
    >200m apart and the mesh adjacency snapshot stops listing them as
    neighbours. Tuning lever for Qasim's EGS replan rehearsal."""
    runner = WaypointRunner(scenario, fake_redis)
    positions = _positions_after(runner, t_seconds=60.0)
    adj = in_range_pairs(positions, range_m=MESH_RANGE_M)
    assert "drone3" not in adj["drone1"], (
        f"drone1 should have lost drone3 by t=60s; adj[drone1]={adj['drone1']}"
    )
    assert "drone1" not in adj["drone3"], (
        f"drone3 should have lost drone1 by t=60s; adj[drone3]={adj['drone3']}"
    )


def test_at_least_one_drone_exits_egs_link_range(scenario, fake_redis):
    """The wider 500m EGS link must drop too at some point, so the EGS
    standalone-mode rehearsal has a real link-loss trigger."""
    runner = WaypointRunner(scenario, fake_redis)
    positions = _positions_after(runner, t_seconds=180.0)
    positions_with_egs = {
        EGS_NODE_ID: (scenario.origin.lat, scenario.origin.lon),
        **positions,
    }
    adj = in_range_pairs(
        positions_with_egs,
        range_m=MESH_RANGE_M,
        egs_link_range_m=EGS_LINK_RANGE_M,
    )
    egs_neighbours = set(adj[EGS_NODE_ID])
    drone_ids = {d.drone_id for d in scenario.drones}
    out_of_range = drone_ids - egs_neighbours
    assert out_of_range, (
        "expected at least one drone to be out of EGS link range by t=180s; "
        f"adj[egs]={sorted(egs_neighbours)}"
    )
