#!/usr/bin/env python3
"""eval_wow_moment_trigger.py — Phase 3b (GATE 4 wow-moment) acceptance gate.

Plan reference: docs/plans/2026-05-12-gate4-wow-moment.md Phase 3b.

Purpose
-------
The Beat 3c camera moment depends on Gemma 4 E4B reliably over-counting
when assigning 25 awkwardly-clustered survey points across 3 drones, so
the ASSIGNMENT_TOTAL_MISMATCH rule fires and the corrective-prompt
overlay renders on the dashboard. This script measures that trigger rate.

What it does
------------
1. Loads ``sim/scenarios/wow_moment_v1.yaml`` (25 points, 3 drones).
2. Builds a synthetic egs_state with the 25 unassigned survey points and
   3 active drones.
3. Runs ``assign_survey_points`` N times (default 20) against the live
   Ollama endpoint configured by ``CONFIG.inference.ollama_egs_endpoint``
   with model ``CONFIG.inference.egs_model`` (gemma4:e4b).
4. Counts how many runs produced at least one ASSIGNMENT_TOTAL_MISMATCH
   event (captured via the per-run ``log_sink`` plumbed into
   ``assign_survey_points``).
5. Emits a JSON report to stdout and exits 0 iff
   ``mismatches >= acceptance_threshold`` (default 12, i.e. 60%).

Iron-rule conventions
---------------------
* ``--dry-run`` prints the planned configuration and exits 0 with NO
  network calls — mirrors ``scripts/run_drone3_reliability.sh`` and
  ``scripts/measure_e4b_replan_latency.py``.
* ``--mock-llm`` injects a deterministic mock client so the harness can
  be tested without hitting Ollama. Returns 27 points on every other
  run, 25 points on the rest, so the harness can verify both arms of the
  acceptance gate. NOT used on real demo-box runs.

Usage
-----
    # dry run (no Ollama needed)
    uv run python ml/evaluation/eval_wow_moment_trigger.py --dry-run

    # mocked end-to-end (CI-friendly)
    uv run python ml/evaluation/eval_wow_moment_trigger.py --mock-llm --runs 20

    # live run on the demo box (assumes gemma4:e4b warm)
    uv run python ml/evaluation/eval_wow_moment_trigger.py --runs 20

Exit codes
----------
0 — acceptance gate passed (mismatches >= threshold)
1 — acceptance gate failed (mismatches <  threshold)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure repo root is importable when invoked directly.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents.egs_agent.replanning import assign_survey_points  # noqa: E402
from agents.egs_agent.validation import EGSValidationNode  # noqa: E402
from shared.contracts import CONFIG  # noqa: E402
from sim.scenario import Scenario, load_scenario  # noqa: E402


DEFAULT_SCENARIO = REPO_ROOT / "sim" / "scenarios" / "wow_moment_v1.yaml"
DEFAULT_RUNS = 20
DEFAULT_THRESHOLD = 12  # ≥12/20 (60%) per plan Phase 3b acceptance gate
DRONE_IDS = ["drone1", "drone2", "drone3"]


# ---------------------------------------------------------------------------
# State construction
# ---------------------------------------------------------------------------

def build_egs_state_from_scenario(scenario: Scenario) -> Dict[str, Any]:
    """Flatten the scenario's per-drone waypoint lists into the egs_state
    shape that ``assign_survey_points`` expects: all waypoints unassigned,
    all drones active. The LLM has to do the partition itself given a flat
    list (storyboard contract — no per-drone pre-partition).
    """
    survey_points = [
        {"id": wp.id, "status": "unassigned"}
        for d in scenario.drones
        for wp in d.waypoints
    ]
    drones_summary = {
        d.drone_id: {"status": "active"} for d in scenario.drones
    }
    return {
        "drones_summary": drones_summary,
        "survey_points": survey_points,
    }


# ---------------------------------------------------------------------------
# Mock LLM (only used with --mock-llm)
# ---------------------------------------------------------------------------

def _round_robin_25(point_ids: Sequence[str]) -> Dict[str, Any]:
    """Valid 25-point round-robin across DRONE_IDS."""
    buckets: Dict[str, List[str]] = {d: [] for d in DRONE_IDS}
    for i, pid in enumerate(point_ids):
        buckets[DRONE_IDS[i % len(DRONE_IDS)]].append(pid)
    return {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": d, "survey_point_ids": buckets[d]}
                for d in DRONE_IDS
            ]
        },
    }


def _overcount_27(point_ids: Sequence[str]) -> Dict[str, Any]:
    """Deliberately-broken 27-point assignment (2 phantom ids on drone1).
    Reuses the exact storyboard literal ("27 points but 25 are available")
    via the existing ASSIGNMENT_TOTAL_MISMATCH branch in replanning.py.
    """
    base = _round_robin_25(point_ids)
    base["arguments"]["assignments"][0]["survey_point_ids"].extend(
        ["sp_phantom_1", "sp_phantom_2"]
    )
    return base


def _make_mock_post(run_index: int, point_ids: Sequence[str]) -> AsyncMock:
    """Return a fake httpx.AsyncClient.post that returns 27 points on the
    first call (when ``run_index`` is even, i.e. half the runs) and 25
    points on the second call (so the loop terminates).

    Even-indexed runs trigger ASSIGNMENT_TOTAL_MISMATCH; odd-indexed runs
    succeed on attempt 1. With DEFAULT_RUNS=20 and threshold=12 the
    harness should land 10 mismatches and FAIL the acceptance gate — the
    odd/even split is on purpose so test_harness can exercise both arms
    by choosing how many runs to schedule.
    """
    will_overcount = (run_index % 2 == 0)
    call_count = {"n": 0}

    async def fake_post(*args, **kwargs):  # noqa: ANN001
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        call_count["n"] += 1
        if will_overcount and call_count["n"] == 1:
            body = _overcount_27(point_ids)
        else:
            body = _round_robin_25(point_ids)
        resp.json = MagicMock(return_value={"message": {"content": json.dumps(body)}})
        return resp

    return AsyncMock(side_effect=fake_post)


# ---------------------------------------------------------------------------
# Per-run execution
# ---------------------------------------------------------------------------

async def _run_one(
    egs_state: Dict[str, Any],
    *,
    use_mock: bool,
    run_index: int,
) -> List[str]:
    """Execute one ``assign_survey_points`` call and return the list of
    rule_ids seen on failed attempts (most useful is ASSIGNMENT_TOTAL_MISMATCH).
    """
    node = EGSValidationNode()
    sink_records: List[Dict[str, Any]] = []

    point_ids = [p["id"] for p in egs_state["survey_points"]]

    if use_mock:
        mock_post = _make_mock_post(run_index, point_ids)
        with patch("httpx.AsyncClient.post", new=mock_post):
            await assign_survey_points(
                egs_state,
                node,
                log_sink=sink_records.append,
            )
    else:
        await assign_survey_points(
            egs_state,
            node,
            log_sink=sink_records.append,
        )

    return [
        s["rule_id"]
        for s in sink_records
        if s.get("rule_id") is not None and s.get("valid") is False
    ]


# ---------------------------------------------------------------------------
# Acceptance gate
# ---------------------------------------------------------------------------

TARGET_RULE_ID = "ASSIGNMENT_TOTAL_MISMATCH"


def _run_had_mismatch(rule_ids: Sequence[str]) -> bool:
    return TARGET_RULE_ID in rule_ids


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Run the GATE 4 wow-moment acceptance gate: assign_survey_points "
            "against the 25-point wow_moment_v1 scenario, count "
            "ASSIGNMENT_TOTAL_MISMATCH triggers, exit 0 iff ≥threshold."
        )
    )
    p.add_argument(
        "--runs", "-n", type=int, default=DEFAULT_RUNS,
        help=f"How many assign_survey_points calls to make (default: {DEFAULT_RUNS}).",
    )
    p.add_argument(
        "--scenario", type=Path, default=DEFAULT_SCENARIO,
        help=f"Scenario YAML to load (default: {DEFAULT_SCENARIO}).",
    )
    p.add_argument(
        "--threshold", type=int, default=DEFAULT_THRESHOLD,
        help=(
            "Minimum ASSIGNMENT_TOTAL_MISMATCH hits required to pass the "
            f"acceptance gate (default: {DEFAULT_THRESHOLD})."
        ),
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print planned configuration and exit 0 without any network calls.",
    )
    p.add_argument(
        "--mock-llm", action="store_true",
        help=(
            "Inject a deterministic mock LLM (alternating 27-point/25-point "
            "responses) instead of hitting Ollama. Used by the harness "
            "test; omit on real demo-box runs."
        ),
    )
    return p.parse_args(argv)


def _dry_run_message(args: argparse.Namespace) -> str:
    endpoint = CONFIG.inference.ollama_egs_endpoint
    model = CONFIG.inference.egs_model
    lines = [
        f"[eval_wow_moment_trigger] --dry-run: would call assign_survey_points "
        f"{args.runs}x against endpoint={endpoint}, model={model}",
        f"  scenario: {args.scenario}",
        f"  acceptance threshold: ≥{args.threshold}/{args.runs} "
        f"({TARGET_RULE_ID} triggers)",
    ]
    if args.mock_llm:
        lines.append(
            "  --mock-llm: would inject deterministic mock client "
            "(even-indexed runs → 27 points → mismatch; odd-indexed → 25 points → first-try)"
        )
    lines.append("  no network calls, exiting 0")
    return "\n".join(lines)


async def _run_async(args: argparse.Namespace) -> Dict[str, Any]:
    scenario = load_scenario(args.scenario)
    egs_state = build_egs_state_from_scenario(scenario)

    per_run: List[Dict[str, Any]] = []
    mismatches = 0
    for i in range(args.runs):
        rule_ids = await _run_one(
            # Deep-ish copy: replanning.py reads survey_points + drones_summary
            # but doesn't mutate them, but defensive copy keeps each run
            # isolated regardless.
            {
                "drones_summary": dict(egs_state["drones_summary"]),
                "survey_points": [dict(p) for p in egs_state["survey_points"]],
            },
            use_mock=args.mock_llm,
            run_index=i,
        )
        hit = _run_had_mismatch(rule_ids)
        if hit:
            mismatches += 1
        per_run.append({"run": i, "rule_ids": rule_ids, "had_mismatch": hit})

    fraction = mismatches / args.runs if args.runs else 0.0
    passed = mismatches >= args.threshold
    return {
        "runs": args.runs,
        "mismatches": mismatches,
        "fraction": fraction,
        "threshold": args.threshold,
        "per_run": per_run,
        "passed": passed,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    if args.dry_run:
        print(_dry_run_message(args))
        return 0

    report = asyncio.run(_run_async(args))
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
