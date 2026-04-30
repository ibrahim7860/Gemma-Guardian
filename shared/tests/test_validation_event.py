"""Contract 11 (validation_event) schema round-trip."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.contracts import validate

FIXTURES = Path(__file__).parent.parent / "schemas" / "fixtures"


def _load(p): return json.loads(p.read_text())


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "valid" / "validation_event").glob("*.json")),
    ids=lambda p: p.name,
)
def test_valid(fixture):
    outcome = validate("validation_event", _load(fixture))
    assert outcome.valid is True, outcome.errors


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "invalid" / "validation_event").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid(fixture):
    outcome = validate("validation_event", _load(fixture))
    assert outcome.valid is False
    assert outcome.errors
