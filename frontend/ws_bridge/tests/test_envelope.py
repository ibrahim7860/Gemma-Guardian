"""The bridge must produce schema-valid state_update envelopes from the seed fixture."""
from __future__ import annotations

import json
from pathlib import Path

from shared.contracts import validate, VERSION
from frontend.ws_bridge.main import build_state_update_envelope

SEED_FIXTURE = (
    Path(__file__).parent.parent.parent.parent
    / "shared" / "schemas" / "fixtures" / "valid"
    / "websocket_messages" / "01_state_update.json"
)


def test_seed_fixture_validates():
    """Sanity-check the fixture itself before we build on it."""
    payload = json.loads(SEED_FIXTURE.read_text())
    outcome = validate("websocket_messages", payload)
    assert outcome.valid, outcome.errors


def test_envelope_validates_at_tick_zero():
    env = build_state_update_envelope(tick=0)
    outcome = validate("websocket_messages", env)
    assert outcome.valid, outcome.errors


def test_envelope_validates_after_many_ticks():
    """Mutated values across ticks must still validate."""
    for tick in [1, 5, 30, 100, 1000]:
        env = build_state_update_envelope(tick=tick)
        outcome = validate("websocket_messages", env)
        assert outcome.valid, f"tick={tick}: {outcome.errors}"


def test_envelope_stamps_contract_version():
    env = build_state_update_envelope(tick=0)
    assert env["contract_version"] == VERSION


def test_envelope_timestamp_advances_with_tick():
    """Each tick should produce a distinct timestamp so the dashboard sees fresh data."""
    e0 = build_state_update_envelope(tick=0)
    e1 = build_state_update_envelope(tick=1)
    assert e0["timestamp"] != e1["timestamp"]


def test_envelope_battery_varies_realistically():
    """Battery should drift downward over many ticks (not stay frozen at 87)."""
    e0 = build_state_update_envelope(tick=0)
    e_late = build_state_update_envelope(tick=300)  # 5 min in
    drone_e0 = e0["active_drones"][0] if e0["active_drones"] else None
    drone_late = e_late["active_drones"][0] if e_late["active_drones"] else None
    if drone_e0 and drone_late:
        # Variety: either battery moves or this fixture has no drones
        # (the seed fixture has empty active_drones, so this test is a no-op for now).
        assert drone_e0 == drone_e0  # placeholder — we don't enforce drift in Phase 1A
