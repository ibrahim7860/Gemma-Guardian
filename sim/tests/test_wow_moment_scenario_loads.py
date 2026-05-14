"""Lockdown tests for sim/scenarios/wow_moment_v1.yaml.

Plan reference: docs/plans/2026-05-12-gate4-wow-moment.md Phase 3 tests #1.

The wow-moment scenario is load-bearing for the Beat 3c capture: the
storyboard pins the count at 25 survey points across 3 drones, and the
eval harness in ml/evaluation/eval_wow_moment_trigger.py asserts the same
shape. These tests catch silent edits to the YAML (extra/missing points,
duplicate ids, geometry that fails the validator).
"""
from __future__ import annotations

from pathlib import Path

from sim.scenario import Scenario, load_scenario

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_WOW_PATH = _REPO_ROOT / "sim" / "scenarios" / "wow_moment_v1.yaml"


def test_scenario_loads_without_raising():
    """The YAML round-trips through sim/scenario.py's Pydantic loader.

    Implicitly covers: extra=forbid on every model, drone_id pattern,
    tick_range ordering, base_image_path/extents paired validator.
    """
    s = load_scenario(_WOW_PATH)
    assert isinstance(s, Scenario)
    assert s.scenario_id == "wow_moment_v1"


def test_exactly_25_survey_points_across_3_drones():
    """The storyboard pins the count at 25 points / 3 drones. Drift on
    either dimension breaks the wow-moment camera shot AND the
    ASSIGNMENT_TOTAL_MISMATCH literal ("27 points but 25") that lands
    in the corrective-prompt overlay.
    """
    s = load_scenario(_WOW_PATH)
    assert len(s.drones) == 3, f"expected 3 drones, got {len(s.drones)}"
    total_points = sum(len(d.waypoints) for d in s.drones)
    assert total_points == 25, f"expected exactly 25 survey points, got {total_points}"


def test_all_point_ids_unique():
    """sp_001..sp_025 sequential, no partitioning by drone (the LLM has
    to do the partition itself given a flat list of 25). Duplicate ids
    would short-circuit ASSIGNMENT_DUPLICATE_POINT and confuse the
    ASSIGNMENT_TOTAL_MISMATCH bait.
    """
    s = load_scenario(_WOW_PATH)
    ids = [wp.id for d in s.drones for wp in d.waypoints]
    assert len(ids) == len(set(ids)), (
        f"duplicate survey-point ids in wow_moment_v1: "
        f"{sorted([i for i in ids if ids.count(i) > 1])}"
    )
    # And the ids are the expected sp_001..sp_025 set.
    assert set(ids) == {f"sp_{i:03d}" for i in range(1, 26)}


def test_geometry_validators_pass():
    """area_m positive, origin in valid lat/lon range, base_image_extents
    bbox ordered, base_image_path + extents both set together. These are
    enforced by sim/scenario.py — the test is a regression guard against
    a future edit that breaks one and only loads-but-renders-wrong.
    """
    s = load_scenario(_WOW_PATH)
    assert s.area_m > 0
    assert -90 <= s.origin.lat <= 90
    assert -180 <= s.origin.lon <= 180
    # base_image fields must be paired (validator) AND extents ordered.
    assert s.base_image_path is not None
    assert s.base_image_extents is not None
    assert s.base_image_extents.lat_min < s.base_image_extents.lat_max
    assert s.base_image_extents.lon_min < s.base_image_extents.lon_max
