"""Phase 4: bridge subscribes to ``egs.command_translations`` and forwards
each valid envelope to all WS clients as ``type=command_translation``.

The bridge-only fields (``kind``, ``egs_published_at_iso_ms``) MUST be
stripped before broadcasting. Schema-invalid envelopes are dropped at the
subscriber layer and never reach the WS.

Test harness convention (see plan section "Test harness convention for
Tasks 7-10"): uses ``httpx.AsyncClient`` + ``pytest_asyncio`` + ``httpx-ws``
instead of FastAPI's ``TestClient``. The TestClient pattern binds
``fakeredis.aioredis.FakeRedis()`` to one event loop while the test
publishes / awaits on another, which yields silent hangs or false-pass
results. Single-loop ownership (FastAPI app + WS transport + fakeredis
client all on the same pytest-asyncio loop) eliminates that class of bug.

Architecture note (adversarial finding #1, spec §5.1): the subscriber
enqueues onto an ``asyncio.Queue`` and a dedicated broadcaster task drains
it. We test only the observable behaviour (frame arrives / does not
arrive) — the queue is an implementation detail, but its presence keeps
the subscriber non-blocking under slow-client conditions.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

import pytest
from httpx_ws import aconnect_ws

from frontend.ws_bridge.tests._helpers import drain_until, make_test_client


# ---- helpers ---------------------------------------------------------------


def _valid_envelope() -> Dict[str, Any]:
    return {
        "kind": "command_translation",
        "command_id": "abcd-1700000000000-3",
        "structured": {
            "command": "recall_drone",
            "args": {"drone_id": "drone1", "reason": "operator request"},
        },
        "valid": True,
        "preview_text": "Will recall drone1: operator request",
        "preview_text_in_operator_language": "Will recall drone1: operator request",
        "egs_published_at_iso_ms": "2026-05-02T12:34:57.123Z",
        "contract_version": "1.0.0",
    }


def _invalid_envelope() -> Dict[str, Any]:
    """Missing required ``preview_text`` — must fail
    ``command_translations_envelope`` validation in the subscriber.
    """
    env = _valid_envelope()
    env["command_id"] = "abcd-1700000000000-9"
    del env["preview_text"]
    return env


# ---- tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_command_translation_forwarded_to_ws_client(app_and_redis):
    """A valid ``command_translations_envelope`` published on
    ``egs.command_translations`` is forwarded to the WS client as
    ``type=command_translation`` with bridge-only fields stripped.
    """
    app, fake = app_and_redis
    envelope = _valid_envelope()

    async with make_test_client(app) as http_client:
        async with aconnect_ws("ws://testserver/", client=http_client) as ws:
            await ws.receive_text()  # initial state envelope

            # Give the subscriber a tick to subscribe before publishing so the
            # message isn't published into the void.
            await asyncio.sleep(0.1)
            await fake.publish(
                "egs.command_translations", json.dumps(envelope)
            )

            forwarded = await drain_until(
                ws,
                lambda m: m.get("type") == "command_translation",
                max_frames=30,
            )

    assert forwarded is not None, "command_translation frame never arrived"
    assert forwarded["command_id"] == "abcd-1700000000000-3"
    # Bridge-only fields must NOT leak to the client.
    assert "kind" not in forwarded
    assert "egs_published_at_iso_ms" not in forwarded
    assert forwarded["structured"]["command"] == "recall_drone"
    assert forwarded["structured"]["args"]["drone_id"] == "drone1"
    assert forwarded["valid"] is True
    assert forwarded["preview_text"].startswith("Will recall")
    assert forwarded["contract_version"] == "1.0.0"


@pytest.mark.asyncio
async def test_invalid_translation_is_dropped(app_and_redis):
    """An envelope that fails ``command_translations_envelope`` validation
    must be dropped at the subscriber — not forwarded — and the subscriber
    task must keep running (the test would hang or error out otherwise).

    With the shared ``drain_until`` helper, "no matching frame" surfaces as
    an ``AssertionError`` from the helper itself, so this test asserts that
    the predicate never matches by expecting that error.
    """
    app, fake = app_and_redis
    bogus = _invalid_envelope()

    async with make_test_client(app) as http_client:
        async with aconnect_ws("ws://testserver/", client=http_client) as ws:
            await ws.receive_text()  # initial state envelope

            await asyncio.sleep(0.1)
            await fake.publish(
                "egs.command_translations", json.dumps(bogus)
            )

            # We should see only periodic state_update frames; never a
            # command_translation. drain_until raises AssertionError when no
            # frame matches within max_frames — that's the success condition.
            with pytest.raises(AssertionError):
                await drain_until(
                    ws,
                    lambda m: m.get("type") == "command_translation",
                    max_frames=10,
                )
