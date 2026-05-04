"""Tests that the shipped scenario YAMLs and ground-truth JSON load cleanly.

These are the files Thayyil / Hazim hand-author and the demo runs against;
breaking them in a refactor would silently kill scenarios. Treat as canaries.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.scenario import load_groundtruth, load_scenario

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"
FRAMES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "frames"

SHIPPED_SCENARIOS = [
    "disaster_zone_v1.yaml",
    "single_drone_smoke.yaml",
    "resilience_v1.yaml",
]


@pytest.mark.parametrize("name", SHIPPED_SCENARIOS)
def test_shipped_scenario_loads(name: str):
    path = SCENARIOS_DIR / name
    assert path.exists(), f"scenario file missing: {path}"
    s = load_scenario(path)
    assert s.scenario_id  # non-empty
    assert s.drones, "scenario must define at least one drone"


def test_disaster_zone_v1_groundtruth_loads():
    path = SCENARIOS_DIR / "disaster_zone_v1_groundtruth.json"
    assert path.exists()
    gt = load_groundtruth(path)
    assert gt.scenario_id == "disaster_zone_v1"
    assert gt.victims, "demo scenario should declare at least one victim"
