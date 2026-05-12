#!/usr/bin/env python3
"""measure_e4b_replan_latency.py — Phase 3a (GATE 4 wow-moment) timing driver.

Plan reference: docs/plans/2026-05-12-gate4-wow-moment.md (Phase 3 section).

Purpose
-------
The Beat 3c wow-moment camera shot needs a 2-attempt validation-loop run to
fit inside ~10 seconds of clip. That depends on the cold-vs-warm latency of
``assign_survey_points`` against ``gemma4:e4b``. This driver measures it.

What it does
------------
1. Builds a synthetic egs_state with 25 unassigned survey points
   (``sp_001`` .. ``sp_025``) across 3 active drones (``drone1`` ..
   ``drone3``).
2. Loops N iterations (default 10), recording the wall-clock latency of one
   ``assign_survey_points`` call per iteration.
3. Optionally (``--force-one-retry``) records a parallel series in which
   the FIRST in-loop response is monkeypatched to be invalid (27 points),
   so the second attempt completes the call. This gives us the
   "single-attempt" and "one-corrective-loop" cost without depending on
   the model actually mispredicting.
4. Computes p50/p95 over each series and renders a markdown table snippet
   that can be appended verbatim to the plan.

Iron rule: ``--dry-run`` must print the planned operations and exit 0 with
no network calls — see ``scripts/run_drone3_reliability.sh`` for the
convention this script follows.

Usage
-----
    # dry run (no Ollama needed)
    uv run python scripts/measure_e4b_replan_latency.py --dry-run

    # live run on the demo box (assumes gemma4:e4b warm)
    uv run python scripts/measure_e4b_replan_latency.py --iterations 10

    # also measure the full corrective-loop cost
    uv run python scripts/measure_e4b_replan_latency.py \\
        --iterations 10 --force-one-retry

    # capture markdown to a file instead of stdout
    uv run python scripts/measure_e4b_replan_latency.py \\
        --iterations 10 --output measurement.md

The script intentionally lives under ``scripts/`` with no new dependencies
(stdlib ``statistics`` + ``asyncio`` + the existing ``agents.egs_agent``
import surface).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure repo root is importable when the script is invoked directly.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.contracts import CONFIG  # noqa: E402

# NOTE: `assign_survey_points` + `EGSValidationNode` are imported LAZILY
# inside the measurement helpers below (see `_measure_single_attempt`,
# `_measure_forced_retry`). Top-level import pulls
# `agents.egs_agent.coordinator` which requires `langgraph`. The CI
# `sim + mesh + scripts` job intentionally does NOT install the `egs`
# extra, so a top-level egs_agent import here would break `--dry-run`
# (which doesn't need the LLM at all) and the helper-only unit tests
# (`_p50_p95`, `render_markdown`, markdown-shape checks). Real
# measurement is the only path that requires the egs extras — that's
# correct because you can't measure latency without the actual function
# under test.


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

NUM_SURVEY_POINTS = 25
DRONE_IDS = ["drone1", "drone2", "drone3"]


def build_synthetic_egs_state() -> Dict[str, Any]:
    """Return the 25-point / 3-drone egs_state used for every iteration.

    Point ids are zero-padded so they sort correctly (``sp_001`` ..
    ``sp_025``); the plan's storyboard pins the count at 25.
    """
    return {
        "drones_summary": {d: {"status": "active"} for d in DRONE_IDS},
        "survey_points": [
            {"id": f"sp_{i:03d}", "status": "unassigned"}
            for i in range(1, NUM_SURVEY_POINTS + 1)
        ],
    }


def _round_robin_assignment(point_ids: Sequence[str], drone_ids: Sequence[str]) -> Dict[str, Any]:
    """Build the canonical valid 25-point round-robin response."""
    buckets: Dict[str, List[str]] = {d: [] for d in drone_ids}
    for i, pid in enumerate(point_ids):
        buckets[drone_ids[i % len(drone_ids)]].append(pid)
    return {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": d, "survey_point_ids": buckets[d]}
                for d in drone_ids
            ]
        },
    }


def _overcount_assignment(point_ids: Sequence[str], drone_ids: Sequence[str]) -> Dict[str, Any]:
    """Deliberately-broken 27-point assignment used to force one corrective re-prompt.

    The plan's storyboard pins the failure mode at "27 points but 25 are
    available", so we lift that literally. The two phantom ids are
    deterministic (``sp_phantom_1``, ``sp_phantom_2``) and assigned to
    drone1 so the existing ASSIGNMENT_TOTAL_MISMATCH branch in
    ``replanning.py`` fires reliably.
    """
    base = _round_robin_assignment(point_ids, drone_ids)
    base["arguments"]["assignments"][0]["survey_point_ids"].extend(
        ["sp_phantom_1", "sp_phantom_2"]
    )
    return base


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------

async def _measure_single_attempt(egs_state: Dict[str, Any]) -> float:
    """One real call into ``assign_survey_points`` (live LLM). Returns ms.

    Imports are local so the surrounding module is importable without the
    `egs` extra (langgraph). See module docstring for the rationale.
    """
    from agents.egs_agent.replanning import assign_survey_points
    from agents.egs_agent.validation import EGSValidationNode
    node = EGSValidationNode()
    t0 = time.perf_counter()
    await assign_survey_points(egs_state, node)
    return (time.perf_counter() - t0) * 1000.0


async def _measure_forced_retry(egs_state: Dict[str, Any]) -> float:
    """One ``assign_survey_points`` run where the FIRST response is forced
    to be invalid (27 points), so the validation loop trips once and the
    second attempt completes the call. Returns ms.

    This monkeypatches ``httpx.AsyncClient.post`` for the duration of the
    call: first POST returns a 27-point assignment, subsequent POSTs
    return a valid 25-point round-robin. The LLM is bypassed entirely on
    invocation #1, so this measures (1× corrective re-prompt overhead +
    1× real LLM call). Caller is expected to NOT combine this with
    ``--dry-run``.

    Imports are local — see ``_measure_single_attempt`` for rationale.
    """
    from agents.egs_agent.replanning import assign_survey_points
    from agents.egs_agent.validation import EGSValidationNode
    node = EGSValidationNode()
    point_ids = [p["id"] for p in egs_state["survey_points"]]
    bad = _overcount_assignment(point_ids, DRONE_IDS)
    good = _round_robin_assignment(point_ids, DRONE_IDS)

    call_count = {"n": 0}

    async def fake_post(*args, **kwargs):  # noqa: ANN001 — mimic httpx signature
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        call_count["n"] += 1
        body = bad if call_count["n"] == 1 else good
        resp.json = MagicMock(return_value={"message": {"content": json.dumps(body)}})
        return resp

    t0 = time.perf_counter()
    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
        await assign_survey_points(egs_state, node)
    return (time.perf_counter() - t0) * 1000.0


def _p50_p95(samples_ms: Sequence[float]) -> tuple[float, float]:
    """Return (p50, p95) over ``samples_ms``, both in milliseconds.

    p50 is ``statistics.median``. p95 is computed via the sorted-index
    method (``sorted_vals[int(0.95 * len(vals))]``, clamped to the last
    index) for stability on small N where ``statistics.quantiles`` is
    overly opinionated about cuts.
    """
    if not samples_ms:
        return (0.0, 0.0)
    p50 = statistics.median(samples_ms)
    sorted_vals = sorted(samples_ms)
    idx = min(int(0.95 * len(sorted_vals)), len(sorted_vals) - 1)
    p95 = sorted_vals[idx]
    return (p50, p95)


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def render_markdown(
    *,
    single_attempt_ms: Sequence[float],
    retry_loop_ms: Optional[Sequence[float]],
    timestamp: Optional[datetime] = None,
    hardware_note: str = "M1 16GB, gemma4:e4b warm",
) -> str:
    """Render the measurement snippet that can be appended to the plan.

    Shape matches the spec in ``docs/plans/2026-05-12-gate4-wow-moment.md``
    Phase 3a; values are rendered in seconds (2 decimals) so the table is
    readable on the camera.
    """
    ts = timestamp or datetime.now()
    header = f"### Phase 3a measurement ({ts:%Y-%m-%d %H:%M}, {hardware_note})"

    rows: List[str] = []
    p50_s, p95_s = _p50_p95(single_attempt_ms)
    rows.append(
        f"| Single attempt                      | {p50_s/1000:.2f}    | {p95_s/1000:.2f}    | {len(single_attempt_ms):<2} |"
    )
    if retry_loop_ms is not None:
        p50_r, p95_r = _p50_p95(retry_loop_ms)
        rows.append(
            f"| Full retry-loop (1 corrective)      | {p50_r/1000:.2f}    | {p95_r/1000:.2f}    | {len(retry_loop_ms):<2} |"
        )

    table = "\n".join(
        [
            "| Metric                              | p50 (s) | p95 (s) | N  |",
            "|-------------------------------------|---------|---------|----|",
            *rows,
        ]
    )
    return f"{header}\n\n{table}\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Measure assign_survey_points latency for the GATE 4 wow-moment "
            "capture strategy decision."
        ),
    )
    parser.add_argument(
        "--iterations", "-n", type=int, default=10,
        help="Number of iterations per measurement series (default: 10).",
    )
    parser.add_argument(
        "--force-one-retry", action="store_true",
        help=(
            "Also measure a 'full retry-loop' series in which the first "
            "in-loop response is monkeypatched to be invalid (27 points), "
            "forcing exactly one corrective re-prompt before success."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print planned operations and exit 0 without any network calls.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Write markdown snippet to PATH (defaults to stdout).",
    )
    parser.add_argument(
        "--hardware-note", type=str, default="M1 16GB, gemma4:e4b warm",
        help="Free-form hardware tag rendered in the markdown header.",
    )
    return parser.parse_args(argv)


def _dry_run_message(iterations: int, force_one_retry: bool) -> str:
    endpoint = CONFIG.inference.ollama_egs_endpoint
    model = CONFIG.inference.egs_model
    lines = [
        f"[measure_e4b_replan_latency] --dry-run: would call assign_survey_points {iterations}x "
        f"against endpoint={endpoint}, model={model}",
        f"  synthetic egs_state: {NUM_SURVEY_POINTS} unassigned survey points "
        f"({DRONE_IDS}), points sp_001..sp_{NUM_SURVEY_POINTS:03d}",
    ]
    if force_one_retry:
        lines.append(
            "  would ALSO call assign_survey_points "
            f"{iterations}x with first response monkeypatched to 27 points "
            "(one corrective re-prompt forced)"
        )
    lines.append("  no network calls, no Ollama dependency, exiting 0")
    return "\n".join(lines)


async def _run_async(args: argparse.Namespace) -> str:
    egs_state = build_synthetic_egs_state()

    single_ms: List[float] = []
    for i in range(args.iterations):
        ms = await _measure_single_attempt(egs_state)
        single_ms.append(ms)
        print(f"[measure] single attempt {i+1}/{args.iterations}: {ms/1000:.2f}s", file=sys.stderr)

    retry_ms: Optional[List[float]] = None
    if args.force_one_retry:
        retry_ms = []
        for i in range(args.iterations):
            ms = await _measure_forced_retry(egs_state)
            retry_ms.append(ms)
            print(f"[measure] forced retry {i+1}/{args.iterations}: {ms/1000:.2f}s", file=sys.stderr)

    return render_markdown(
        single_attempt_ms=single_ms,
        retry_loop_ms=retry_ms,
        hardware_note=args.hardware_note,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    if args.dry_run:
        print(_dry_run_message(args.iterations, args.force_one_retry))
        return 0

    snippet = asyncio.run(_run_async(args))

    if args.output is not None:
        args.output.write_text(snippet)
        print(f"[measure_e4b_replan_latency] wrote markdown snippet to {args.output}", file=sys.stderr)
    else:
        print(snippet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
