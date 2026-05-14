import asyncio
import json
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.egs_agent.replanning import assign_survey_points
from agents.egs_agent.validation import EGSValidationNode


def _two_drone_two_point_state():
    """Minimal egs_state fixture: 2 active drones, 2 unassigned survey points."""
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

def test_assign_survey_points_success():
    async def run_test():
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "message": {
                "content": '{"function": "assign_survey_points", "arguments": {"assignments": [{"drone_id": "drone1", "survey_point_ids": ["sp_001"]}, {"drone_id": "drone2", "survey_point_ids": ["sp_002"]}]}}'
            }
        }
        
        mock_post = AsyncMock(return_value=mock_resp)
        
        with patch("httpx.AsyncClient.post", new=mock_post):
            validation_node = EGSValidationNode()
            egs_state = {
                "drones_summary": {"drone1": {"status": "active"}, "drone2": {"status": "active"}},
                "survey_points": [
                    {"id": "sp_001", "status": "unassigned"},
                    {"id": "sp_002", "status": "unassigned"}
                ]
            }
            res = await assign_survey_points(egs_state, validation_node)
            assert res["function"] == "assign_survey_points"
            assignments = res["arguments"]["assignments"]
            assert len(assignments) == 2
            
    asyncio.run(run_test())

def test_assign_survey_points_total_mismatch_fallback():
    async def run_test():
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "message": {
                "content": '{"function": "assign_survey_points", "arguments": {"assignments": [{"drone_id": "drone1", "survey_point_ids": ["sp_001"]}, {"drone_id": "drone2", "survey_point_ids": []}]}}'
            }
        }
        
        mock_post = AsyncMock(return_value=mock_resp)
        
        with patch("httpx.AsyncClient.post", new=mock_post):
            validation_node = EGSValidationNode()
            egs_state = {
                "drones_summary": {"drone1": {"status": "active"}, "drone2": {"status": "active"}},
                "survey_points": [
                    {"id": "sp_001", "status": "unassigned"},
                    {"id": "sp_002", "status": "unassigned"}
                ]
            }
            res = await assign_survey_points(egs_state, validation_node)

            assert res["function"] == "assign_survey_points"
            assignments = res["arguments"]["assignments"]
            assert assignments[0]["survey_point_ids"] == ["sp_001"]
            assert assignments[1]["survey_point_ids"] == ["sp_002"]

    asyncio.run(run_test())


# ---------------------------------------------------------------------------
# GH #32 / Bug 2 regression: transport errors must fall back, not propagate
# ---------------------------------------------------------------------------
#
# Pre-fix: `except Exception: raise e` at replanning.py:129-131 caught
# httpx errors and re-raised them, blocking the deterministic round-robin
# fallback (lines 133-144) from ever running. Combined with Bug 3's hung
# in-flight guard, this starved every drone_failure-triggered replan
# during the 240s resilience_v1 scenario. The fix: catch httpx.HTTPError /
# asyncio.TimeoutError / json.JSONDecodeError as retryable, fall through
# to the fallback after max_retries. Verbose errors still propagate so
# real bugs aren't silently swallowed.

@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("read timeout"),
        httpx.ConnectTimeout("connect timeout"),
        httpx.RemoteProtocolError("server disconnected"),
    ],
    ids=["connect_error", "read_timeout", "connect_timeout", "protocol_error"],
)
def test_assign_survey_points_falls_back_on_httpx_error(exc):
    """Every httpx error class we'd see in the wild must trigger the
    deterministic round-robin fallback, not raise.

    Pre-fix repro from GH #32: pointing CONFIG.inference.ollama_egs_endpoint
    at a closed port raised httpx.ConnectError. With this fix that returns
    the 2-drone × 2-point round-robin assignment instead.
    """
    async def run_test():
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=exc)):
            res = await assign_survey_points(_two_drone_two_point_state(), EGSValidationNode())

        # Fallback shape from replanning.py:139-144 — function name + a
        # round-robin assignment that covers every available point.
        assert res["function"] == "assign_survey_points"
        assignments = res["arguments"]["assignments"]
        assigned_drones = {a["drone_id"] for a in assignments}
        assert assigned_drones == {"drone1", "drone2"}, (
            f"both active drones should get a slot, got {assigned_drones}"
        )
        all_points = sorted(
            p for a in assignments for p in a["survey_point_ids"]
        )
        assert all_points == ["sp_001", "sp_002"], (
            f"every available point must be assigned exactly once, got {all_points}"
        )

    asyncio.run(run_test())


def test_assign_survey_points_falls_back_on_json_decode_error():
    """Malformed JSON from the LLM is retryable and falls back."""
    async def run_test():
        bad_resp = MagicMock()
        bad_resp.raise_for_status = MagicMock()
        bad_resp.json = MagicMock(side_effect=json.JSONDecodeError("nope", "", 0))
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=bad_resp)):
            res = await assign_survey_points(_two_drone_two_point_state(), EGSValidationNode())
        assert res["function"] == "assign_survey_points"
        assert len(res["arguments"]["assignments"]) == 2

    asyncio.run(run_test())


def test_assign_survey_points_unexpected_error_still_propagates():
    """Regression: don't swallow genuinely unexpected errors (e.g. attribute
    errors from a future refactor). They must surface to _replan_impl so
    they're logged, not silently masked by the fallback path.
    """
    async def run_test():
        with patch(
            "httpx.AsyncClient.post",
            new=AsyncMock(side_effect=RuntimeError("future refactor broke this")),
        ):
            with pytest.raises(RuntimeError, match="future refactor"):
                await assign_survey_points(
                    _two_drone_two_point_state(), EGSValidationNode()
                )

    asyncio.run(run_test())
