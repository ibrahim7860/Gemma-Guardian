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
