"""Positive unit tests for drain_until's AssertionError path.

drain_until's raise-on-miss behavior is load-bearing: every migrated
test file in this directory relies on it as the failure signal when
the bridge stops emitting expected echoes. Without a positive test,
a refactor that silently returns None on miss would make every
dependent test pass for the wrong reason.
"""
from __future__ import annotations

import json

import pytest

from frontend.ws_bridge.tests._helpers import drain_until


class _StubWS:
    """Tiny stand-in for an httpx-ws client. Yields a fixed list of
    JSON-encoded frames, one per receive_text call, then hangs.
    """

    def __init__(self, frames: list[dict]) -> None:
        self._frames = [json.dumps(f) for f in frames]
        self._idx = 0

    async def receive_text(self) -> str:
        if self._idx >= len(self._frames):
            # In real usage the WS would block; in the test we pad with
            # frames the predicate rejects so drain_until exhausts max_frames
            # rather than hanging.
            return json.dumps({"type": "noise"})
        out = self._frames[self._idx]
        self._idx += 1
        return out


@pytest.mark.asyncio
async def test_drain_until_returns_first_matching_frame():
    ws = _StubWS([{"type": "noise"}, {"type": "echo", "ok": True}])
    msg = await drain_until(ws, lambda m: m.get("type") == "echo", max_frames=5)
    assert msg == {"type": "echo", "ok": True}


@pytest.mark.asyncio
async def test_drain_until_raises_when_predicate_never_matches():
    ws = _StubWS([{"type": "noise"}])  # one noise frame; rest synthesised by stub
    with pytest.raises(AssertionError, match="no frame matched predicate after 3 frames"):
        await drain_until(ws, lambda m: m.get("type") == "never", max_frames=3)
