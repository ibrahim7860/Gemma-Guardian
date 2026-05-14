"""Phase 3c (GATE 4 wow moment fallback) — coverage for the one-shot
phantom-survey-point injection on `assign_survey_points`.

The injection exists so the camera capture for Beat 3c deterministically
shows ASSIGNMENT_TOTAL_MISMATCH on attempt 1 followed by a genuine LLM
recovery on attempt 2. The previous version of this test copy-pasted the
mutation block into the test body and asserted on a local variable — it
never called `assign_survey_points`, so deleting the production injection
would not have made it fail. This file fixes that: each test drives the
real retry loop with a mocked `httpx.AsyncClient.post`.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.egs_agent.replanning import assign_survey_points
from agents.egs_agent.validation import EGSValidationNode


def _resp(content_dict: Dict[str, Any]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"message": {"content": json.dumps(content_dict)}}
    return resp


def _twentyfive_point_state() -> Dict[str, Any]:
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


def _valid_25pt_assignment() -> Dict[str, Any]:
    """A clean round-robin assignment over sp_001..sp_025 across 3 drones."""
    buckets: Dict[str, List[str]] = {"drone1": [], "drone2": [], "drone3": []}
    drone_ids = ["drone1", "drone2", "drone3"]
    for i in range(1, 26):
        buckets[drone_ids[(i - 1) % 3]].append(f"sp_{i:03d}")
    return {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": [
                {"drone_id": d, "survey_point_ids": buckets[d]} for d in drone_ids
            ],
        },
    }


@pytest.mark.asyncio
async def test_inject_flag_off_no_mutation():
    """Flag off: a clean 25-point response from the LLM is accepted on attempt 1."""
    sink: List[Dict[str, Any]] = []
    mock_post = AsyncMock(return_value=_resp(_valid_25pt_assignment()))
    with patch("httpx.AsyncClient.post", new=mock_post):
        result = await assign_survey_points(
            _twentyfive_point_state(),
            EGSValidationNode(),
            log_sink=sink.append,
            inject_overcount_first_attempt=False,
        )

    assert mock_post.await_count == 1
    assert result.get("function") == "assign_survey_points"
    assert sink[-1]["valid"] is True
    assert sink[-1]["attempt_n"] == 1
    assert all(s.get("rule_id") != "ASSIGNMENT_TOTAL_MISMATCH" for s in sink)


@pytest.mark.asyncio
async def test_inject_flag_on_fires_mismatch_on_attempt_one():
    """Flag on, 25-point LLM response: injection makes it 27 → rule fires on attempt 1."""
    sink: List[Dict[str, Any]] = []
    mock_post = AsyncMock(return_value=_resp(_valid_25pt_assignment()))
    with patch("httpx.AsyncClient.post", new=mock_post):
        await assign_survey_points(
            _twentyfive_point_state(),
            EGSValidationNode(),
            log_sink=sink.append,
            inject_overcount_first_attempt=True,
        )

    attempt1 = next(s for s in sink if s["attempt_n"] == 1)
    assert attempt1["valid"] is False
    assert attempt1["rule_id"] == "ASSIGNMENT_TOTAL_MISMATCH"
    assert attempt1["details"] == {"assigned": 27, "total": 25}
    assert "27 points" in attempt1["corrective_text"]
    assert "25" in attempt1["corrective_text"]


@pytest.mark.asyncio
async def test_inject_flag_on_only_mutates_attempt_one_then_recovers():
    """End-to-end Beat 3c shape: attempt 1 injected → invalid; attempt 2 clean → valid."""
    sink: List[Dict[str, Any]] = []
    mock_post = AsyncMock(return_value=_resp(_valid_25pt_assignment()))
    with patch("httpx.AsyncClient.post", new=mock_post):
        result = await assign_survey_points(
            _twentyfive_point_state(),
            EGSValidationNode(),
            log_sink=sink.append,
            inject_overcount_first_attempt=True,
        )

    assert mock_post.await_count == 2
    assert result.get("function") == "assign_survey_points"
    attempt1 = next(s for s in sink if s["attempt_n"] == 1)
    attempt2 = next(s for s in sink if s["attempt_n"] == 2)
    assert attempt1["valid"] is False
    assert attempt1["rule_id"] == "ASSIGNMENT_TOTAL_MISMATCH"
    assert attempt2["valid"] is True
    assert attempt2["rule_id"] is None

    total = sum(
        len(a.get("survey_point_ids", []))
        for a in result["arguments"]["assignments"]
    )
    assert total == 25
    returned_ids = [
        pid
        for a in result["arguments"]["assignments"]
        for pid in a.get("survey_point_ids", [])
    ]
    assert "sp_phantom_1" not in returned_ids
    assert "sp_phantom_2" not in returned_ids


@pytest.mark.asyncio
async def test_inject_does_not_persist_across_calls():
    """A second call with the flag False must not see leftover injection state."""
    mock_post = AsyncMock(return_value=_resp(_valid_25pt_assignment()))
    with patch("httpx.AsyncClient.post", new=mock_post):
        await assign_survey_points(
            _twentyfive_point_state(),
            EGSValidationNode(),
            inject_overcount_first_attempt=True,
        )
        post_first_call_count = mock_post.await_count

        sink: List[Dict[str, Any]] = []
        await assign_survey_points(
            _twentyfive_point_state(),
            EGSValidationNode(),
            log_sink=sink.append,
            inject_overcount_first_attempt=False,
        )

    assert mock_post.await_count == post_first_call_count + 1
    assert sink[-1]["valid"] is True
    assert sink[-1]["attempt_n"] == 1
