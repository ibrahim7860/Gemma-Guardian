"""Asserts every `frame_file` referenced by a shipped scenario exists on disk.

If Person 5 swaps placeholder JPEGs for real xBD imagery, the file *names*
must stay the same — this test enforces that. If a scenario adds a new
frame_file reference, the corresponding file must land before merge.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.scenario import load_scenario

SCENARIOS_DIR = Path(__file__).resolve().parent.parent / "scenarios"
FRAMES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "frames"

SHIPPED_SCENARIOS = [
    "disaster_zone_v1.yaml",
    "single_drone_smoke.yaml",
    "resilience_v1.yaml",
]


@pytest.mark.parametrize("scenario_name", SHIPPED_SCENARIOS)
def test_every_referenced_frame_exists(scenario_name: str):
    scenario = load_scenario(SCENARIOS_DIR / scenario_name)
    referenced: set[str] = set()
    for mappings in scenario.frame_mappings.values():
        for mapping in mappings:
            referenced.add(mapping.frame_file)

    missing = [name for name in sorted(referenced) if not (FRAMES_DIR / name).exists()]
    assert not missing, f"frames missing for {scenario_name}: {missing}"


def test_every_frame_is_readable_jpeg():
    """Every JPEG under fixtures/frames/ must start with the JPEG magic bytes."""
    found = list(FRAMES_DIR.glob("*.jpg"))
    assert found, "no placeholder JPEGs found"
    for path in found:
        with path.open("rb") as fh:
            magic = fh.read(2)
        assert magic == b"\xff\xd8", f"{path.name} is not a JPEG (magic={magic!r})"
