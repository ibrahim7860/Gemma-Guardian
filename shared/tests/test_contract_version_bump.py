"""Iron-rule contract-version regression test (Phase 4, GATE 4 wow moment).

The plan §Phase 4 item 1: any change to the EGSStateMessage wire shape
*must* be a deliberate two-step author action — update the schema AND bump
shared/VERSION. This test enforces that by hashing both the Pydantic-derived
JSON schema and the checked-in JSON Schema for `egs_state`, comparing them
against a fixture file. Any drift fails CI loudly.

It also asserts the Pydantic model and the JSON Schema describe the SAME set
of top-level fields. That catches the specific failure mode "someone added a
field to the Pydantic model but forgot the JSON schema" — silent contract
drift that would only surface on the next prod schema-validation cycle.

How to refresh after a deliberate contract change:
  1. Update `shared/contracts/models.py::EGSStateMessage` and/or
     `shared/schemas/egs_state.json`.
  2. Run this file as a script:
         uv run python shared/tests/test_contract_version_bump.py --update-fixture
     It prints the new hashes and overwrites
     `shared/tests/fixtures/egs_state_schema_hash.txt`. ALSO bump
     `shared/VERSION` (semver) and regenerate
     `frontend/flutter_dashboard/lib/generated/contract_version.dart`.
  3. Re-run pytest. The drift test should now pass with the new hashes.

Skipping the fixture update is the IRON RULE violation this test exists to
catch — a contract change without a version bump.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, Tuple

import pytest

from shared.contracts import VERSION
from shared.contracts.models import EGSStateMessage


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_JSON_SCHEMA_PATH = _REPO_ROOT / "shared" / "schemas" / "egs_state.json"
_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "egs_state_schema_hash.txt"


# ---- hashing helpers -------------------------------------------------------


def _canonical_bytes(obj) -> bytes:
    """Deterministic JSON serialization for hashing.

    sort_keys + compact separators give a stable representation across
    Pydantic versions that may reorder keys in `model_json_schema()`.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pydantic_schema_hash() -> str:
    return hashlib.sha256(
        _canonical_bytes(EGSStateMessage.model_json_schema())
    ).hexdigest()


def _json_schema_hash() -> str:
    # Hash the *parsed* JSON (not the file bytes) so cosmetic reformat /
    # whitespace edits don't trip the test. A real shape change always
    # alters the parsed content.
    text = _JSON_SCHEMA_PATH.read_text(encoding="utf-8")
    return hashlib.sha256(_canonical_bytes(json.loads(text))).hexdigest()


def _read_fixture() -> Dict[str, str]:
    """Parse the simple `key=value` fixture file. Comment lines start with `#`."""
    out: Dict[str, str] = {}
    text = _FIXTURE_PATH.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _compute_fields() -> Tuple[set, set]:
    """Return (pydantic_top_level_props, json_top_level_props)."""
    pyd = set((EGSStateMessage.model_json_schema().get("properties") or {}).keys())
    js = set(
        (json.loads(_JSON_SCHEMA_PATH.read_text()).get("properties") or {}).keys()
    )
    return pyd, js


# ---- tests -----------------------------------------------------------------


def test_pydantic_schema_hash_matches_fixture():
    """Pydantic-derived schema for `EGSStateMessage` is unchanged since the
    last deliberate contract bump.

    Failure means someone changed the Pydantic model (added/removed/renamed
    a field, tightened a constraint, etc.) without re-baking the fixture
    AND bumping `shared/VERSION`. Fix path:
      * If the change is intentional: run this file with --update-fixture
        and bump shared/VERSION (and regenerate the Dart contract_version).
      * If unintentional: revert the model edit.
    """
    fix = _read_fixture()
    expected = fix.get("pydantic_egs_state_message_sha256", "")
    actual = _pydantic_schema_hash()
    assert actual == expected, (
        "EGSStateMessage Pydantic schema drifted from the checked-in fixture.\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}\n"
        "If the change is intentional, refresh the fixture via:\n"
        "    uv run python shared/tests/test_contract_version_bump.py --update-fixture\n"
        "and bump shared/VERSION (semver). See the module docstring."
    )


def test_json_schema_hash_matches_fixture():
    """`shared/schemas/egs_state.json` is unchanged since the last bump.

    Same iron-rule mechanism as the Pydantic test, just on the JSON Schema
    side. Either source-of-truth can move first, but both fixture lines
    must travel together with a VERSION bump.
    """
    fix = _read_fixture()
    expected = fix.get("json_egs_state_sha256", "")
    actual = _json_schema_hash()
    assert actual == expected, (
        "shared/schemas/egs_state.json drifted from the checked-in fixture.\n"
        f"  expected: {expected}\n"
        f"  actual:   {actual}\n"
        "If the change is intentional, refresh the fixture via:\n"
        "    uv run python shared/tests/test_contract_version_bump.py --update-fixture\n"
        "and bump shared/VERSION (semver). See the module docstring."
    )


def test_fixture_contract_version_matches_VERSION():
    """Fixture-pinned contract version equals the live `VERSION` constant.

    Belt-and-suspenders: if someone bumps `shared/VERSION` but forgets to
    re-bake the fixture, the schema-hash tests above would still pass
    (because no schema actually changed). This third assertion forces the
    fixture to advance in lockstep with `VERSION` — making it impossible
    for a release to ship under a stale fixture pin.
    """
    fix = _read_fixture()
    pinned = fix.get("contract_version", "")
    assert pinned == VERSION, (
        "Fixture's contract_version pin is out of sync with shared/VERSION.\n"
        f"  fixture pin: {pinned!r}\n"
        f"  VERSION:     {VERSION!r}\n"
        "Refresh via:\n"
        "    uv run python shared/tests/test_contract_version_bump.py --update-fixture\n"
    )


# Fields present in `shared/schemas/egs_state.json` but intentionally absent
# from the Pydantic mirror (and vice versa). This is pre-existing,
# well-documented drift — `base_image_*` is consumed only by the Flutter
# dashboard's map_panel renderer and was deliberately kept out of the
# Pydantic model because no Python-side consumer reads it. If you genuinely
# add a new asymmetric field, list it here with a one-line justification.
# Any *unlisted* drift fails the test below — which is the load-bearing
# regression guard.
_KNOWN_PYDANTIC_ONLY_FIELDS: set = set()
_KNOWN_JSON_ONLY_FIELDS: set = {
    # Flutter-side only: rendered as the static aerial background image.
    "base_image_path",
    # Flutter-side only: lat/lon bbox for the base image.
    "base_image_extents",
}


def test_pydantic_and_json_schema_share_top_level_fields():
    """Top-level property keys agree between Pydantic and JSON Schema.

    Catches the silent-drift case the plan calls out: someone adds a field
    to `EGSStateMessage` but forgets `shared/schemas/egs_state.json` (or
    vice versa). The two sources of truth must agree on which keys are
    part of the contract; constraints / types are covered by the existing
    schema-fixture tests.

    Pre-existing intentional asymmetry is captured in
    `_KNOWN_PYDANTIC_ONLY_FIELDS` / `_KNOWN_JSON_ONLY_FIELDS`. Anything not
    on those lists fails the test loudly — which is the regression guard.
    """
    pyd, js = _compute_fields()
    new_pydantic_only = (pyd - js) - _KNOWN_PYDANTIC_ONLY_FIELDS
    new_json_only = (js - pyd) - _KNOWN_JSON_ONLY_FIELDS
    assert not new_pydantic_only and not new_json_only, (
        "EGSStateMessage top-level fields diverged across the Pydantic model "
        "and the JSON Schema (and the drift is NOT on the documented "
        "intentional-asymmetry allow-list).\n"
        f"  in Pydantic but missing in JSON Schema (new drift): "
        f"{sorted(new_pydantic_only)}\n"
        f"  in JSON Schema but missing in Pydantic (new drift): "
        f"{sorted(new_json_only)}\n"
        "Add the field to the missing source AND refresh the fixture "
        "(uv run python shared/tests/test_contract_version_bump.py "
        "--update-fixture) AND bump shared/VERSION. If the asymmetry is "
        "intentional, add the field name to _KNOWN_* in this test with a "
        "justification comment."
    )


# ---- script entrypoint: refresh the fixture --------------------------------


def _write_fixture(pyd_hash: str, json_hash: str, version: str) -> None:
    body = f"""\
# EGSStateMessage contract-version regression fixture.
#
# Updated by ANY change to:
#   * shared/contracts/models.py::EGSStateMessage (and its sub-models reachable
#     via .model_json_schema())
#   * shared/schemas/egs_state.json
#
# When updating, ALSO bump shared/VERSION (semver) — the IRON RULE is that
# wire-shape changes ship with a contract-version bump so consumers
# (Flutter, EGS, drone agents) can refuse to run against incompatible peers.
#
# Format: two lines, each "name:hex_sha256".
#
# Regenerate via:
#   uv run python shared/tests/test_contract_version_bump.py --update-fixture
#
contract_version={version}
pydantic_egs_state_message_sha256={pyd_hash}
json_egs_state_sha256={json_hash}
"""
    _FIXTURE_PATH.write_text(body, encoding="utf-8")


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--update-fixture",
        action="store_true",
        help="Recompute hashes and overwrite the checked-in fixture file.",
    )
    args = parser.parse_args(argv)
    pyd = _pydantic_schema_hash()
    js = _json_schema_hash()
    print(f"contract_version (shared/VERSION): {VERSION}")
    print(f"pydantic_egs_state_message_sha256: {pyd}")
    print(f"json_egs_state_sha256:             {js}")
    if args.update_fixture:
        _write_fixture(pyd, js, VERSION)
        print(f"\nfixture refreshed: {_FIXTURE_PATH}")
    else:
        print("\n(pass --update-fixture to overwrite the checked-in fixture)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
