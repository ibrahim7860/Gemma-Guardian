import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from agents.egs_agent.command_translator import translate_operator_command
from agents.egs_agent.validation import EGSValidationNode

def test_translate_operator_command_success():
    async def run_test():
        mock_post = AsyncMock()
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.return_value = {
            "message": {
                "content": '{"command": "set_language", "args": {"lang_code": "en"}}'
            }
        }
        
        with patch("httpx.AsyncClient.post", new=mock_post):
            validation_node = EGSValidationNode()
            egs_state = {"drones_summary": {"drone1": {"status": "active"}}}
            res = await translate_operator_command("focus on zone 1", "en", egs_state, validation_node)
            assert res["valid"] is True
            assert res["structured"]["command"] == "set_language"
            assert res["structured"]["args"]["lang_code"] == "en"
            
    asyncio.run(run_test())

def test_translate_operator_command_recall_inactive():
    async def run_test():
        mock_post = AsyncMock()
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json.side_effect = [
            {
                "message": {
                    "content": '{"command": "recall_drone", "args": {"drone_id": "drone2", "reason": "test"}}'
                }
            },
            {
                "message": {
                    "content": '{"command": "recall_drone", "args": {"drone_id": "drone2", "reason": "test"}}'
                }
            },
            {
                "message": {
                    "content": '{"command": "recall_drone", "args": {"drone_id": "drone2", "reason": "test"}}'
                }
            },
            {
                "message": {
                    "content": '{"command": "recall_drone", "args": {"drone_id": "drone2", "reason": "test"}}'
                }
            }
        ]
        
        with patch("httpx.AsyncClient.post", new=mock_post):
            validation_node = EGSValidationNode()
            egs_state = {"drones_summary": {"drone2": {"status": "offline"}}}
            res = await translate_operator_command("bring back drone 2", "en", egs_state, validation_node)
            assert res["valid"] is False
            assert res["structured"]["command"] == "unknown_command"
            
    asyncio.run(run_test())
