"""Direct $def coverage for _common.json.

These tests validate shared definitions in isolation rather than transitively
through a consumer schema. Phase 4 added `command_id` here; future shared
$defs land alongside.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

_COMMON_PATH = Path(__file__).parent.parent / "schemas" / "_common.json"
_COMMON = json.loads(_COMMON_PATH.read_text())
_COMMAND_ID_DEF = _COMMON["$defs"]["command_id"]


def test_command_id_def_accepts_session_format():
    jsonschema.validate("abcd-1700000000000-1", _COMMAND_ID_DEF)


def test_command_id_def_rejects_shell_metacharacters():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate("abcd; rm -rf /", _COMMAND_ID_DEF)


def test_command_id_def_rejects_empty_string():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate("", _COMMAND_ID_DEF)


def test_command_id_def_rejects_over_128_chars():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate("x" * 129, _COMMAND_ID_DEF)
