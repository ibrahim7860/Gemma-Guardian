"""Phase 3: operator_actions schema gates the egs.operator_actions Redis payload.

Discriminated by `kind` so future operator action types (recall, restrict_zone)
land on the same channel without breaking existing consumers.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.contracts import validate

FIXTURES = Path(__file__).parent.parent / "schemas" / "fixtures"


def _load(rel: str) -> dict:
    return json.loads((FIXTURES / rel).read_text())


def test_finding_approval_kind_validates():
    payload = _load("valid/operator_actions/01_finding_approval.json")
    outcome = validate("operator_actions", payload)
    assert outcome.valid, outcome.errors


def test_missing_command_id_rejected():
    payload = _load("invalid/operator_actions/01_missing_command_id.json")
    outcome = validate("operator_actions", payload)
    assert not outcome.valid
    assert outcome.errors


def test_unknown_kind_rejected():
    payload = _load("invalid/operator_actions/02_unknown_kind.json")
    outcome = validate("operator_actions", payload)
    assert not outcome.valid
    assert outcome.errors


def test_unknown_action_rejected():
    payload = {
        "kind": "finding_approval",
        "command_id": "abcd-1700000000000-1",
        "finding_id": "f_drone1_42",
        "action": "delete",  # not in enum
        "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
        "contract_version": "1.0.0",
    }
    outcome = validate("operator_actions", payload)
    assert not outcome.valid


def test_extra_field_rejected():
    payload = _load("valid/operator_actions/01_finding_approval.json")
    payload["extra"] = "nope"
    outcome = validate("operator_actions", payload)
    assert not outcome.valid


def test_bridge_timestamp_pattern_enforced():
    payload = _load("valid/operator_actions/01_finding_approval.json")
    payload["bridge_received_at_iso_ms"] = "2026-05-02 12:34:56"  # space, no Z
    outcome = validate("operator_actions", payload)
    assert not outcome.valid


def test_command_id_length_cap_enforced():
    """Reject 10MB command_ids that would blow Redis subscriber memory."""
    payload = _load("valid/operator_actions/01_finding_approval.json")
    payload["command_id"] = "x" * 1024  # 1KB > 128 char cap
    outcome = validate("operator_actions", payload)
    assert not outcome.valid
    assert outcome.errors


def test_command_id_charset_enforced():
    """Reject command_ids with shell metacharacters or whitespace."""
    payload = _load("valid/operator_actions/01_finding_approval.json")
    for bad in [
        "abcd; DROP TABLE users",
        "abcd 1700000000000 1",  # spaces
        "abcd\n1700000000000-1",  # newline
        "<script>alert(1)</script>",
        "abcd-${ms}-1",  # template literal leftover from a bug
    ]:
        payload["command_id"] = bad
        outcome = validate("operator_actions", payload)
        assert not outcome.valid, f"expected reject for {bad!r}"


def test_command_id_session_format_accepted():
    """The Flutter session-prefixed format must validate cleanly."""
    payload = _load("valid/operator_actions/01_finding_approval.json")
    payload["command_id"] = "v046-1777751008388-2"  # ${4chars}-${ms}-${counter}
    outcome = validate("operator_actions", payload)
    assert outcome.valid, outcome.errors


def test_dispatch_kind_validates():
    payload = _load("valid/operator_actions/02_operator_command_dispatch.json")
    outcome = validate("operator_actions", payload)
    assert outcome.valid, outcome.errors


def test_dispatch_missing_command_id_rejected():
    payload = _load("invalid/operator_actions/03_dispatch_missing_command_id.json")
    outcome = validate("operator_actions", payload)
    assert not outcome.valid
    assert outcome.errors


def test_dispatch_does_not_accept_finding_approval_only_fields():
    """A dispatch payload with finding_id+action must be rejected — those keys
    are additionalProperties:false on the dispatch branch."""
    payload = {
        "kind": "operator_command_dispatch",
        "command_id": "abcd-1700000000000-7",
        "finding_id": "f_drone1_42",
        "action": "approve",
        "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
        "contract_version": "1.0.0",
    }
    outcome = validate("operator_actions", payload)
    assert not outcome.valid
