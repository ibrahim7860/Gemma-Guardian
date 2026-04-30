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


_EXPECTED_PATH_FRAGMENT = {
    "severity_out_of_range.json": "severity",
    "missing_visual_description.json": "visual_description",
    "coverage_pct_negative.json": "coverage_pct",
    "unknown_function.json": "function",
}


@pytest.mark.parametrize(
    "fixture",
    sorted((FIXTURES / "invalid" / "drone_function_calls").glob("*.json")),
    ids=lambda p: p.name,
)
def test_invalid_fixture_rejected(fixture):
    outcome = validate("drone_function_calls", _load(fixture))
    assert outcome.valid is False
    assert outcome.errors, "rejected payload must report at least one error"
    expected_fragment = _EXPECTED_PATH_FRAGMENT.get(fixture.name)
    if expected_fragment:
        joined_paths = " ".join(e.field_path for e in outcome.errors)
        joined_msgs = " ".join(e.message for e in outcome.errors)
        assert expected_fragment in joined_paths or expected_fragment in joined_msgs, (
            f"{fixture.name}: expected '{expected_fragment}' in field paths or messages, "
            f"got paths={[e.field_path for e in outcome.errors]}, "
            f"messages={[e.message for e in outcome.errors]}"
        )
