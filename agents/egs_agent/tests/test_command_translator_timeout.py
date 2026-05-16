"""Invariant test: command_translator does not regress to inline timeout literal.

Mirrors the spirit of the GH #32 fix on replanning.py — once we hoist a
timeout to a module constant, regression-test that future edits don't
sneak the literal back into the call site.
"""
import re
from pathlib import Path
import inspect

from agents.egs_agent import command_translator


def test_timeout_constant_is_180s():
    """Behavior preservation — the operator-command timeout must remain 180s."""
    assert command_translator.COMMAND_TRANSLATOR_HTTPX_PER_ATTEMPT_TIMEOUT_S == 180.0


def test_no_inline_timeout_literal_in_post_call():
    """DRY enforcement — `timeout=` keyword must reference the module constant,
    not an inline float literal. Catches accidental re-introduction.

    LIMIT: this regex catches the obvious inline-literal form
    (`client.post(..., timeout=180.0)`). It does NOT catch local-var indirection
    (`t = 180.0; client.post(..., timeout=t)`) or **kwargs unpacking
    (`kwargs = {"timeout": 180.0}; client.post(..., **kwargs)`). For a hackathon
    timebox this is the pragmatic level; an AST-based check would catch the
    rest but isn't worth the cost.
    """
    src = inspect.getsource(command_translator)
    # Find the client.post(... timeout=X ...) call inside translate_operator_command
    # and assert X is the constant name, not a number literal.
    pattern = re.compile(r"client\.post\([^)]*timeout=([A-Z_]+|[\d.]+)", re.DOTALL)
    matches = pattern.findall(src)
    assert matches, "expected to find a client.post(..., timeout=...) call"
    for m in matches:
        assert not re.match(r"^[\d.]+$", m), (
            f"client.post timeout uses inline literal {m!r}; "
            f"must reference COMMAND_TRANSLATOR_HTTPX_PER_ATTEMPT_TIMEOUT_S"
        )


def test_timeout_constant_passed_to_httpx_call(monkeypatch):
    """Integration smoke — when translate_operator_command runs, the httpx
    client gets the constant value as the timeout kwarg.
    """
    import httpx
    captured = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, timeout=None):
            captured["timeout"] = timeout
            # Force the loop to bail out cleanly via a fake error response.
            raise httpx.HTTPError("fake")

    monkeypatch.setattr(command_translator.httpx, "AsyncClient", lambda: FakeClient())

    # Minimal stubs for the rest of the call chain.
    class _Stub:
        max_retries = 0

        def validate_operator_command(self, *a, **k):
            class R:
                valid = False
                failure_reason = None
                detail = "stub"
            return R()

    # Run; we expect it to fail-out the retry loop and return unknown_command.
    # NOTE: command_translator re-raises non-AdapterError exceptions, so we
    # swallow the fake HTTPError here — the assertion is on captured["timeout"]
    # which is recorded BEFORE the raise inside FakeClient.post.
    import asyncio
    try:
        asyncio.run(
            command_translator.translate_operator_command(
                operator_text="test",
                language="en",
                egs_state={"drones_summary": {}},
                validation_node=_Stub(),
            )
        )
    except httpx.HTTPError:
        pass
    assert captured.get("timeout") == 180.0
