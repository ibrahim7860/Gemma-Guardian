import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from agents.egs_agent.command_translator import translate_operator_command
from agents.egs_agent.validation import EGSValidationNode

def test_translate_operator_command_success():
    async def run_test():
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "message": {
                "content": '{"command": "restrict_zone", "args": {"zone_id": "zone_1"}}'
            }
        }
        
        mock_post = AsyncMock(return_value=mock_resp)
        
        with patch("httpx.AsyncClient.post", new=mock_post):
            validation_node = EGSValidationNode()
            egs_state = {"drones_summary": {"drone1": {"status": "active"}}}
            res = await translate_operator_command("focus on zone 1", "en", egs_state, validation_node)
            assert res["valid"] is True
            assert res["structured"]["command"] == "restrict_zone"
            assert res["structured"]["args"]["zone_id"] == "zone_1"
            
    asyncio.run(run_test())

def test_translate_operator_command_recall_inactive():
    async def run_test():
        mock_resp1 = MagicMock()
        mock_resp1.raise_for_status = MagicMock()
        mock_resp1.json.return_value = {
            "message": {
                "content": '{"command": "recall_drone", "args": {"drone_id": "drone2", "reason": "test"}}'
            }
        }
        
        mock_post = AsyncMock(side_effect=[mock_resp1, mock_resp1, mock_resp1, mock_resp1, mock_resp1])
        
        with patch("httpx.AsyncClient.post", new=mock_post):
            validation_node = EGSValidationNode()
            egs_state = {"drones_summary": {"drone2": {"status": "offline"}}}
            res = await translate_operator_command("bring back drone 2", "en", egs_state, validation_node)
            assert res["valid"] is False
            assert res["structured"]["command"] == "unknown_command"
            
    asyncio.run(run_test())
