"""Tests for ``scripts/measure_e4b_replan_latency.py`` — Phase 3a driver.

Plan reference: docs/plans/2026-05-12-gate4-wow-moment.md (Phase 3 / test
inventory row 3, ``scripts/tests/test_measure_e4b_replan_latency.py``).

We cover the four behaviors the plan calls out:

1. ``--dry-run`` exits 0 quickly and prints the expected "would call"
   plan line — no network is touched (mirrors the convention in
   ``scripts/run_drone3_reliability.sh`` and the parametrize-over-scripts
   pattern in ``scripts/tests/test_launch_scripts.py``).
2. With a stubbed ``httpx.AsyncClient`` driving deterministic latencies
   (100, 200, ..., 1000 ms), p50/p95 computed by the script match what
   we expect (within a small slop budget — ``asyncio.sleep`` is not
   perfectly precise on busy CI).
3. ``--force-one-retry`` produces a 2-row markdown table
   (single + retry-loop) with the row header "Full retry-loop".
4. The markdown snippet has the canonical shape: headers
   ("| Metric", "p50 (s)"), the "Single attempt" row, no trailing
   whitespace-only lines, and valid GFM table separators.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "measure_e4b_replan_latency.py"

# Make the script importable for in-process tests so we can monkeypatch
# httpx and exercise the timing path without a subprocess (subprocess
# would need a real Ollama; we don't have one in CI).
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# 1. --dry-run exits 0 + prints "would call"
# ---------------------------------------------------------------------------


def test_dry_run_exits_zero_and_prints_would_call():
    """``--dry-run`` must finish in under 5 seconds with no network calls,
    print the expected plan line, and exit 0.

    Iron-rule: the script must not import Ollama; the in-process test
    suite would notice and fail otherwise. Run as a subprocess so we
    actually exercise the CLI entry point a future user will hit.
    """
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run"],
        capture_output=True, text=True, timeout=15,
        env={**os.environ},
    )
    assert result.returncode == 0, (
        f"--dry-run exited {result.returncode}; stderr={result.stderr!r}"
    )
    # Plan line must mention "would call" and the script's defaults so
    # the user can sanity-check what a non-dry-run would do.
    assert "would call assign_survey_points" in result.stdout, (
        f"missing 'would call' plan line; stdout={result.stdout!r}"
    )
    assert "10x" in result.stdout, "default iterations (10) should appear"
    # The 25-point/3-drone fixture is load-bearing for the storyboard.
    assert "25 unassigned survey points" in result.stdout
    assert "drone1" in result.stdout and "drone3" in result.stdout
    # Endpoint + model echoed from CONFIG so the operator notices misconfig early.
    assert "endpoint=" in result.stdout
    assert "model=" in result.stdout


def test_dry_run_with_force_one_retry_mentions_corrective_reprompt():
    """When ``--force-one-retry`` is on alongside ``--dry-run``, the plan
    output must surface the corrective-reprompt run so the user knows
    BOTH series would happen on a non-dry-run."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", "--force-one-retry"],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0
    assert "27 points" in result.stdout
    assert "corrective re-prompt" in result.stdout


# ---------------------------------------------------------------------------
# 2. p50/p95 computed correctly against deterministic mock latencies
# ---------------------------------------------------------------------------


def test_p50_and_p95_match_known_latencies():
    """Feed deterministic latencies 100, 200, ..., 1000 ms into the
    measurement loop via a sleeping mock. With 10 evenly-spaced samples
    the script should compute p50 ≈ 550 ms and p95 ≈ 950 ms.

    We exercise the in-process API rather than the CLI because (a) we
    need to inject the mock at a Python boundary and (b) the resulting
    markdown is rendered by ``render_markdown`` which we can call
    directly to dodge subprocess + asyncio.sleep flakiness.
    """
    from scripts.measure_e4b_replan_latency import (
        _measure_single_attempt,
        _p50_p95,
        build_synthetic_egs_state,
    )

    target_latencies_s = [0.1 * i for i in range(1, 11)]  # 100ms .. 1000ms
    call_idx = {"n": 0}

    async def fake_post(*args, **kwargs):
        # Sleep the target latency, then return a valid 25-point response.
        i = call_idx["n"]
        call_idx["n"] += 1
        await asyncio.sleep(target_latencies_s[i])
        from scripts.measure_e4b_replan_latency import (
            DRONE_IDS,
            _round_robin_assignment,
        )
        point_ids = [f"sp_{j:03d}" for j in range(1, 26)]
        body = _round_robin_assignment(point_ids, DRONE_IDS)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json = MagicMock(return_value={"message": {"content": json.dumps(body)}})
        return resp

    egs_state = build_synthetic_egs_state()
    measured_ms: List[float] = []

    async def collect():
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)):
            for _ in range(10):
                ms = await _measure_single_attempt(egs_state)
                measured_ms.append(ms)

    asyncio.run(collect())

    p50_ms, p95_ms = _p50_p95(measured_ms)
    # Slop budget: ``asyncio.sleep`` is monotonically *at least* the
    # requested duration, so measured values skew slightly high. The
    # plan called for ±50ms, but on a busy CI box (and on M1 under load)
    # the 1000ms-sleep arm typically lands at 1010-1050ms because the
    # outer measurement also includes validation + JSON parse. Bound at
    # ±100ms — still tight enough to catch a miscomputed quantile
    # (which would land hundreds of ms off), loose enough to not flake.
    assert 500.0 <= p50_ms <= 650.0, f"p50 out of range: {p50_ms}ms (expected ~550)"
    assert 900.0 <= p95_ms <= 1100.0, f"p95 out of range: {p95_ms}ms (expected ~950)"


def test_p50_p95_helper_handles_empty_and_single_value():
    """The stdlib quantiles function would raise on N<2 — our helper
    returns sensible defaults instead so the markdown can still render."""
    from scripts.measure_e4b_replan_latency import _p50_p95
    assert _p50_p95([]) == (0.0, 0.0)
    p50, p95 = _p50_p95([42.0])
    assert p50 == 42.0 and p95 == 42.0


# ---------------------------------------------------------------------------
# 3. --force-one-retry produces a "Full retry-loop" row in the markdown
# ---------------------------------------------------------------------------


def test_force_one_retry_renders_full_retry_loop_row():
    """When ``--force-one-retry`` is on, the rendered markdown must
    contain a second body row labelled 'Full retry-loop (1 corrective)'.
    Exercises ``render_markdown`` directly with hand-crafted samples to
    avoid driving the live LLM path."""
    from scripts.measure_e4b_replan_latency import render_markdown
    md = render_markdown(
        single_attempt_ms=[100.0, 200.0, 300.0],
        retry_loop_ms=[500.0, 600.0, 700.0],
    )
    assert "Full retry-loop (1 corrective)" in md, f"missing retry-loop row in:\n{md}"
    # Without --force-one-retry the second row must NOT appear.
    md_single_only = render_markdown(
        single_attempt_ms=[100.0, 200.0, 300.0],
        retry_loop_ms=None,
    )
    assert "Full retry-loop" not in md_single_only, (
        f"single-only run should not render retry-loop row:\n{md_single_only}"
    )


# ---------------------------------------------------------------------------
# 4. Markdown snippet shape
# ---------------------------------------------------------------------------


def test_markdown_snippet_has_canonical_shape():
    """The snippet that gets appended to the plan must:
       - start with the '### Phase 3a measurement' header,
       - contain the canonical Metric / p50 (s) / p95 (s) / N column header,
       - contain a 'Single attempt' row,
       - have a valid GFM separator line (|---|---|---|---|),
       - have no whitespace-only trailing lines (defensive against
         accidental ``\\n\\n`` runs in the plan when this is appended).
    """
    from scripts.measure_e4b_replan_latency import render_markdown
    md = render_markdown(
        single_attempt_ms=[100.0, 200.0, 300.0, 400.0, 500.0,
                           600.0, 700.0, 800.0, 900.0, 1000.0],
        retry_loop_ms=[1100.0, 1200.0, 1300.0, 1400.0, 1500.0,
                       1600.0, 1700.0, 1800.0, 1900.0, 2000.0],
    )

    assert md.startswith("### Phase 3a measurement"), f"bad header: {md[:80]!r}"
    assert "| Metric" in md, "missing 'Metric' column header"
    assert "p50 (s)" in md, "missing 'p50 (s)' column header"
    assert "p95 (s)" in md, "missing 'p95 (s)' column header"
    assert "| Single attempt" in md, "missing 'Single attempt' row"

    # GFM separator: a line that contains only |, -, :, and whitespace,
    # with at least 4 cells. ``render_markdown`` emits exactly one.
    sep_re = re.compile(r"^\|[\s\-:|]+\|$")
    sep_lines = [ln for ln in md.splitlines() if sep_re.match(ln)]
    assert len(sep_lines) == 1, (
        f"expected exactly one GFM separator line; found {len(sep_lines)}:\n{md}"
    )

    # No whitespace-only TRAILING lines and no consecutive blank lines.
    # A single blank line between the header and the table is required
    # by GFM (a paragraph break), so we don't reject it — we just reject
    # ``\n\n\n`` runs that would create visual gaps when the snippet is
    # appended to the plan.
    stripped = md.rstrip("\n")
    assert "\n\n\n" not in stripped, (
        f"snippet contains a run of >=2 blank lines:\n{md!r}"
    )
    # The very last non-empty content line should be a table row.
    last_line = stripped.splitlines()[-1]
    assert last_line.startswith("|") and last_line.endswith("|"), (
        f"last content line is not a table row: {last_line!r}"
    )


def test_markdown_output_flag_writes_file(tmp_path):
    """``--output PATH`` must write the snippet to PATH and leave stdout
    quiet (other than the courtesy 'wrote markdown snippet' line on
    stderr). We exercise this via the in-process ``main`` because a
    full live run needs Ollama.
    """
    from scripts.measure_e4b_replan_latency import main

    out = tmp_path / "snippet.md"

    # Patch the async runner so we don't hit Ollama. Feed it a static
    # snippet so we only test the file-vs-stdout dispatch.
    from scripts import measure_e4b_replan_latency as mod

    async def fake_run(args):
        return "### Phase 3a measurement (fake)\n\n| Metric | p50 (s) | p95 (s) | N  |\n|---|---|---|---|\n| Single attempt | 1.00 | 1.00 | 1 |\n"

    with patch.object(mod, "_run_async", new=fake_run):
        rc = main(["--iterations", "1", "--output", str(out)])

    assert rc == 0
    assert out.exists(), "output file must be created"
    content = out.read_text()
    assert "### Phase 3a measurement (fake)" in content
    assert "| Single attempt |" in content
