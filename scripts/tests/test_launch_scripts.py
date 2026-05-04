"""Smoke tests for the bash launch scripts.

We don't execute the full tmux stack in CI — that needs Redis, Ollama, and
multiple agent processes. We do verify:

- bash -n syntax check for all three scripts
- ``stop_demo.sh`` is idempotent (re-runs cleanly when nothing is running)
- ``launch_swarm.sh --dry-run`` prints the planned tmux invocations
- ``launch_swarm.sh --dry-run`` skips agents/services that aren't built yet
- ``launch_swarm.sh`` writes a ``.gg_started_redis`` sentinel only when it
  daemonized its own Redis, so ``stop_demo.sh`` can avoid clobbering a
  long-lived system Redis it didn't start.
- ``--drones=<csv>`` rejects ids not in the scenario YAML rather than
  silently launching ghost agents.
"""
from __future__ import annotations

import os
import signal
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

SCRIPTS = [
    SCRIPTS_DIR / "launch_swarm.sh",
    SCRIPTS_DIR / "stop_demo.sh",
    SCRIPTS_DIR / "run_full_demo.sh",
    SCRIPTS_DIR / "run_resilience_scenario.sh",
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


def test_launch_swarm_auto_derives_three_drones_from_disaster_zone_v1():
    """Default --drones=auto reads the scenario YAML and expands to its full
    drone roster, so add/remove drones in scenario YAML without editing the
    bash script."""
    script = SCRIPTS_DIR / "launch_swarm.sh"
    result = subprocess.run(
        ["bash", str(script), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    for drone_id in ("drone1", "drone2", "drone3"):
        assert f"--drone-id {drone_id}" in result.stdout, (
            f"expected agent invocation for {drone_id}; stdout was:\n{result.stdout}"
        )


def test_launch_swarm_auto_derives_single_drone_from_smoke_scenario():
    """When the scenario only has one drone, only one agent is planned."""
    script = SCRIPTS_DIR / "launch_swarm.sh"
    result = subprocess.run(
        ["bash", str(script), "single_drone_smoke", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert "--drone-id drone1" in result.stdout
    assert "--drone-id drone2" not in result.stdout
    assert "--drone-id drone3" not in result.stdout


def test_launch_swarm_explicit_drones_override_disables_auto():
    """``--drones=drone1,drone2`` should win over the scenario's full roster."""
    script = SCRIPTS_DIR / "launch_swarm.sh"
    result = subprocess.run(
        ["bash", str(script), "disaster_zone_v1", "--drones=drone1,drone2", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert "--drone-id drone1" in result.stdout
    assert "--drone-id drone2" in result.stdout
    assert "--drone-id drone3" not in result.stdout


def test_launch_swarm_explicit_drones_unknown_id_is_rejected():
    """``--drones=drone7`` against disaster_zone_v1 (drones 1-3) must fail
    fast with a clear error rather than launching a ghost agent for an id
    the scenario never declared."""
    script = SCRIPTS_DIR / "launch_swarm.sh"
    result = subprocess.run(
        ["bash", str(script), "disaster_zone_v1", "--drones=drone7", "--dry-run"],
        capture_output=True, text=True, timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    assert result.returncode != 0, (
        f"expected non-zero exit; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "drone7" in combined, f"error should mention the offending id; got: {combined!r}"
    # No agent should have been planned for drone7.
    assert "--drone-id drone7" not in result.stdout


def test_launch_swarm_explicit_drones_partially_valid_is_rejected():
    """A mix of one valid and one unknown id is still a hard failure — silent
    truncation would be worse than a loud rejection."""
    script = SCRIPTS_DIR / "launch_swarm.sh"
    result = subprocess.run(
        ["bash", str(script), "disaster_zone_v1", "--drones=drone1,droneX", "--dry-run"],
        capture_output=True, text=True, timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "droneX" in combined


def test_launch_swarm_duration_propagates_to_runners():
    """``launch_swarm.sh --duration=30`` should pass --duration through to
    sim/waypoint_runner.py and sim/frame_server.py (the only processes that
    accept it). Drone agents and EGS do not, so the flag must NOT appear on
    their commands."""
    script = SCRIPTS_DIR / "launch_swarm.sh"
    result = subprocess.run(
        ["bash", str(script), "--duration=30", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    # Sim runners get --duration.
    assert "waypoint_runner.py" in result.stdout
    waypoint_lines = [ln for ln in result.stdout.splitlines() if "waypoint_runner.py" in ln]
    assert any("--duration 30" in ln for ln in waypoint_lines), (
        f"waypoint_runner missing --duration; lines were:\n{waypoint_lines}"
    )
    frames_lines = [ln for ln in result.stdout.splitlines() if "frame_server.py" in ln]
    assert any("--duration 30" in ln for ln in frames_lines), (
        f"frame_server missing --duration; lines were:\n{frames_lines}"
    )
    # Drone agents do NOT get --duration (they don't accept it).
    drone_agent_lines = [ln for ln in result.stdout.splitlines() if "drone_agent/main.py" in ln]
    if drone_agent_lines:
        for ln in drone_agent_lines:
            assert "--duration" not in ln, f"drone_agent should not receive --duration: {ln}"


def test_launch_swarm_default_no_duration_flag_anywhere():
    """When --duration is omitted, no runner should get a --duration flag."""
    script = SCRIPTS_DIR / "launch_swarm.sh"
    result = subprocess.run(
        ["bash", str(script), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    assert result.returncode == 0
    assert "--duration" not in result.stdout


# ---------------------------------------------------------------------------
# Redis-ownership sentinel
#
# Live-run anomaly #3 (docs/sim-live-run-notes.md): stop_demo.sh would happily
# `redis-cli shutdown nosave` a system-managed Redis it never started, leaving
# Hazim's WSL2 box without a broker until the service was kicked. The fix
# is to record ownership at launch time and only shut down what we daemonized.
# ---------------------------------------------------------------------------


def _make_stub(path: Path, body: str) -> Path:
    """Write an executable bash stub at ``path`` whose body is ``body``."""
    path.write_text("#!/bin/bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _isolated_path_env(fake_bin: Path, log_dir: Path, **extra: str) -> dict[str, str]:
    """Build an env dict with ``fake_bin`` first on PATH so our stubs win
    over real ``redis-cli`` / ``redis-server`` if they're installed."""
    env = {**os.environ, "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
           "GG_LOG_DIR": str(log_dir)}
    env.update(extra)
    return env


def test_launch_swarm_writes_redis_sentinel_when_it_daemonized_redis(tmp_path):
    """No Redis running → launch_swarm starts one and leaves a sentinel."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    # redis-cli ping fails (no broker yet), other subcommands no-op.
    _make_stub(
        fake_bin / "redis-cli",
        'if [ "$1" = "ping" ]; then exit 1; fi\nexit 0\n',
    )
    # redis-server "starts" silently — we never actually daemonize anything.
    _make_stub(fake_bin / "redis-server", "exit 0\n")

    env = _isolated_path_env(fake_bin, log_dir, GG_NO_TMUX="1")
    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "launch_swarm.sh"), "--drones=drone1"],
        capture_output=True, text=True, timeout=20, env=env,
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert (log_dir / ".gg_started_redis").exists(), (
        "expected sentinel after launch daemonized its own Redis; "
        f"log_dir contents = {list(log_dir.iterdir())}"
    )


def test_launch_swarm_no_sentinel_when_redis_already_running(tmp_path):
    """Existing Redis → launch_swarm reuses it and writes no sentinel."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    # redis-cli ping succeeds → reuse path.
    _make_stub(fake_bin / "redis-cli", "exit 0\n")
    # redis-server present but should not be invoked.
    _make_stub(fake_bin / "redis-server", "exit 0\n")

    env = _isolated_path_env(fake_bin, log_dir, GG_NO_TMUX="1")
    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "launch_swarm.sh"), "--drones=drone1"],
        capture_output=True, text=True, timeout=20, env=env,
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert not (log_dir / ".gg_started_redis").exists(), (
        "expected NO sentinel when Redis was already running"
    )


def test_stop_demo_shuts_down_redis_when_sentinel_present(tmp_path):
    """Sentinel says we own this Redis → stop_demo issues `shutdown nosave`
    and cleans up the sentinel afterwards."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    sentinel = log_dir / ".gg_started_redis"
    sentinel.write_text("")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    cli_calls = tmp_path / "redis_cli_calls.log"
    _make_stub(
        fake_bin / "redis-cli",
        f'echo "$@" >> "{cli_calls}"\nexit 0\n',
    )

    env = _isolated_path_env(fake_bin, log_dir)
    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "stop_demo.sh")],
        capture_output=True, text=True, timeout=20, env=env,
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    calls = cli_calls.read_text() if cli_calls.exists() else ""
    assert "shutdown nosave" in calls, (
        f"expected redis-cli shutdown nosave to be called; saw: {calls!r}"
    )
    assert not sentinel.exists(), "sentinel must be removed once we shut Redis down"


def test_stop_demo_leaves_redis_alone_when_sentinel_absent(tmp_path):
    """No sentinel → Redis is someone else's responsibility, leave it running."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    cli_calls = tmp_path / "redis_cli_calls.log"
    _make_stub(
        fake_bin / "redis-cli",
        f'echo "$@" >> "{cli_calls}"\nexit 0\n',
    )

    env = _isolated_path_env(fake_bin, log_dir)
    result = subprocess.run(
        ["bash", str(SCRIPTS_DIR / "stop_demo.sh")],
        capture_output=True, text=True, timeout=20, env=env,
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    calls = cli_calls.read_text() if cli_calls.exists() else ""
    assert "shutdown" not in calls, (
        f"redis-cli shutdown should NOT have been called; saw: {calls!r}"
    )


# ---------------------------------------------------------------------------
# run_resilience_scenario.sh — Phase D / E launcher for resilience_v1
# ---------------------------------------------------------------------------


def test_run_resilience_scenario_dry_run_targets_resilience_v1(tmp_path):
    """``run_resilience_scenario.sh --dry-run`` must hand off to launch_swarm
    with the resilience_v1 scenario id (and a sensible default --duration)
    so Qasim can rehearse the EGS replan loop without remembering flags."""
    script = SCRIPTS_DIR / "run_resilience_scenario.sh"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    result = subprocess.run(
        ["bash", str(script), "--dry-run"],
        capture_output=True, text=True, timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1", "GG_LOG_DIR": str(log_dir)},
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    assert "resilience_v1" in result.stdout, (
        f"expected scenario name in plan output; saw:\n{result.stdout}"
    )
    # Default duration must show up on the sim runner invocations.
    waypoint_lines = [ln for ln in result.stdout.splitlines() if "waypoint_runner.py" in ln]
    assert waypoint_lines, "no waypoint_runner invocation in plan"
    assert any("--duration" in ln for ln in waypoint_lines), (
        f"expected default --duration on waypoint_runner; saw:\n{waypoint_lines}"
    )


def test_run_resilience_scenario_user_duration_overrides_default(tmp_path):
    """If the user passes ``--duration=N``, the wrapper must not double-up
    the flag (launch_swarm rejects unknown flags but this also guards
    surprise behaviour where user intent is silently overridden)."""
    script = SCRIPTS_DIR / "run_resilience_scenario.sh"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    result = subprocess.run(
        ["bash", str(script), "--dry-run", "--duration=15"],
        capture_output=True, text=True, timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1", "GG_LOG_DIR": str(log_dir)},
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    waypoint_lines = [ln for ln in result.stdout.splitlines() if "waypoint_runner.py" in ln]
    assert any("--duration 15" in ln for ln in waypoint_lines), (
        f"user-supplied --duration=15 should reach waypoint_runner; saw:\n{waypoint_lines}"
    )
    # The default (240) must not also appear.
    for ln in waypoint_lines:
        assert "--duration 240" not in ln, f"default duration leaked through: {ln}"


def test_run_resilience_scenario_subset_drones_forwarded(tmp_path):
    """``--drones=drone1`` (passed by the operator who wants to run the
    manual_pilot stand-in for that id) must reach launch_swarm verbatim."""
    script = SCRIPTS_DIR / "run_resilience_scenario.sh"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    result = subprocess.run(
        ["bash", str(script), "--dry-run", "--drones=drone2,drone3"],
        capture_output=True, text=True, timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1", "GG_LOG_DIR": str(log_dir)},
    )
    assert result.returncode == 0, f"stderr={result.stderr!r}"
    # Implementation detail: launch_swarm prints planned drone agent
    # invocations for every requested id. drone1 must NOT appear.
    drone_lines = [ln for ln in result.stdout.splitlines() if "--drone-id" in ln]
    if drone_lines:
        assert not any("--drone-id drone1" in ln for ln in drone_lines), (
            f"drone1 should be omitted; saw:\n{drone_lines}"
        )


# ---------------------------------------------------------------------------
# run_full_demo.sh argument forwarding
# ---------------------------------------------------------------------------


def test_run_full_demo_forwards_duration_to_launch_swarm(tmp_path):
    """``run_full_demo.sh --duration=N --dry-run`` should hand the flag through
    to ``launch_swarm.sh`` so it lands on the sim runner invocations.

    run_full_demo.sh wraps launch_swarm with a trailing ``tail -F``, which
    runs forever even after a successful --dry-run. We start the script in
    its own process group, capture launch_swarm's plan output, then SIGTERM
    the whole group to take down ``tail -F`` and any trap-spawned children.
    """
    script = SCRIPTS_DIR / "run_full_demo.sh"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    proc = subprocess.Popen(
        ["bash", str(script), "--duration=42", "--dry-run"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "GG_NO_TMUX": "1", "GG_LOG_DIR": str(log_dir)},
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            out, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate(timeout=5)
    combined = out + err
    waypoint_lines = [ln for ln in combined.splitlines() if "waypoint_runner.py" in ln]
    assert any("--duration 42" in ln for ln in waypoint_lines), (
        f"expected --duration 42 forwarded to waypoint_runner; saw:\n{combined}"
    )
    frames_lines = [ln for ln in combined.splitlines() if "frame_server.py" in ln]
    assert any("--duration 42" in ln for ln in frames_lines), (
        f"expected --duration 42 forwarded to frame_server; saw:\n{combined}"
    )
