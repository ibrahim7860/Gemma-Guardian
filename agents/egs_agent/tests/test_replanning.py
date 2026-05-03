import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.egs_agent.replanning import assign_survey_points
from agents.egs_agent.validation import EGSValidationNode

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
