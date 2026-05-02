"""Shared $def coverage for _common.json."""
from __future__ import annotations

import pytest

from shared.contracts import validate


def test_command_id_def_accepts_session_format():
    payload = {
        "kind": "finding_approval",
        "command_id": "abcd-1700000000000-1",
        "finding_id": "f_drone1_42",
        "action": "approve",
        "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
        "contract_version": "1.0.0",
    }
    outcome = validate("operator_actions", payload)
    assert outcome.valid, outcome.errors


def test_command_id_def_rejects_shell_metacharacters():
    payload = {
        "kind": "finding_approval",
        "command_id": "abcd; rm -rf /",
        "finding_id": "f_drone1_42",
        "action": "approve",
        "bridge_received_at_iso_ms": "2026-05-02T12:34:56.789Z",
        "contract_version": "1.0.0",
    }
    outcome = validate("operator_actions", payload)
    assert not outcome.valid
