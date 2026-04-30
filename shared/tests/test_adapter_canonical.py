"""Adapter contract: Ollama tool_calls[] and structured-output content -> canonical form."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.contracts.adapters import AdapterError, normalize

FIXTURES = Path(__file__).parent.parent / "schemas" / "fixtures" / "valid"


def _layer1_fixtures():
    return sorted((FIXTURES / "drone_function_calls").glob("*.json"))


@pytest.mark.parametrize("fixture", _layer1_fixtures(), ids=lambda p: p.name)
def test_normalize_from_canonical_passthrough(fixture):
    canonical = json.loads(fixture.read_text())
    assert normalize(canonical, layer="drone") == canonical


@pytest.mark.parametrize("fixture", _layer1_fixtures(), ids=lambda p: p.name)
def test_normalize_from_ollama_tool_calls_shape(fixture):
    canonical = json.loads(fixture.read_text())
    ollama_response = {
        "message": {
            "tool_calls": [{"function": {"name": canonical["function"], "arguments": canonical["arguments"]}}]
        }
    }
    assert normalize(ollama_response, layer="drone") == canonical


@pytest.mark.parametrize("fixture", _layer1_fixtures(), ids=lambda p: p.name)
def test_normalize_from_structured_output_content(fixture):
    canonical = json.loads(fixture.read_text())
    response = {"message": {"content": json.dumps(canonical)}}
    assert normalize(response, layer="drone") == canonical


def test_normalize_rejects_multiple_tool_calls():
    response = {
        "message": {
            "tool_calls": [
                {"function": {"name": "continue_mission", "arguments": {}}},
                {"function": {"name": "continue_mission", "arguments": {}}},
            ]
        }
    }
    with pytest.raises(AdapterError, match="exactly one"):
        normalize(response, layer="drone")


def test_normalize_rejects_malformed_json_content():
    response = {"message": {"content": "{not valid json"}}
    with pytest.raises(AdapterError):
        normalize(response, layer="drone")


def test_normalize_layer3_uses_command_args_keys():
    canonical = {"command": "set_language", "args": {"lang_code": "en"}}
    response = {"message": {"content": json.dumps(canonical)}}
    assert normalize(response, layer="operator") == canonical


def test_normalize_rejects_non_dict_input():
    with pytest.raises(AdapterError):
        normalize("not a dict", layer="drone")  # type: ignore[arg-type]


def test_normalize_rejects_message_with_neither_tool_calls_nor_content():
    response = {"message": {"role": "assistant"}}
    with pytest.raises(AdapterError, match="neither"):
        normalize(response, layer="drone")
