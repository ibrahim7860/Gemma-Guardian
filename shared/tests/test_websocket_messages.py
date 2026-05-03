"""Contracts 7+8 (websocket_messages) discriminated-union round-trip."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.contracts import validate
from shared.contracts.models import WebSocketMessage

FIXTURES = Path(__file__).parent.parent / "schemas" / "fixtures"


def _load(p): return json.loads(p.read_text())


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "valid" / "websocket_messages").glob("*.json")),
    ids=lambda p: p.name,
)
def test_valid(fixture):
    outcome = validate("websocket_messages", _load(fixture))
    assert outcome.valid is True, outcome.errors


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "invalid" / "websocket_messages").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid(fixture):
    outcome = validate("websocket_messages", _load(fixture))
    assert outcome.valid is False
    assert outcome.errors


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "valid" / "websocket_messages").glob("*.json")),
    ids=lambda p: p.name,
)
def test_pydantic_dispatcher(fixture):
    payload = _load(fixture)
    parsed = WebSocketMessage.parse(payload)
    assert parsed.type == payload["type"]


def test_pydantic_rejects_unknown_type():
    with pytest.raises(ValueError, match="unknown WebSocket message type"):
        WebSocketMessage.parse({"type": "ping"})


def test_operator_command_command_id_charset_enforced():
    """Reject command_ids with shell metacharacters at the WS layer too."""
    payload = {
        "type": "operator_command",
        "command_id": "abcd; rm -rf /",
        "language": "en",
        "raw_text": "recall drone1",
        "contract_version": "1.0.0",
    }
    outcome = validate("websocket_messages", payload)
    assert not outcome.valid


def test_command_translation_command_id_charset_enforced():
    """Reject command_ids with shell metacharacters at the WS layer too."""
    payload = {
        "type": "command_translation",
        "command_id": "abcd; rm -rf /",
        "structured": {"command": "restrict_zone", "args": {"zone_id": "east"}},
        "valid": True,
        "preview_text": "preview",
        "preview_text_in_operator_language": "preview",
        "contract_version": "1.0.0",
    }
    outcome = validate("websocket_messages", payload)
    assert not outcome.valid


def test_operator_command_dispatch_command_id_charset_enforced():
    """Reject command_ids with shell metacharacters at the WS layer too."""
    payload = {
        "type": "operator_command_dispatch",
        "command_id": "abcd; rm -rf /",
        "contract_version": "1.0.0",
    }
    outcome = validate("websocket_messages", payload)
    assert not outcome.valid
