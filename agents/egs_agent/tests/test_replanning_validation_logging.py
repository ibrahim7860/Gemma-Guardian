"""Validation-event logging + ReplanAttempt sink wiring on the EGS replan
loop (Phase 1, GATE 4 wow moment).

Five cases per the plan:
 1. 3-attempt run, success on attempt 3: exactly 3 in_progress + 1
    corrected_after_retry JSONL lines, all agent_id=egs / layer=egs /
    function_or_command=assign_survey_points.
 2. 1-attempt run, success first try: 1 line, outcome=success_first_try,
    attempt=1, valid=True.
 3. Max retries exceeded → fallback: terminal line is failed_after_retries
    and the deterministic round-robin still returns a valid assignment.
 4. raw_call field populated on every in_progress line.
 5. corrective_text comes from RULE_REGISTRY[rule_id].corrective_template —
    literal string "Your assignments cover 27 points but 25 are available"
    must land on ReplanAttempt.corrective_text when a 25-point input
    receives a 27-point assignment.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.egs_agent.replanning import assign_survey_points
from agents.egs_agent.validation import EGSValidationNode
from shared.contracts.logging import ValidationEventLogger


def _resp(content_dict: Dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"message": {"content": json.dumps(content_dict)}}
    return resp


def _twentyfive_point_state() -> Dict[str, Any]:
    """3 active drones, 25 unassigned survey points sp_001..sp_025."""
    return {
        "drones_summary": {
            "drone1": {"status": "active"},
            "drone2": {"status": "active"},
            "drone3": {"status": "active"},
        },
        "survey_points": [
            {"id": f"sp_{i:03d}", "status": "unassigned"} for i in range(1, 26)
        ],
    }


def _two_point_state() -> Dict[str, Any]:
    return {
        "drones_summary": {
            "drone1": {"status": "active"},
            "drone2": {"status": "active"},
        },
        "survey_points": [
            {"id": "sp_001", "status": "unassigned"},
            {"id": "sp_002", "status": "unassigned"},
        ],
    }


def _valid_2pt_assignment() -> Dict[str, Any]:
    return {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": "drone1", "survey_point_ids": ["sp_001"]},
                {"drone_id": "drone2", "survey_point_ids": ["sp_002"]},
            ],
        },
    }


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _make_logger(tmp_path: Path, monkeypatch) -> ValidationEventLogger:
    """Per GG_LOG_DIR env-var contract in shared/contracts/logging.py."""
    monkeypatch.setenv("GG_LOG_DIR", str(tmp_path))
    log_path = tmp_path / "validation_events.jsonl"
    return ValidationEventLogger(path=log_path)


# ---------- Test 1: 3-attempt run, success on attempt 3 ---------------------


def test_three_attempt_run_success_on_third(tmp_path, monkeypatch):
    """Two failed attempts (drone missing, then duplicate), one success."""
    sink_records: List[Dict[str, Any]] = []
    vlog = _make_logger(tmp_path, monkeypatch)

    # Attempt 1: missing drone2
    bad1 = {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": "drone1", "survey_point_ids": ["sp_001", "sp_002"]},
            ],
        },
    }
    # Attempt 2: duplicate point
    bad2 = {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": "drone1", "survey_point_ids": ["sp_001"]},
                {"drone_id": "drone2", "survey_point_ids": ["sp_001"]},
            ],
        },
    }
    good = _valid_2pt_assignment()

    responses = [_resp(bad1), _resp(bad2), _resp(good)]
    mock_post = AsyncMock(side_effect=responses)

    with patch("httpx.AsyncClient.post", new=mock_post):
        result = asyncio.run(assign_survey_points(
            _two_point_state(),
            EGSValidationNode(),
            validation_logger=vlog,
            log_sink=sink_records.append,
        ))

    assert result == good

    records = _read_jsonl(tmp_path / "validation_events.jsonl")
    in_progress = [r for r in records if r["outcome"] == "in_progress"]
    terminal = [r for r in records if r["outcome"] != "in_progress"]
    assert len(in_progress) == 2, f"expected 2 in_progress lines (the two failures), got {len(in_progress)}"
    assert len(terminal) == 1
    assert terminal[0]["outcome"] == "corrected_after_retry"
    assert terminal[0]["attempt"] == 3
    assert terminal[0]["valid"] is True

    for r in records:
        assert r["agent_id"] == "egs"
        assert r["layer"] == "egs"
        assert r["function_or_command"] == "assign_survey_points"

    # Sink got 3 entries (2 failures + 1 final success).
    assert len(sink_records) == 3
    assert [s["attempt_n"] for s in sink_records] == [1, 2, 3]
    assert [s["valid"] for s in sink_records] == [False, False, True]


# ---------- Test 2: 1-attempt run, success first try -----------------------


def test_success_first_try(tmp_path, monkeypatch):
    sink_records: List[Dict[str, Any]] = []
    vlog = _make_logger(tmp_path, monkeypatch)

    mock_post = AsyncMock(return_value=_resp(_valid_2pt_assignment()))
    with patch("httpx.AsyncClient.post", new=mock_post):
        result = asyncio.run(assign_survey_points(
            _two_point_state(),
            EGSValidationNode(),
            validation_logger=vlog,
            log_sink=sink_records.append,
        ))

    records = _read_jsonl(tmp_path / "validation_events.jsonl")
    assert len(records) == 1
    r = records[0]
    assert r["outcome"] == "success_first_try"
    assert r["attempt"] == 1
    assert r["valid"] is True
    assert r["rule_id"] is None
    assert r["agent_id"] == "egs"

    assert len(sink_records) == 1
    assert sink_records[0]["attempt_n"] == 1
    assert sink_records[0]["valid"] is True
    assert sink_records[0]["rule_id"] is None


# ---------- Test 3: max retries exceeded → fallback ------------------------


def test_failed_after_retries_falls_back(tmp_path, monkeypatch):
    """Every LLM response is a total-mismatch; the loop exhausts retries and
    the deterministic round-robin fallback still returns a valid assignment.
    """
    sink_records: List[Dict[str, Any]] = []
    vlog = _make_logger(tmp_path, monkeypatch)

    # Always wrong: assigns only 1 point of 2 available.
    bad = {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": "drone1", "survey_point_ids": ["sp_001"]},
                {"drone_id": "drone2", "survey_point_ids": []},
            ],
        },
    }

    mock_post = AsyncMock(return_value=_resp(bad))
    with patch("httpx.AsyncClient.post", new=mock_post):
        result = asyncio.run(assign_survey_points(
            _two_point_state(),
            EGSValidationNode(),
            validation_logger=vlog,
            log_sink=sink_records.append,
        ))

    # Deterministic fallback returns a valid assignment shape.
    assert result["function"] == "assign_survey_points"
    all_points = sorted(
        p for a in result["arguments"]["assignments"] for p in a["survey_point_ids"]
    )
    assert all_points == ["sp_001", "sp_002"]

    records = _read_jsonl(tmp_path / "validation_events.jsonl")
    terminal = [r for r in records if r["outcome"] != "in_progress"]
    assert len(terminal) == 1, f"expected exactly one terminal line, got {[r['outcome'] for r in records]}"
    assert terminal[0]["outcome"] == "failed_after_retries"


# ---------- Test 4: raw_call populated on every in_progress line -----------


def test_raw_call_populated_on_in_progress(tmp_path, monkeypatch):
    sink_records: List[Dict[str, Any]] = []
    vlog = _make_logger(tmp_path, monkeypatch)

    bad = {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": "drone1", "survey_point_ids": ["sp_001"]},
                {"drone_id": "drone2", "survey_point_ids": []},
            ],
        },
    }
    good = _valid_2pt_assignment()

    responses = [_resp(bad), _resp(good)]
    mock_post = AsyncMock(side_effect=responses)
    with patch("httpx.AsyncClient.post", new=mock_post):
        asyncio.run(assign_survey_points(
            _two_point_state(),
            EGSValidationNode(),
            validation_logger=vlog,
            log_sink=sink_records.append,
        ))

    records = _read_jsonl(tmp_path / "validation_events.jsonl")
    in_progress = [r for r in records if r["outcome"] == "in_progress"]
    assert in_progress, "must have at least one in_progress record"
    for r in in_progress:
        assert r["raw_call"] is not None, (
            "raw_call must reflect what the model emitted on each failed attempt — "
            f"got None on {r}"
        )
        assert r["raw_call"]["function"] == "assign_survey_points"


# ---------- Test 5: corrective_text from RULE_REGISTRY template -----------


def test_corrective_text_matches_rule_template_27_vs_25(tmp_path, monkeypatch):
    """Wow-moment literal: a 25-point input that gets a 27-point assignment
    must produce the corrective_text "Your assignments cover 27 points but
    25 are available" on the ReplanAttempt sink record. This is the exact
    string that lands in front of the camera.
    """
    sink_records: List[Dict[str, Any]] = []
    vlog = _make_logger(tmp_path, monkeypatch)

    # 25 available, 27 assigned (drone1 gets 9 unique + 2 phantom).
    overcount_ids = [f"sp_{i:03d}" for i in range(1, 10)] + ["sp_phantom_A", "sp_phantom_B"]
    overcount = {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": "drone1", "survey_point_ids": overcount_ids},
                {"drone_id": "drone2", "survey_point_ids": [f"sp_{i:03d}" for i in range(10, 18)]},
                {"drone_id": "drone3", "survey_point_ids": [f"sp_{i:03d}" for i in range(18, 26)]},
            ],
        },
    }
    good = {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": "drone1", "survey_point_ids": [f"sp_{i:03d}" for i in range(1, 10)]},
                {"drone_id": "drone2", "survey_point_ids": [f"sp_{i:03d}" for i in range(10, 18)]},
                {"drone_id": "drone3", "survey_point_ids": [f"sp_{i:03d}" for i in range(18, 26)]},
            ],
        },
    }

    responses = [_resp(overcount), _resp(good)]
    mock_post = AsyncMock(side_effect=responses)
    with patch("httpx.AsyncClient.post", new=mock_post):
        asyncio.run(assign_survey_points(
            _twentyfive_point_state(),
            EGSValidationNode(),
            validation_logger=vlog,
            log_sink=sink_records.append,
        ))

    # Find the failed attempt's sink record.
    fail = next(s for s in sink_records if s["valid"] is False)
    assert fail["rule_id"] == "ASSIGNMENT_TOTAL_MISMATCH"
    assert fail["corrective_text"] is not None
    assert "Your assignments cover 27 points but 25 are available" in fail["corrective_text"], (
        f"corrective_text must come verbatim from the rule template; got: {fail['corrective_text']!r}"
    )
