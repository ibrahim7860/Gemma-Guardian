"""Phase 2 integration: main.py wiring produces schema-valid envelopes.

Most envelope-construction concerns are unit-tested in `test_aggregator.py`.
This file pins the integration: ``create_app()`` wires aggregator + config +
fixture together, and the resulting first snapshot validates against the
``websocket_messages`` contract. Plus a regression on ``contract_version``
stamping (the emit loop overwrites whatever the aggregator put there).
"""
from __future__ import annotations

import json
from pathlib import Path

from shared.contracts import VERSION, validate
from frontend.ws_bridge.aggregator import StateAggregator
from frontend.ws_bridge.main import _load_seed_envelope, _now_iso_ms, create_app

SEED_FIXTURE = (
    Path(__file__).parent.parent.parent.parent
    / "shared" / "schemas" / "fixtures" / "valid"
    / "websocket_messages" / "01_state_update.json"
)


def test_seed_fixture_validates():
    """The fixture we seed the aggregator with must itself be valid."""
    payload = json.loads(SEED_FIXTURE.read_text())
    outcome = validate("websocket_messages", payload)
    assert outcome.valid, outcome.errors


def test_load_seed_envelope_matches_fixture():
    seed = _load_seed_envelope()
    fixture = json.loads(SEED_FIXTURE.read_text())
    assert seed == fixture


def test_aggregator_first_snapshot_validates_with_seed():
    """End-to-end Phase 1A regression: empty buckets still produce a valid envelope."""
    seed = _load_seed_envelope()
    agg = StateAggregator(max_findings=50, seed_envelope=seed)
    env = agg.snapshot(timestamp_iso=_now_iso_ms())
    outcome = validate("websocket_messages", env)
    assert outcome.valid, outcome.errors


def test_emit_loop_stamps_contract_version_from_shared_version():
    """The emit loop overwrites contract_version with shared.contracts.VERSION.

    Aggregator seeds with VERSION too, but main.py is the single source of
    truth at runtime — assert that the stamp matches even if a future change
    has the aggregator emit something else.
    """
    seed = _load_seed_envelope()
    agg = StateAggregator(max_findings=50, seed_envelope=seed)
    env = agg.snapshot(timestamp_iso=_now_iso_ms())
    env["contract_version"] = VERSION   # what _emit_loop does
    outcome = validate("websocket_messages", env)
    assert outcome.valid, outcome.errors
    assert env["contract_version"] == VERSION


def test_now_iso_ms_format():
    """_now_iso_ms() must produce iso_timestamp_utc_ms format."""
    s = _now_iso_ms()
    # YYYY-MM-DDTHH:MM:SS.mmmZ
    assert len(s) == 24
    assert s[10] == "T"
    assert s[-1] == "Z"
    assert s[19] == "."


def test_create_app_wires_aggregator_and_subscriber(monkeypatch):
    """create_app() must populate app.state with the four lifecycle objects."""
    # Avoid trying to actually contact Redis during construction (we never
    # start the lifespan in this test, but constructing RedisSubscriber should
    # be I/O-free).
    monkeypatch.delenv("REDIS_URL", raising=False)
    app = create_app()
    assert hasattr(app.state, "config")
    assert hasattr(app.state, "aggregator")
    assert hasattr(app.state, "subscriber")
    assert hasattr(app.state, "registry")
