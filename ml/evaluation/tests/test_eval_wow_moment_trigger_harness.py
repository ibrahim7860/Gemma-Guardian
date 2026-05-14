"""Harness tests for ml/evaluation/eval_wow_moment_trigger.py.

Plan reference: docs/plans/2026-05-12-gate4-wow-moment.md Phase 3 tests #2.

Three cases:
 1. The harness counts ASSIGNMENT_TOTAL_MISMATCH correctly given a
    deterministic mocked LLM (--mock-llm injects an alternating
    27-point / 25-point response sequence; even-indexed runs trigger,
    odd-indexed runs succeed first-try).
 2. Acceptance-gate logic: ≥threshold/N exits 0; <threshold/N exits 1.
    Drives both arms via subprocess + --mock-llm.
 3. Output JSON shape contains the required fields (runs, mismatches,
    fraction, per_run, passed) so the capture script and the smoke
    runner can rely on the contract.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_EVAL_SCRIPT = _REPO_ROOT / "ml" / "evaluation" / "eval_wow_moment_trigger.py"


def _run_eval(*args: str) -> subprocess.CompletedProcess:
    """Invoke the eval script under the current interpreter.

    We do NOT use ``uv run`` here so the test stays portable (the test
    runner is already inside the project's uv-managed venv).
    """
    return subprocess.run(
        [sys.executable, str(_EVAL_SCRIPT), *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _parse_json_stdout(proc: subprocess.CompletedProcess) -> dict:
    # Find the first JSON object on stdout (langgraph emits a deprecation
    # warning on stderr; stdout is clean JSON).
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# Test 1: harness counts ASSIGNMENT_TOTAL_MISMATCH correctly
# ---------------------------------------------------------------------------

def test_harness_counts_mismatches_correctly_under_mock_llm():
    """With 6 runs and the alternating mock (even idx → 27 pts, odd → 25 pts),
    we expect exactly 3 mismatches (runs 0, 2, 4) and 3 first-try successes
    (runs 1, 3, 5). The harness MUST classify those correctly via the
    log_sink rule_ids it captures."""
    proc = _run_eval("--mock-llm", "--runs", "6", "--threshold", "1")
    assert proc.returncode == 0, (
        f"expected exit 0 with threshold=1; stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    report = _parse_json_stdout(proc)
    assert report["runs"] == 6
    assert report["mismatches"] == 3, (
        f"expected exactly 3 ASSIGNMENT_TOTAL_MISMATCH hits under the "
        f"alternating mock (runs 0/2/4); got {report['mismatches']}. "
        f"per_run={report['per_run']}"
    )
    # And the even runs have the rule_id, odd runs don't.
    for entry in report["per_run"]:
        if entry["run"] % 2 == 0:
            assert "ASSIGNMENT_TOTAL_MISMATCH" in entry["rule_ids"], (
                f"run {entry['run']} should be a mismatch hit; got rule_ids={entry['rule_ids']}"
            )
            assert entry["had_mismatch"] is True
        else:
            assert entry["rule_ids"] == [], (
                f"run {entry['run']} should be first-try success; got rule_ids={entry['rule_ids']}"
            )
            assert entry["had_mismatch"] is False


# ---------------------------------------------------------------------------
# Test 2: acceptance-gate logic exits 0 / 1 at the threshold boundary
# ---------------------------------------------------------------------------

class TestAcceptanceGateExitCodes:
    def test_below_threshold_exits_1(self):
        """4 runs, 2 mismatches, threshold=3 → fails the gate, exit 1.
        Catches a future change that silently swaps the comparison.
        """
        proc = _run_eval("--mock-llm", "--runs", "4", "--threshold", "3")
        assert proc.returncode == 1, (
            f"expected exit 1 (2 mismatches < threshold 3); "
            f"got {proc.returncode}; stdout={proc.stdout!r}"
        )
        report = _parse_json_stdout(proc)
        assert report["mismatches"] == 2
        assert report["passed"] is False

    def test_at_threshold_exits_0(self):
        """4 runs, 2 mismatches, threshold=2 → exactly meets the gate, exit 0.
        The acceptance gate is >= (not >), so the boundary value passes.
        """
        proc = _run_eval("--mock-llm", "--runs", "4", "--threshold", "2")
        assert proc.returncode == 0, (
            f"expected exit 0 (2 mismatches >= threshold 2); "
            f"got {proc.returncode}; stdout={proc.stdout!r}"
        )
        report = _parse_json_stdout(proc)
        assert report["mismatches"] == 2
        assert report["passed"] is True

    def test_default_threshold_20_runs_alternating_mock_fails(self):
        """Default threshold is 12; alternating mock over 20 runs yields
        only 10 mismatches → exit 1. This is the EXPECTED failure mode
        when run on the demo box with a mocked LLM; it proves the harness
        wouldn't false-positive on a model that hallucinates only 50% of
        the time.
        """
        proc = _run_eval("--mock-llm", "--runs", "20")
        assert proc.returncode == 1
        report = _parse_json_stdout(proc)
        assert report["mismatches"] == 10
        assert report["threshold"] == 12
        assert report["passed"] is False


# ---------------------------------------------------------------------------
# Test 3: output JSON contains every documented field
# ---------------------------------------------------------------------------

def test_output_json_shape_contains_required_fields():
    """Downstream consumers (capture script, smoke runner) rely on the
    field set. Any missing key is a contract break."""
    proc = _run_eval("--mock-llm", "--runs", "2", "--threshold", "1")
    assert proc.returncode == 0
    report = _parse_json_stdout(proc)

    for required in ("runs", "mismatches", "fraction", "per_run", "passed"):
        assert required in report, (
            f"missing required field {required!r} in eval output; got keys={sorted(report)}"
        )

    assert isinstance(report["per_run"], list)
    assert len(report["per_run"]) == report["runs"]
    for entry in report["per_run"]:
        assert "run" in entry
        assert "rule_ids" in entry
        assert isinstance(entry["rule_ids"], list)


# ---------------------------------------------------------------------------
# Bonus: --dry-run never hits Ollama
# ---------------------------------------------------------------------------

def test_dry_run_exits_zero_without_network():
    """Iron-rule convention from scripts/run_drone3_reliability.sh:
    --dry-run prints the plan and exits 0 with no network calls. The
    harness MUST honor that so CI can smoke-test it on a box with no
    Ollama installed."""
    proc = _run_eval("--dry-run")
    assert proc.returncode == 0
    assert "--dry-run" in proc.stdout
    assert "wow_moment_v1" in proc.stdout
    assert "ASSIGNMENT_TOTAL_MISMATCH" in proc.stdout
