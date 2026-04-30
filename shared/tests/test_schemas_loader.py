"""Smoke tests for the shared.contracts.schemas loader.

Asserts the loader can resolve `_common.json` $refs and that
validate() returns a structured outcome (not a raw exception).
"""
from __future__ import annotations

import pytest

from shared.contracts import schemas


def test_validate_accepts_known_common_iso_timestamp():
    outcome = schemas.validate("_common", {})  # _common has no top-level type, accepts {}
    assert outcome.valid is True


def test_validate_unknown_schema_raises_keyerror():
    with pytest.raises(KeyError, match="not_a_real_schema"):
        schemas.validate("not_a_real_schema", {})


def test_schema_returns_parsed_dict():
    common = schemas.schema("_common")
    assert isinstance(common, dict)
    assert "$defs" in common
    assert "iso_timestamp_utc_ms" in common["$defs"]


def test_all_schemas_includes_common():
    every = schemas.all_schemas()
    assert "_common" in every
