"""Schema-conformance tests for `scripts/dev_fake_producers.py`.

The dev fake-producer is the stand-in publisher Ibrahim runs while Hazim
and Qasim are still building their real producers. If anything it emits drifts
out of contract spec, the bridge will silently drop messages and the
dashboard will look broken — so we pin its payload builders down here, with
no Redis required (pure functions in / pure functions out).

Coverage:
- `_build_drone_state` produces a contract-valid `drone_state` payload.
- `_build_egs_state` produces a contract-valid `egs_state` payload.
- `_build_finding` produces a contract-valid `finding` payload for every
  finding_type in the locked rotation enum.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from shared.contracts import validate

from scripts.dev_fake_producers import (
    _FINDING_TYPE_ROTATION,
    _build_drone_state,
    _build_egs_state,
    _build_finding,
)


_TEST_DRONE_ID: str = "drone99"


def test_drone_state_payload_validates() -> None:
    """`_build_drone_state` emits a payload accepted by the drone_state schema.

    Spot-check across a handful of ticks so battery decrement and
    survey-points-remaining drift don't push values out of allowed ranges.
    """
    for tick in (0, 1, 50, 200, 1000):
        payload: Dict[str, Any] = _build_drone_state(_TEST_DRONE_ID, tick)
        outcome = validate("drone_state", payload)
        assert outcome.valid, (
            f"drone_state invalid at tick={tick}: errors={outcome.errors}"
        )
        assert payload["drone_id"] == _TEST_DRONE_ID
        # Battery must stay in [0, 100] per the contract; the helper floors
        # at 5 so even very high tick counts remain valid.
        assert 0 <= payload["battery_pct"] <= 100


def test_egs_state_payload_validates() -> None:
    """`_build_egs_state` emits a payload accepted by the egs_state schema.

    Mission_id is pinned to `dev_mission` so the dashboard can recognize
    that it is consuming dev scaffolding rather than a real run.
    """
    payload: Dict[str, Any] = _build_egs_state(0)
    outcome = validate("egs_state", payload)
    assert outcome.valid, f"egs_state invalid: errors={outcome.errors}"
    assert payload["mission_id"] == "dev_mission"


def test_finding_payload_validates() -> None:
    """`_build_finding` emits a payload accepted by the finding schema.

    Walk the full type rotation (5 entries) plus one wrap-around to confirm
    every enum value validates and the modulo rotation behaves correctly.
    """
    seen_types = []
    for counter in range(len(_FINDING_TYPE_ROTATION) + 1):
        payload: Dict[str, Any] = _build_finding(_TEST_DRONE_ID, counter)
        outcome = validate("finding", payload)
        assert outcome.valid, (
            f"finding invalid at counter={counter}: errors={outcome.errors}"
        )
        assert payload["source_drone_id"] == _TEST_DRONE_ID
        assert payload["finding_id"] == f"f_{_TEST_DRONE_ID}_{counter}"
        seen_types.append(payload["type"])

    # All 5 enum values appear in the first 5 ticks, in order.
    assert seen_types[: len(_FINDING_TYPE_ROTATION)] == _FINDING_TYPE_ROTATION
    # Counter 5 wraps back to the first entry.
    assert seen_types[len(_FINDING_TYPE_ROTATION)] == _FINDING_TYPE_ROTATION[0]
