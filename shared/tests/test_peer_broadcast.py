"""Contract 6 (peer_broadcast) discriminated-union round-trip."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.contracts import validate
from shared.contracts.models import PeerBroadcast

FIXTURES = Path(__file__).parent.parent / "schemas" / "fixtures"


def _load(p): return json.loads(p.read_text())


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "valid" / "peer_broadcast").glob("*.json")),
    ids=lambda p: p.name,
)
def test_valid(fixture):
    outcome = validate("peer_broadcast", _load(fixture))
    assert outcome.valid is True, outcome.errors


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "invalid" / "peer_broadcast").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid(fixture):
    outcome = validate("peer_broadcast", _load(fixture))
    assert outcome.valid is False
    assert outcome.errors, "rejected payload must report at least one error"


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "valid" / "peer_broadcast").glob("*.json")),
    ids=lambda p: p.name,
)
def test_pydantic_dispatcher(fixture):
    payload = _load(fixture)
    parsed = PeerBroadcast.parse_payload(payload)
    assert parsed is not None


def test_pydantic_rejects_unknown_broadcast_type():
    with pytest.raises(ValueError, match="unknown broadcast_type"):
        PeerBroadcast.parse_payload({"broadcast_type": "lunch_break", "payload": {}})
