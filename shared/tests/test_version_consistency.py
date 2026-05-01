"""Version consistency: VERSION + config.yaml + contract_version.dart + every schema $id agree."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from shared.contracts import VERSION, all_schemas

ROOT = Path(__file__).parent.parent.parent
DART_VERSION = ROOT / "frontend" / "flutter_dashboard" / "lib" / "generated" / "contract_version.dart"


def _major(v: str) -> str:
    return v.split(".")[0]


def test_version_file_matches_config():
    cfg = yaml.safe_load((ROOT / "shared" / "config.yaml").read_text())
    assert cfg["contract_version"] == VERSION


def test_dart_contract_version_matches():
    assert DART_VERSION.exists(), f"dart contract_version file missing: {DART_VERSION}"
    text = DART_VERSION.read_text()
    m = re.search(r'contractVersion = "([^"]+)"', text)
    assert m, "contract_version.dart missing constant"
    assert m.group(1) == VERSION


def test_every_schema_id_carries_major_version():
    expected = f"/v{_major(VERSION)}/"
    for name, doc in all_schemas().items():
        assert "$id" in doc, f"{name}.json missing $id"
        assert expected in doc["$id"], f"{name}.json $id missing {expected}: {doc['$id']!r}"
