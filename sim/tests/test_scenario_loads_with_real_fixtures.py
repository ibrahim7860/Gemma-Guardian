"""Regression: every scenario YAML that references the swapped fixtures
loads cleanly through FrameServer post-swap. Without this, a corrupt or
mis-encoded JPEG passes the lockdown tests but breaks the actual sim.

Per LOCKED FIX from review §3 #2: Task 3 has a manual `--ticks 30 --dry-run`
sanity step; this is its automated equivalent. Catches "I swapped the bytes
but Pillow can't decode them" silently."""
from __future__ import annotations

from pathlib import Path

import pytest

from sim.frame_server import FrameServer
from sim.scenario import load_scenario

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRAMES_DIR = REPO_ROOT / "sim" / "fixtures" / "frames"
SCENARIOS = (
    "disaster_zone_v1.yaml",
    "single_drone_smoke.yaml",
    "resilience_v1.yaml",
)


@pytest.mark.parametrize("scenario_name", SCENARIOS)
def test_scenario_loads_and_publishes_first_tick(scenario_name, fake_redis):
    scenario = load_scenario(REPO_ROOT / "sim" / "scenarios" / scenario_name)
    server = FrameServer(scenario, fake_redis, frames_dir=FRAMES_DIR)
    server.tick(tick_index=0)  # asserts no FileNotFoundError + no JPEG decode crash
