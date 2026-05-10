"""PR1 regression guard: EGS subscribes to the gated `.delivered` channel.

After PR1 the EGS findings subscription must land on
`drones.*.findings.delivered`, not the raw `drones.*.findings`. If a future
refactor reverts the migration, this test fires before the silent-zero
diagnostic loop has any chance to.

Implementation note: we don't run the full `main()` (it spawns a publish
loop and a graph-tick loop). Instead we stub out everything past the
`pubsub.psubscribe(...)` calls and assert the recorded calls match the
expected channel. The `psubscribe` patches return immediately so the await
in `main` resolves without actually contacting Redis.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _StopMain(BaseException):
    """Sentinel exception to bail out of `main()` after we've recorded the
    psubscribe call but before the infinite event loop runs.

    Inherits from ``BaseException`` (not ``Exception``) so the broad
    ``except Exception`` clause inside ``main()``'s loop does not absorb
    it; we want this to propagate out of the function cleanly.
    """


@pytest.mark.asyncio
async def test_egs_main_psubscribes_to_findings_delivered():
    """Boot the EGS main() far enough to see its psubscribe calls, then bail.

    Asserts that one of the psubscribe calls landed on
    `drones.*.findings.delivered` and that NO call landed on the raw
    `drones.*.findings`. The list-form check guards against accidentally
    keeping both subscriptions during the migration.
    """
    psub_calls: list[str] = []

    fake_pubsub = MagicMock()

    async def _record_psub(*args, **kwargs):
        for a in args:
            psub_calls.append(a)

    async def _record_sub(*args, **kwargs):
        # We don't care about plain subscribes for this test; absorb them.
        return None

    fake_pubsub.psubscribe = AsyncMock(side_effect=_record_psub)
    fake_pubsub.subscribe = AsyncMock(side_effect=_record_sub)
    fake_pubsub.unsubscribe = AsyncMock(return_value=None)

    # The Wave 3a mesh-sim healthcheck calls get_message first (looking for
    # mesh.adjacency_matrix). Return a fake adjacency message on the FIRST
    # call so the healthcheck passes; on the next call (the main event loop)
    # raise to short-circuit and capture psubscribe state.
    call_state = {"n": 0}

    async def _get_message(*args, **kwargs):
        call_state["n"] += 1
        if call_state["n"] == 1:
            # Pretend mesh sim is alive.
            return {
                "type": "message",
                "channel": b"mesh.adjacency_matrix",
                "data": b"{}",
            }
        raise _StopMain()

    fake_pubsub.get_message = AsyncMock(side_effect=_get_message)

    fake_client = MagicMock()
    fake_client.pubsub = MagicMock(return_value=fake_pubsub)
    fake_client.publish = AsyncMock(return_value=0)

    with patch(
        "agents.egs_agent.main.redis.from_url", return_value=fake_client,
    ):
        # Avoid running the EGS coordinator graph and validation init —
        # we only care about the psubscribe call list.
        from agents.egs_agent import main as egs_main

        try:
            await egs_main.main()
        except _StopMain:
            pass

    assert "drones.*.findings.delivered" in psub_calls, (
        f"EGS did not psubscribe to the gated findings channel; "
        f"recorded calls={psub_calls}"
    )
    assert "drones.*.findings" not in psub_calls, (
        f"EGS still psubscribes to the raw findings channel; "
        f"recorded calls={psub_calls}. PR1 migration regressed."
    )
