"""Smoke-test scripts/check_wow_moment.sh's --dry-run path.

The full live-stack pathway (launch_swarm + validation_events tail + WS
snapshot) is not unit-testable — it requires real Redis, Ollama, Flutter
bundle, etc. We leave that to manual demo-day verification (see
docs/plans/2026-05-12-gate4-wow-moment.md §Phase 5). The --dry-run path
IS unit-testable and guards against:

  * Silent regressions in the planned-ops printout (e.g. someone changes
    the scenario name from `wow_moment_v1` without updating the WS check).
  * Argparse breakage (--timeout=N vs --timeout N).
  * Accidental side effects in dry-run mode.

Also covers the WS helper's argparse so a flag rename can't go unnoticed.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_wow_moment.sh"
_WS_HELPER = _REPO_ROOT / "scripts" / "_check_wow_moment_ws.py"


def _run(args, *, env=None) -> subprocess.CompletedProcess:
    """Invoke check_wow_moment.sh via bash. Capture stdout+stderr."""
    full = ["bash", str(_SCRIPT)] + list(args)
    return subprocess.run(
        full, capture_output=True, text=True, timeout=15,
        env=env if env is not None else dict(os.environ),
    )


def test_dry_run_exits_zero() -> None:
    """`bash check_wow_moment.sh --dry-run` must exit 0 without launching."""
    r = _run(["--dry-run"])
    assert r.returncode == 0, (
        f"--dry-run should exit 0; got rc={r.returncode}\n"
        f"stdout: {r.stdout}\nstderr: {r.stderr}"
    )


def test_dry_run_prints_expected_plan() -> None:
    """The planned-ops printout names the four load-bearing pieces:

    * the scenario id `wow_moment_v1` (storyboard target),
    * the launch script path,
    * the validation-event tail step,
    * the WS snapshot helper step.

    Any of these going silent breaks the camera-day gate without warning,
    so we assert their presence by substring match.
    """
    r = _run(["--dry-run"])
    out = r.stdout + r.stderr
    assert "wow_moment_v1" in out, f"scenario id missing from plan; got: {out}"
    assert "launch_swarm.sh" in out, (
        f"launch script missing from plan; got: {out}"
    )
    assert "validation_events.jsonl" in out, (
        f"validation-event tail step missing from plan; got: {out}"
    )
    assert "ASSIGNMENT_TOTAL_MISMATCH" in out, (
        f"the rule-id we wait on must be named in the plan; got: {out}"
    )
    assert "_check_wow_moment_ws.py" in out, (
        f"WS snapshot helper missing from plan; got: {out}"
    )


def test_dry_run_honours_timeout_flag_separate_arg() -> None:
    """`--timeout 45` (two args) overrides the default."""
    r = _run(["--dry-run", "--timeout", "45"])
    assert r.returncode == 0
    assert "TIMEOUT_S      = 45" in r.stdout, (
        f"--timeout 45 should land in the plan; got: {r.stdout}"
    )


def test_dry_run_honours_timeout_equals_form() -> None:
    """`--timeout=45` (equals form) is the launch_swarm convention."""
    r = _run(["--dry-run", "--timeout=45"])
    assert r.returncode == 0
    assert "TIMEOUT_S      = 45" in r.stdout, (
        f"--timeout=45 should land in the plan; got: {r.stdout}"
    )


def test_unknown_flag_exits_two() -> None:
    """Unknown flags get rc=2 (project convention)."""
    r = _run(["--bogus-flag"])
    assert r.returncode == 2, (
        f"unknown flag should exit 2; got rc={r.returncode}\n"
        f"stderr: {r.stderr}"
    )


def test_ws_helper_argparse_recognises_flags() -> None:
    """_check_wow_moment_ws.py --help responds, proving argparse is wired.

    Catches the case where someone renames --bridge-url or --window-s but
    forgets to update the shell script (which would silently pass an
    unknown flag and exit 2 inside the script).
    """
    r = subprocess.run(
        [sys.executable, str(_WS_HELPER), "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0, f"--help should exit 0; stderr: {r.stderr}"
    assert "--bridge-url" in r.stdout
    assert "--window-s" in r.stdout


def test_ws_helper_fails_cleanly_when_bridge_absent() -> None:
    """Connecting to a dead URL returns exit 2 with a diagnostic to stderr."""
    r = subprocess.run(
        [
            sys.executable, str(_WS_HELPER),
            "--bridge-url", "ws://127.0.0.1:1",  # port 1 is privileged + dead
            "--window-s", "0.5",
        ],
        capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 2, (
        f"dead bridge should exit 2; got rc={r.returncode}\n"
        f"stdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert "bridge connection error" in (r.stdout + r.stderr).lower()
