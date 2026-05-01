"""Pure unit tests for StateAggregator.

Covers the five cases from the Phase 2 design spec:
1. First update_egs_state replaces seed.
2. update_drone_state adds then updates the same drone in place.
3. Multi-drone: two distinct drone_ids both appear in snapshot.
4. add_finding append + dedup-by-finding_id (in-place replace) + cap eviction.
5. snapshot() on empty buckets is schema-valid (Phase 1A regression).

Plus: every embedded payload in the snapshot validates against its own schema.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import pytest

from shared.contracts import VERSION, validate

from frontend.ws_bridge.aggregator import StateAggregator


# ---- fixtures ---------------------------------------------------------------

_FIXTURES_ROOT = (
    Path(__file__).parent.parent.parent.parent
    / "shared" / "schemas" / "fixtures" / "valid"
)
_SEED_PATH = _FIXTURES_ROOT / "websocket_messages" / "01_state_update.json"
_DRONE_FIXTURE = _FIXTURES_ROOT / "drone_state" / "01_active.json"
_FINDING_FIXTURE = _FIXTURES_ROOT / "finding" / "01_victim.json"
_EGS_FIXTURE = _FIXTURES_ROOT / "egs_state" / "01_active.json"

# Stable timestamp used for snapshot() calls in tests; the aggregator stamps
# this onto the envelope and embedded egs_state. Real timestamps come from
# main.py at runtime.
_TS = "2026-05-15T14:23:11.342Z"


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


@pytest.fixture
def seed_envelope() -> Dict[str, Any]:
    return _load(_SEED_PATH)


@pytest.fixture
def egs_payload() -> Dict[str, Any]:
    return _load(_EGS_FIXTURE)


@pytest.fixture
def drone_payload() -> Dict[str, Any]:
    return _load(_DRONE_FIXTURE)


@pytest.fixture
def finding_payload() -> Dict[str, Any]:
    return _load(_FINDING_FIXTURE)


def _make(seed: Dict[str, Any], *, max_findings: int = 50) -> StateAggregator:
    return StateAggregator(max_findings=max_findings, seed_envelope=seed)


# ---- 1. update_egs_state replaces seed --------------------------------------

def test_update_egs_state_replaces_seed(seed_envelope, egs_payload):
    agg = _make(seed_envelope)
    # Before: snapshot uses seed's egs_state.
    snap0 = agg.snapshot(timestamp_iso=_TS)
    assert snap0["egs_state"]["mission_id"] == seed_envelope["egs_state"]["mission_id"]

    agg.update_egs_state(egs_payload)
    snap1 = agg.snapshot(timestamp_iso=_TS)
    assert snap1["egs_state"]["mission_id"] == egs_payload["mission_id"]
    # The egs_state in the snapshot validates against its own schema.
    outcome = validate("egs_state", snap1["egs_state"])
    assert outcome.valid, outcome.errors


# ---- 2. update_drone_state adds, then updates same drone in place -----------

def test_update_drone_state_adds_then_replaces(seed_envelope, drone_payload):
    agg = _make(seed_envelope)
    snap0 = agg.snapshot(timestamp_iso=_TS)
    assert snap0["active_drones"] == []

    agg.update_drone_state("drone1", drone_payload)
    snap1 = agg.snapshot(timestamp_iso=_TS)
    assert len(snap1["active_drones"]) == 1
    assert snap1["active_drones"][0]["drone_id"] == "drone1"
    assert snap1["active_drones"][0]["battery_pct"] == drone_payload["battery_pct"]

    updated = deepcopy(drone_payload)
    updated["battery_pct"] = 42
    agg.update_drone_state("drone1", updated)
    snap2 = agg.snapshot(timestamp_iso=_TS)
    assert len(snap2["active_drones"]) == 1  # in-place replace, not append
    assert snap2["active_drones"][0]["battery_pct"] == 42


# ---- 3. multi-drone: both ids surface --------------------------------------

def test_update_drone_state_multi_drone(seed_envelope, drone_payload):
    agg = _make(seed_envelope)
    d1 = deepcopy(drone_payload)
    d1["drone_id"] = "drone1"
    d2 = deepcopy(drone_payload)
    d2["drone_id"] = "drone2"

    agg.update_drone_state("drone1", d1)
    agg.update_drone_state("drone2", d2)
    snap = agg.snapshot(timestamp_iso=_TS)

    ids = {d["drone_id"] for d in snap["active_drones"]}
    assert ids == {"drone1", "drone2"}
    for entry in snap["active_drones"]:
        outcome = validate("drone_state", entry)
        assert outcome.valid, outcome.errors


# ---- 4. findings: append, dedup-replace, cap eviction -----------------------

def test_add_finding_append(seed_envelope, finding_payload):
    agg = _make(seed_envelope)
    agg.add_finding(finding_payload)
    snap = agg.snapshot(timestamp_iso=_TS)
    assert len(snap["active_findings"]) == 1
    assert snap["active_findings"][0]["finding_id"] == finding_payload["finding_id"]
    outcome = validate("finding", snap["active_findings"][0])
    assert outcome.valid, outcome.errors


def test_add_finding_duplicate_replaces_in_place_preserving_order(
    seed_envelope, finding_payload
):
    agg = _make(seed_envelope)
    f1 = deepcopy(finding_payload)
    f1["finding_id"] = "f_a"
    f2 = deepcopy(finding_payload)
    f2["finding_id"] = "f_b"
    f3 = deepcopy(finding_payload)
    f3["finding_id"] = "f_c"
    agg.add_finding(f1)
    agg.add_finding(f2)
    agg.add_finding(f3)
    snap = agg.snapshot(timestamp_iso=_TS)
    assert [f["finding_id"] for f in snap["active_findings"]] == ["f_a", "f_b", "f_c"]

    # Replace f_a in place — must not jump to the end.
    f1_v2 = deepcopy(finding_payload)
    f1_v2["finding_id"] = "f_a"
    f1_v2["severity"] = 5  # any value distinct from default
    agg.add_finding(f1_v2)

    snap2 = agg.snapshot(timestamp_iso=_TS)
    assert [f["finding_id"] for f in snap2["active_findings"]] == ["f_a", "f_b", "f_c"]
    assert snap2["active_findings"][0]["severity"] == 5


def test_add_finding_cap_evicts_oldest(seed_envelope, finding_payload):
    agg = _make(seed_envelope, max_findings=3)
    for i in range(3):
        f = deepcopy(finding_payload)
        f["finding_id"] = f"f_{i}"
        agg.add_finding(f)
    snap = agg.snapshot(timestamp_iso=_TS)
    assert [f["finding_id"] for f in snap["active_findings"]] == ["f_0", "f_1", "f_2"]

    # Insert a 4th — oldest (f_0) evicted.
    f3 = deepcopy(finding_payload)
    f3["finding_id"] = "f_3"
    agg.add_finding(f3)
    snap2 = agg.snapshot(timestamp_iso=_TS)
    assert [f["finding_id"] for f in snap2["active_findings"]] == ["f_1", "f_2", "f_3"]


# ---- 5. snapshot on empty buckets is schema-valid (Phase 1A regression) -----

def test_snapshot_empty_buckets_is_schema_valid(seed_envelope):
    agg = _make(seed_envelope)
    env = agg.snapshot(timestamp_iso=_TS)
    outcome = validate("websocket_messages", env)
    assert outcome.valid, outcome.errors
    assert env["type"] == "state_update"
    assert env["timestamp"] == _TS
    # Aggregator stamps a placeholder contract_version (main.py overwrites
    # with shared.contracts.VERSION at emit time).
    assert env["contract_version"] == VERSION
    assert env["active_drones"] == []
    assert env["active_findings"] == []
    # Embedded egs_state passes its own schema even when seeded.
    assert validate("egs_state", env["egs_state"]).valid


# ---- additional safety: deep-copy isolation --------------------------------

def test_aggregator_deep_copies_inputs(seed_envelope, drone_payload):
    """Caller mutating the input dict after passing it in must not leak."""
    agg = _make(seed_envelope)
    payload = deepcopy(drone_payload)
    agg.update_drone_state("drone1", payload)
    payload["battery_pct"] = 1  # mutate caller copy
    snap = agg.snapshot(timestamp_iso=_TS)
    assert snap["active_drones"][0]["battery_pct"] == drone_payload["battery_pct"]


def test_snapshot_returns_independent_copy(seed_envelope, drone_payload):
    """Mutating a returned snapshot must not corrupt internal state."""
    agg = _make(seed_envelope)
    agg.update_drone_state("drone1", drone_payload)
    snap = agg.snapshot(timestamp_iso=_TS)
    snap["active_drones"][0]["battery_pct"] = 0
    snap2 = agg.snapshot(timestamp_iso=_TS)
    assert snap2["active_drones"][0]["battery_pct"] == drone_payload["battery_pct"]


def test_snapshot_overrides_egs_timestamp(seed_envelope, egs_payload):
    """snapshot() must stamp timestamp_iso onto the embedded egs_state too."""
    agg = _make(seed_envelope)
    agg.update_egs_state(egs_payload)
    env = agg.snapshot(timestamp_iso=_TS)
    assert env["egs_state"]["timestamp"] == _TS


def test_aggregator_uses_ordereddict_internally(seed_envelope, finding_payload):
    """Spec says findings bucket is an OrderedDict — verify exposed attribute type."""
    agg = _make(seed_envelope)
    agg.add_finding(finding_payload)
    # Internal type guard: spec is explicit about OrderedDict semantics.
    assert isinstance(agg._findings, OrderedDict)  # type: ignore[attr-defined]
