"""launch_swarm.sh must pass --scenario to each drone agent."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_drone_agent_receives_scenario_flag():
    env = dict(os.environ)
    env["GG_NO_TMUX"] = "1"
    out = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "launch_swarm.sh"), "disaster_zone_v1", "--dry-run"],
        capture_output=True, text=True, env=env, check=True,
    )
    drone_lines = [
        ln for ln in out.stdout.splitlines()
        if "agents.drone_agent" in ln and "--drone-id" in ln
    ]
    assert drone_lines, f"no drone agent invocations found in:\n{out.stdout}"
    for ln in drone_lines:
        assert "--scenario disaster_zone_v1" in ln, f"missing --scenario in: {ln}"
