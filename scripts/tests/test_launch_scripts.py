"""Smoke tests for the bash launch scripts.

We don't execute the full tmux stack in CI — that needs Redis, Ollama, and
multiple agent processes. We do verify:

- bash -n syntax check for all three scripts
- ``stop_demo.sh`` is idempotent (re-runs cleanly when nothing is running)
- ``launch_swarm.sh --dry-run`` prints the planned tmux invocations
- ``launch_swarm.sh --dry-run`` skips agents/services that aren't built yet
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

SCRIPTS = [
    SCRIPTS_DIR / "launch_swarm.sh",
    SCRIPTS_DIR / "stop_demo.sh",
    SCRIPTS_DIR / "run_full_demo.sh",
]


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_script_passes_bash_syntax_check(script: Path):
    assert script.exists(), f"{script} missing"
    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert result.returncode == 0, f"syntax error in {script.name}: {result.stderr}"


def test_stop_demo_idempotent():
    """Running stop_demo when nothing is running must succeed and not blow up."""
    script = SCRIPTS_DIR / "stop_demo.sh"
    # First run.
    r1 = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=20)
    assert r1.returncode == 0, f"first stop_demo failed: rc={r1.returncode} stderr={r1.stderr}"
    # Second run.
    r2 = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=20)
    assert r2.returncode == 0, f"second stop_demo failed: rc={r2.returncode} stderr={r2.stderr}"


def test_launch_swarm_dry_run_prints_commands():
    script = SCRIPTS_DIR / "launch_swarm.sh"
    result = subprocess.run(
        ["bash", str(script), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    assert result.returncode == 0, f"dry-run failed: stderr={result.stderr}"
    # Sim components always exist (we just shipped them).
    assert "waypoint_runner.py" in result.stdout
    assert "frame_server.py" in result.stdout
    assert "mesh_simulator/main.py" in result.stdout


def test_launch_swarm_dry_run_skips_missing_components():
    """drone_agent and egs_agent main.py exist but ws_bridge/main.py is in
    a different location. The script must skip missing components with a
    clear note rather than failing."""
    script = SCRIPTS_DIR / "launch_swarm.sh"
    result = subprocess.run(
        ["bash", str(script), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    # Either it includes a component or it logs that it's skipping it — never crashes.
    assert result.returncode == 0
    # Output mentions every drone agent we'd launch (drone1, drone2, drone3 by default).
    assert "drone1" in result.stdout
