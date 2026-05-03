"""Shared async helpers for bridge WS tests.

These are NOT fixtures — they're plain functions imported explicitly by
the test files. Fixtures live in conftest.py; everything else lives here.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict


async def drain_until(
    ws,
    predicate: Callable[[Dict[str, Any]], bool],
    *,
    max_frames: int = 20,
) -> Dict[str, Any]:
    """Receive up to ``max_frames`` frames; return the first one matching
    ``predicate``. Raises ``AssertionError`` if no frame matches.

    The default ``max_frames=20`` was chosen as the ceiling that covered
    every existing call site (the previous per-file defaults ranged from
    10 to 30). Tests that need a different ceiling pass it explicitly.
    """
    for _ in range(max_frames):
        raw = await ws.receive_text()
        msg = json.loads(raw)
        if predicate(msg):
            return msg
    raise AssertionError(
        f"no frame matched predicate after {max_frames} frames"
    )
