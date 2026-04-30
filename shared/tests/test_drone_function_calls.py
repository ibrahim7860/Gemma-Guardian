"""Layer-1 drone function-call schema round-trip."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.contracts import validate

FIXTURES = Path(__file__).parent.parent / "schemas" / "fixtures"


def _load(p: Path) -> dict:
    return json.loads(p.read_text())


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "valid" / "drone_function_calls").glob("*.json")),
    ids=lambda p: p.name,
)
def test_valid_fixture_passes(fixture):
    outcome = validate("drone_function_calls", _load(fixture))
    assert outcome.valid is True, outcome.errors


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "invalid" / "drone_function_calls").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid_fixture_rejected(fixture):
    outcome = validate("drone_function_calls", _load(fixture))
    assert outcome.valid is False
