# httpx-ws 0.8+ Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop the `httpx-ws<0.8` upper-bound pin and the `transport.exit_stack = None` private-API workaround in `frontend/ws_bridge/tests/conftest.py` by moving `ASGIWebSocketTransport` construction out of the shared fixture and into per-test context managers.

**Architecture:** httpx-ws 0.8 made `ASGIWebSocketTransport.__aenter__`/`__aexit__` strict-same-task (anyio 4.x cancel-scope check). pytest-asyncio splits fixture setup/teardown into separate `runner.run()` invocations, so a transport entered in fixture-setup-task fails its `__aexit__` in fixture-teardown-task. Yesterday's PR #15 attempt to wrap the transport in lifecycle tasks failed CI on Python 3.11 + Linux for this reason. The fix is to give each test its own transport whose `async with` enters and exits in the test's own task. We add a helper context manager `make_test_client(app)` to `_helpers.py`, change `app_and_client` to yield `(app, fake_redis)` only, and update every test that uses `aconnect_ws` to wrap the call in `async with make_test_client(app) as http_client`. The fixture continues to manage `app.router.lifespan_context(app)` (FastAPI's lifespan is not strict-same-task and works fine across pytest-asyncio's split runners).

**Tech Stack:** pytest-asyncio (function-scoped loop), httpx, httpx-ws (≥0.8 target), anyio 4.x, FastAPI, fakeredis.aioredis.

---

## Background context

**Why this work exists:** Yesterday's PR #15 attempted to migrate from httpx-ws 0.7.x to 0.8.x. Three approaches were tried and all failed CI on Linux + Python 3.11:

1. Wrap transport-only in a background lifecycle task (commit `04e074d`)
2. Wrap transport AND lifespan_context in a background lifecycle task (commit `4b3e771`)
3. Drop the redundant `client.aclose()` inside the lifecycle (commit `bc36f8b`)

All three failed with `RuntimeError: Attempted to exit cancel scope in a different task` at fixture teardown. Local macOS + Python 3.12 was clean, masking the issue until CI surfaced it. The migration was reverted in commit `164ae9d` and the TODO at `TODOS.md:16-49` was reopened with the failure context.

**The root cause we are working around:** pytest-asyncio's session runner calls `runner.run(async_setup)` and `runner.run(async_teardown)` as two separate invocations. Each invocation is a fresh task. `ASGIWebSocketTransport` (httpx-ws 0.8) records `current_task()` on `__aenter__` and verifies it matches on `__aexit__`. They never match across pytest-asyncio's setup/teardown split.

**The fix:** Don't enter the transport's context manager from a fixture. Enter it from the test function's own task — which is one task across the entire test body. `__aenter__` and `__aexit__` then run in the same task, anyio is satisfied.

**Current state of the code (pre-migration):**
- `frontend/ws_bridge/tests/conftest.py` defines a single `app_and_client` fixture that yields `(app, http_client, fake_client)` and pokes `transport.exit_stack = None` at teardown to break a circular reference.
- 13 tests across 5 files use this fixture: `test_main_command_translation_forward.py` (2), `test_main_error_paths.py` (6), `test_main_finding_id_allowlist.py` (2), `test_main_operator_command_dispatch.py` (1), `test_main_operator_command_publish.py` (2).
- `pyproject.toml`'s `[project.optional-dependencies] dev` pins `httpx-ws>=0.7.0,<0.8` with a multi-line comment block explaining the workaround.
- `TODOS.md` has an entry titled "Migrate bridge tests off `httpx-ws` private API" at line 16, with the 2026-05-04 update note documenting yesterday's failures.

**Repository conventions you must follow:**
- Python deps managed by `uv`. Modify `pyproject.toml`, then run `uv lock` to refresh `uv.lock`. Do not create `requirements*.txt` files.
- Run tests with `uv run pytest ...` from repo root.
- Tests import via `frontend.ws_bridge.tests.*` package paths.
- `_helpers.py` is for plain functions imported explicitly. `conftest.py` is for fixtures. Keep that boundary.
- The bridge's runtime code (`frontend/ws_bridge/main.py`, `redis_subscriber.py`) does NOT change. This is a test-harness-only refactor.

**Decision gate convention:** Task 2 is a spike. If CI fails on the spike PR, STOP and report. Do not push on with the rest of the migration before the spike is green. The whole point of the spike-first structure is to de-risk before we touch 12 more test sites.

---

## File Structure

**Modified files:**
- `frontend/ws_bridge/tests/_helpers.py` — add `make_test_client` async context manager
- `frontend/ws_bridge/tests/conftest.py` — change `app_and_client` to yield `(app, fake)` only; drop `transport.exit_stack = None` workaround; drop `httpx` and `ASGIWebSocketTransport` imports (moved to `_helpers.py`)
- `frontend/ws_bridge/tests/test_main_operator_command_dispatch.py` — 1 test migrated (Task 2 spike)
- `frontend/ws_bridge/tests/test_main_command_translation_forward.py` — 2 tests migrated
- `frontend/ws_bridge/tests/test_main_finding_id_allowlist.py` — 2 tests migrated
- `frontend/ws_bridge/tests/test_main_operator_command_publish.py` — 2 tests migrated
- `frontend/ws_bridge/tests/test_main_error_paths.py` — 6 tests migrated
- `pyproject.toml` — drop `<0.8` upper bound and the anyio comment block
- `uv.lock` — regenerated by `uv lock`
- `TODOS.md` — close the migration TODO entry

**New files:** none.

**Untouched (intentionally):** `frontend/ws_bridge/main.py`, `frontend/ws_bridge/redis_subscriber.py`, all non-`test_main_*.py` test files. The fixture changes are scoped narrowly to keep the diff reviewable.

---

## Task 1: Add `make_test_client` helper and parallel fixture (no behavior change)

**Goal:** Land the new helper alongside the existing `app_and_client` fixture so we can migrate one test file at a time without breaking the rest. No tests change behavior in this task.

**Files:**
- Modify: `frontend/ws_bridge/tests/_helpers.py`
- Modify: `frontend/ws_bridge/tests/conftest.py`

- [ ] **Step 0: Create the feature branch BEFORE any commits**

From repo root, with a clean working tree on `main`:

```bash
git status                          # confirm clean
git checkout main && git pull       # confirm up to date
git checkout -b feat/httpx-ws-migration
```

All subsequent commits in this plan land on `feat/httpx-ws-migration`. Do NOT commit to `main` at any point.

- [ ] **Step 1: Add `make_test_client` to `_helpers.py`**

Open `frontend/ws_bridge/tests/_helpers.py` and replace the file content with:

```python
"""Shared async helpers for bridge WS tests.

These are NOT fixtures — they're plain functions imported explicitly by
the test files. Fixtures live in conftest.py; everything else lives here.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Dict

import httpx
from httpx_ws.transport import ASGIWebSocketTransport


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


@asynccontextmanager
async def make_test_client(app) -> AsyncIterator[httpx.AsyncClient]:
    """Construct an ``httpx.AsyncClient`` bound to an ``ASGIWebSocketTransport``
    against ``app``, scoped to a single test's task.

    Why this is a helper, not a fixture: ``httpx-ws`` 0.8+ enforces strict
    same-task entry/exit on the transport's ``async with`` (anyio 4.x cancel
    scope check). pytest-asyncio splits fixture setup and teardown across
    separate ``runner.run()`` invocations, so any transport entered in a
    fixture would fail at teardown. Used as a plain async context manager
    inside the test body, both ``__aenter__`` and ``__aexit__`` run in the
    test function's task and the check passes.
    """
    async with ASGIWebSocketTransport(app=app) as transport:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            yield client
```

- [ ] **Step 2: Add `app_and_redis` fixture in `conftest.py` alongside the existing `app_and_client`**

Open `frontend/ws_bridge/tests/conftest.py` and replace the file content with:

```python
"""Shared fixtures for bridge WS tests.

Discovered automatically by pytest — no import needed at call site.

Convention: every fixture here is function-scoped, monkeypatch-aware,
and pinned to the running pytest-asyncio loop. The pytest.ini setting
``asyncio_default_fixture_loop_scope = function`` is what makes
fakeredis bind to the same loop as the test.
"""
from __future__ import annotations

import fakeredis.aioredis as fakeredis_async
import httpx
import pytest_asyncio
from httpx_ws.transport import ASGIWebSocketTransport


@pytest_asyncio.fixture
async def fake_client():
    """A fakeredis client bound to the running pytest-asyncio loop.

    Used by every test that needs the bridge to talk to a Redis-compatible
    backend without spawning a real redis-server.
    """
    client = fakeredis_async.FakeRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def app_and_redis(monkeypatch, fake_client):
    """New-style fixture: yields ``(app, fake_redis)``. Each test constructs
    its own ``ASGIWebSocketTransport`` + ``httpx.AsyncClient`` via
    ``make_test_client(app)`` from ``_helpers.py``.

    Replaces ``app_and_client`` (kept temporarily for migration). See
    ``docs/superpowers/plans/2026-05-04-httpx-ws-migration.md`` for context.
    """
    import redis.asyncio as redis_async

    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )

    from frontend.ws_bridge.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app, fake_client


@pytest_asyncio.fixture
async def app_and_client(monkeypatch, fake_client):
    """LEGACY fixture: yields ``(app, http_client, fake_redis)``. Being
    migrated out — see ``docs/superpowers/plans/2026-05-04-httpx-ws-migration.md``
    and the corresponding TODOS.md entry.

    Teardown: ``transport.exit_stack = None`` is a documented workaround
    for the httpx-ws<0.8 transport's circular-reference at shutdown.
    """
    import redis.asyncio as redis_async

    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )

    from frontend.ws_bridge.main import create_app

    app = create_app()
    transport = ASGIWebSocketTransport(app=app)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    )
    async with app.router.lifespan_context(app):
        try:
            yield app, client, fake_client
        finally:
            transport.exit_stack = None
            await client.aclose()
```

- [ ] **Step 3: Run the existing test suite to verify nothing regressed**

Run from repo root:

```bash
uv run pytest frontend/ws_bridge/tests -v
```

Expected: all bridge tests pass (same baseline as `e19c89a`). The new `app_and_redis` fixture and `make_test_client` helper are unused at this point.

- [ ] **Step 4: Commit**

```bash
git add frontend/ws_bridge/tests/_helpers.py frontend/ws_bridge/tests/conftest.py
git commit -m "test(bridge): add make_test_client helper + app_and_redis fixture (parallel to legacy)"
```

---

## Task 2: SPIKE — migrate `test_main_operator_command_dispatch.py` and verify CI green

**Goal:** This is the de-risking checkpoint. Migrate the smallest test file (1 test) and verify CI passes on Python 3.11 + Linux before touching the other 4 files. **If CI fails, STOP and report. Do not proceed to Task 3.**

**Files:**
- Modify: `frontend/ws_bridge/tests/test_main_operator_command_dispatch.py`

- [ ] **Step 1: Read the current file**

```bash
cat frontend/ws_bridge/tests/test_main_operator_command_dispatch.py
```

Note the test signature: `async def test_dispatch_publishes_to_operator_actions(app_and_client)`, line ~45.

- [ ] **Step 2: Migrate the test**

Open `frontend/ws_bridge/tests/test_main_operator_command_dispatch.py`. Replace the existing test function (and only that — leave imports and helpers above it intact for now, except as noted in the import-update step below).

The test currently has shape:

```python
@pytest.mark.asyncio
async def test_dispatch_publishes_to_operator_actions(app_and_client):
    ...
    app, http_client, fake = app_and_client
    ...
    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        ...
```

Change to:

```python
@pytest.mark.asyncio
async def test_dispatch_publishes_to_operator_actions(app_and_redis):
    ...
    app, fake = app_and_redis
    ...
    async with make_test_client(app) as http_client:
        async with aconnect_ws("ws://testserver/", client=http_client) as ws:
            ...
```

The body of the test (Redis pubsub setup, frame send, assertions) does not change — only the fixture name, the unpack, and the new outer `async with make_test_client(app) as http_client:` wrapper around the existing `aconnect_ws` block.

- [ ] **Step 3: Update the file's imports**

At the top of `test_main_operator_command_dispatch.py`, add an import for `make_test_client` next to the existing `drain_until` import:

```python
from frontend.ws_bridge.tests._helpers import drain_until, make_test_client
```

(If the file does not currently import `drain_until`, add: `from frontend.ws_bridge.tests._helpers import make_test_client`.)

- [ ] **Step 4: Run the migrated test locally**

```bash
uv run pytest frontend/ws_bridge/tests/test_main_operator_command_dispatch.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit and push to a draft PR**

The feature branch already exists (created in Task 1 Step 0). Commit and push:

```bash
git add frontend/ws_bridge/tests/test_main_operator_command_dispatch.py
git commit -m "test(bridge): migrate test_main_operator_command_dispatch to make_test_client (spike)"
git push -u origin feat/httpx-ws-migration
gh pr create --draft --title "Bridge tests: migrate to httpx-ws 0.8 (spike)" --body "$(cat <<'EOF'
## Spike scope

Migrating ONE test file (`test_main_operator_command_dispatch.py`, 1 test) off the legacy `app_and_client` fixture onto the new `app_and_redis` fixture + `make_test_client` helper. Goal is to verify CI on Linux + Python 3.11 is green before migrating the other 4 files.

If this spike fails, the migration is reverted and the TODO at TODOS.md:16 stays open with new findings appended.

See `docs/superpowers/plans/2026-05-04-httpx-ws-migration.md` for full context.
EOF
)"
```

- [ ] **Step 6: DECISION GATE — verify CI on Linux + Python 3.11**

Wait for CI to complete on the draft PR. Watch `bridge_e2e` and any pytest jobs.

```bash
gh pr checks --watch
```

**Outcome A — all green:** Proceed to Task 3.

**Outcome B — failures:** STOP. Do NOT proceed. Report the failure to the requester with:
1. The full failing job log (`gh run view <run-id> --log-failed`)
2. The hypothesis revision (what changed about our understanding of the cross-task issue)
3. A recommendation: revert this branch and re-open the migration TODO with new context, OR try one more variation with explicit user approval

---

## Task 3: Migrate `test_main_command_translation_forward.py` (2 tests)

**Goal:** Mechanical migration of 2 tests. No new patterns — apply exactly the spike's transformation.

**Files:**
- Modify: `frontend/ws_bridge/tests/test_main_command_translation_forward.py`

- [ ] **Step 1: Update the imports at the top of the file**

Find the existing line `from frontend.ws_bridge.tests._helpers import drain_until` (around line 31). Change it to:

```python
from frontend.ws_bridge.tests._helpers import drain_until, make_test_client
```

- [ ] **Step 2: Migrate `test_command_translation_forwarded_to_ws_client` (around line 67)**

The current shape:

```python
@pytest.mark.asyncio
async def test_command_translation_forwarded_to_ws_client(app_and_client):
    """..."""
    app, http_client, fake = app_and_client
    ...
    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        # ... existing body unchanged ...
```

Change the function signature to take `app_and_redis`, change the unpack to `app, fake = app_and_redis`, and wrap the existing `async with aconnect_ws(...)` in an outer `async with make_test_client(app) as http_client:`. Result:

```python
@pytest.mark.asyncio
async def test_command_translation_forwarded_to_ws_client(app_and_redis):
    """..."""
    app, fake = app_and_redis
    ...
    async with make_test_client(app) as http_client:
        async with aconnect_ws("ws://testserver/", client=http_client) as ws:
            # ... existing body unchanged ...
```

The body inside `aconnect_ws` (frame sends, asserts, Redis interactions) is untouched.

- [ ] **Step 3: Migrate `test_invalid_translation_is_dropped` (around line 104)**

Apply the same transformation: signature `app_and_client` → `app_and_redis`, unpack `app, http_client, fake` → `app, fake`, wrap `aconnect_ws` in `async with make_test_client(app) as http_client:`.

- [ ] **Step 4: Run this file's tests locally**

```bash
uv run pytest frontend/ws_bridge/tests/test_main_command_translation_forward.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/ws_bridge/tests/test_main_command_translation_forward.py
git commit -m "test(bridge): migrate test_main_command_translation_forward to make_test_client"
```

---

## Task 4: Migrate `test_main_finding_id_allowlist.py` (2 tests)

**Goal:** Mechanical migration of 2 tests.

**Files:**
- Modify: `frontend/ws_bridge/tests/test_main_finding_id_allowlist.py`

- [ ] **Step 1: Update the imports**

If the file already imports from `_helpers` (currently it imports `drain_until`), append `make_test_client` to that import. Otherwise add a new line:

```python
from frontend.ws_bridge.tests._helpers import drain_until, make_test_client
```

- [ ] **Step 2: Migrate `test_unknown_finding_id_is_dropped_with_echo` (around line 65)**

Current signature: `async def test_unknown_finding_id_is_dropped_with_echo(app_and_client, ...)`. The test body has shape:

```python
app, http_client, fake = app_and_client
...
try:
    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        ...
```

Change to:

```python
app, fake = app_and_redis
...
try:
    async with make_test_client(app) as http_client:
        async with aconnect_ws("ws://testserver/", client=http_client) as ws:
            ...
```

Update the function parameter to `app_and_redis`. Preserve the existing `try/finally` block — the new `make_test_client` `async with` lives inside the `try`, alongside the existing `aconnect_ws` (now nested one level deeper).

- [ ] **Step 3: Migrate `test_known_finding_id_publishes_normally` (around line 105)**

Apply the same transformation.

- [ ] **Step 4: Run this file's tests**

```bash
uv run pytest frontend/ws_bridge/tests/test_main_finding_id_allowlist.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/ws_bridge/tests/test_main_finding_id_allowlist.py
git commit -m "test(bridge): migrate test_main_finding_id_allowlist to make_test_client"
```

---

## Task 5: Migrate `test_main_operator_command_publish.py` (2 tests)

**Goal:** Mechanical migration of 2 tests.

**Files:**
- Modify: `frontend/ws_bridge/tests/test_main_operator_command_publish.py`

- [ ] **Step 1: Update the imports**

Find the existing line `from frontend.ws_bridge.tests._helpers import drain_until` (around line 25). Change to:

```python
from frontend.ws_bridge.tests._helpers import drain_until, make_test_client
```

- [ ] **Step 2: Migrate `test_valid_operator_command_publishes_envelope` (around line 55)**

The test has a `try/finally` around `pubsub.aclose()`. Within the `try`, there's an `async with aconnect_ws(...)`. Apply the transformation:

- Change parameter `app_and_client` → `app_and_redis`
- Change `app, http_client, fake = app_and_client` → `app, fake = app_and_redis`
- Wrap the existing `async with aconnect_ws("ws://testserver/", client=http_client) as ws:` block with `async with make_test_client(app) as http_client:` (added one indentation level outside the `aconnect_ws`)

Result shape:

```python
async def test_valid_operator_command_publishes_envelope(app_and_redis):
    """..."""
    app, fake = app_and_redis

    pubsub = fake.pubsub()
    await pubsub.subscribe("egs.operator_commands")
    try:
        async with make_test_client(app) as http_client:
            async with aconnect_ws("ws://testserver/", client=http_client) as ws:
                await ws.receive_text()  # initial state envelope
                await ws.send_text(json.dumps(_command_frame()))
                ack = await drain_until(
                    ws, lambda m: m.get("ack") == "operator_command_received"
                )

        assert ack["type"] == "echo"
        # ... rest of assertions and post-aconnect_ws Redis polling unchanged ...
    finally:
        await pubsub.aclose()
```

The post-`aconnect_ws` assertions and the Redis polling block stay where they are. Only the `aconnect_ws` block gets a new outer `async with`.

- [ ] **Step 3: Migrate `test_invalid_operator_command_no_publish` (around line 104)**

Apply the same transformation.

- [ ] **Step 4: Run this file's tests**

```bash
uv run pytest frontend/ws_bridge/tests/test_main_operator_command_publish.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/ws_bridge/tests/test_main_operator_command_publish.py
git commit -m "test(bridge): migrate test_main_operator_command_publish to make_test_client"
```

---

## Task 6: Migrate `test_main_error_paths.py` (6 tests)

**Goal:** Mechanical migration of the largest test file. Same transformation, applied 6 times.

**Files:**
- Modify: `frontend/ws_bridge/tests/test_main_error_paths.py`

- [ ] **Step 1: Update the imports**

Find the existing line `from frontend.ws_bridge.tests._helpers import drain_until` (around line 30). Change to:

```python
from frontend.ws_bridge.tests._helpers import drain_until, make_test_client
```

- [ ] **Step 2: Migrate all 6 tests**

The 6 test signatures (lines from the current file):

1. `test_operator_command_redis_publish_failed_emits_echo(app_and_client, monkeypatch)` — line 76
2. `test_operator_command_bridge_internal_when_envelope_invalid(app_and_client, monkeypatch)` — line 111
3. `test_finding_approval_redis_publish_failed_emits_echo(app_and_client, monkeypatch)` — line 151
4. `test_finding_approval_bridge_internal_when_envelope_invalid(app_and_client, monkeypatch)` — line 183
5. `test_dispatch_redis_publish_failed_emits_echo(app_and_client, monkeypatch)` — line 218
6. `test_dispatch_bridge_internal_when_envelope_invalid(app_and_client, monkeypatch)` — line 246

For EACH of the 6 tests, apply the same transformation:

- Change parameter `app_and_client` → `app_and_redis` (preserve `monkeypatch` if present)
- Change `app, http_client, _fake = app_and_client` → `app, _fake = app_and_redis` (preserve the `_fake` underscore-prefix where used)
- Wrap the test's `async with aconnect_ws("ws://testserver/", client=http_client) as ws:` block in an outer `async with make_test_client(app) as http_client:`

Example transformation for test 1:

```python
@pytest.mark.asyncio
async def test_operator_command_redis_publish_failed_emits_echo(
    app_and_redis, monkeypatch
):
    """..."""
    app, _fake = app_and_redis

    async def _boom(*_a, **_kw):
        raise RuntimeError("redis is on fire")

    monkeypatch.setattr(app.state.publisher, "publish", _boom)

    frame = {
        # ... unchanged ...
    }

    async with make_test_client(app) as http_client:
        async with aconnect_ws("ws://testserver/", client=http_client) as ws:
            await ws.receive_text()
            await ws.send_text(json.dumps(frame))
            echo = await drain_until(
                ws, lambda m: m.get("error") == "redis_publish_failed"
            )

    assert echo["type"] == "echo"
    # ... rest of assertions unchanged ...
```

Read each test fully before editing. Where a test has additional `try/finally` or pubsub setup outside `aconnect_ws`, the new `async with make_test_client(app)` wraps ONLY the `aconnect_ws` block — assertions and pubsub teardown that already lived outside the `aconnect_ws` `with` block stay outside.

- [ ] **Step 3: Run the full file's tests**

```bash
uv run pytest frontend/ws_bridge/tests/test_main_error_paths.py -v
```

Expected: 6 PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/ws_bridge/tests/test_main_error_paths.py
git commit -m "test(bridge): migrate test_main_error_paths to make_test_client"
```

---

## Task 7: Remove the legacy `app_and_client` fixture and `transport.exit_stack` workaround

**Goal:** Now that all 13 tests use `app_and_redis` + `make_test_client`, the old fixture is dead code. Delete it and the private-API workaround.

**Files:**
- Modify: `frontend/ws_bridge/tests/conftest.py`

- [ ] **Step 1: Verify no remaining usages**

```bash
grep -rn "app_and_client" frontend/ws_bridge/tests/ --include="*.py"
```

Expected output: only the fixture definition in `conftest.py` (no test files should reference it). If any test file still references `app_and_client`, go back to the corresponding migration task and finish it before continuing.

- [ ] **Step 2: Replace `conftest.py` content**

Open `frontend/ws_bridge/tests/conftest.py` and replace the file with the cleaned-up version (removing the `app_and_client` fixture and dropping unused imports):

```python
"""Shared fixtures for bridge WS tests.

Discovered automatically by pytest — no import needed at call site.

Convention: every fixture here is function-scoped, monkeypatch-aware,
and pinned to the running pytest-asyncio loop. The pytest.ini setting
``asyncio_default_fixture_loop_scope = function`` is what makes
fakeredis bind to the same loop as the test.
"""
from __future__ import annotations

import fakeredis.aioredis as fakeredis_async
import pytest_asyncio


@pytest_asyncio.fixture
async def fake_client():
    """A fakeredis client bound to the running pytest-asyncio loop.

    Used by every test that needs the bridge to talk to a Redis-compatible
    backend without spawning a real redis-server.
    """
    client = fakeredis_async.FakeRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def app_and_redis(monkeypatch, fake_client):
    """Yields ``(app, fake_redis)`` with the bridge's lifespan active.

    Each test constructs its own ``ASGIWebSocketTransport`` +
    ``httpx.AsyncClient`` via ``make_test_client(app)`` from ``_helpers.py``.
    This avoids httpx-ws 0.8's strict same-task entry/exit check, which
    pytest-asyncio's split fixture setup/teardown otherwise violates.
    """
    import redis.asyncio as redis_async

    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )

    from frontend.ws_bridge.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        yield app, fake_client
```

This drops the `httpx`, `ASGIWebSocketTransport`, and `app_and_client` definitions entirely.

- [ ] **Step 3: Run the full bridge test suite**

```bash
uv run pytest frontend/ws_bridge/tests -v
```

Expected: all bridge tests pass (no regression vs Task 6).

- [ ] **Step 4: Commit**

```bash
git add frontend/ws_bridge/tests/conftest.py
git commit -m "test(bridge): drop legacy app_and_client fixture and transport.exit_stack workaround"
```

---

## Task 8: Drop the `<0.8` upper-bound pin on `httpx-ws`

**Goal:** With the workaround gone, the version pin is no longer needed. Drop it and refresh the lock.

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Update `pyproject.toml`**

Open `pyproject.toml`. The `dev` extra at lines 72-85 currently reads:

```toml
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-timeout>=2.3",
    "pytest-playwright>=0.5",
    # Upper-bound pin on httpx-ws: 0.8.0 introduced an API change to
    # ASGIWebSocketTransport that requires entering the transport as an
    # async context manager. That conflicts with pytest-asyncio's split
    # setup/teardown runs (anyio 4.x raises "different task" because the
    # transport's cancel scope is host-task-bound to the setup run). See
    # frontend/ws_bridge/tests/conftest.py for the pre-0.8 workaround
    # (transport.exit_stack = None) and TODOS.md for the migration TODO.
    "httpx-ws>=0.7.0,<0.8",
]
```

Replace the entire `dev = [ ... ]` block with:

```toml
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-timeout>=2.3",
    "pytest-playwright>=0.5",
    "httpx-ws>=0.8",
]
```

- [ ] **Step 2: Refresh the lock**

From repo root:

```bash
uv lock
```

This should resolve `httpx-ws` to the latest 0.8+ release and update `uv.lock`.

- [ ] **Step 3: Re-sync the dev environment**

```bash
uv sync --extra dev --extra ws_bridge
```

- [ ] **Step 4: Run the full bridge suite against the upgraded httpx-ws**

```bash
uv run pytest frontend/ws_bridge/tests -v
```

Expected: all PASS. If any test fails here, it's a real httpx-ws 0.8 API change we hadn't accounted for — investigate before continuing.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): drop httpx-ws<0.8 upper bound, bump to 0.8+"
```

---

## Task 9: Close the migration TODO

**Goal:** Update `TODOS.md` to remove the now-resolved migration entry.

**Files:**
- Modify: `TODOS.md`

- [ ] **Step 1: Delete the "Migrate bridge tests off `httpx-ws` private API" section**

Open `TODOS.md`. Delete the entire section starting at the heading `### Migrate bridge tests off \`httpx-ws\` private API (Phase 5+)` (around line 16) and ending just before the next `###` heading (around line 50, before `### EGS subscriber for \`egs.operator_actions\``).

This removes both the "Update 2026-05-04" attempt-and-revert note and the original TODO body — the migration is now done, the breadcrumb belongs in git history, not in `TODOS.md`.

- [ ] **Step 2: Verify the file still parses cleanly**

```bash
head -60 TODOS.md
```

Confirm the remaining TODO sections (`### Expand Playwright coverage`, `### EGS subscriber`, `### Static aerial base image`, `### Translate preview_text`) are intact and properly separated.

- [ ] **Step 3: Commit**

```bash
git add TODOS.md
git commit -m "docs(todos): close httpx-ws migration TODO (now shipped)"
```

---

## Task 10: Final CI verification and PR finalization

**Goal:** Push everything, watch CI go green, mark the PR ready for review.

- [ ] **Step 1: Push the branch**

```bash
git push
```

- [ ] **Step 2: Watch CI**

```bash
gh pr checks --watch
```

Expected: all jobs green, including the bridge_e2e Playwright job and any pytest jobs on Linux + Python 3.11.

If any job fails: investigate, fix, push, re-watch. Do NOT mark the PR ready for review with red CI.

- [ ] **Step 3: Mark the PR ready for review**

```bash
gh pr ready
```

- [ ] **Step 4: Update the PR body to reflect the final shipped state**

```bash
gh pr edit --body "$(cat <<'EOF'
## Summary

Migrates the bridge WS test harness off the legacy `httpx-ws<0.8` pinning + `transport.exit_stack = None` private-API workaround.

- **New helper:** `make_test_client(app)` in `frontend/ws_bridge/tests/_helpers.py` — async context manager that constructs the ASGI WS transport + httpx client inside the test's own task (avoiding pytest-asyncio's cross-task fixture split that broke yesterday's PR #15 attempt).
- **New fixture:** `app_and_redis` yielding `(app, fake_redis)` only. Lifespan_context still managed by the fixture (FastAPI lifespan is task-tolerant).
- **13 tests migrated** across 5 `test_main_*.py` files.
- **Legacy fixture removed:** `app_and_client` and the `transport.exit_stack = None` workaround are gone.
- **Pin dropped:** `httpx-ws>=0.8` (was `>=0.7.0,<0.8`).

## Why this approach worked when yesterday's didn't

Yesterday wrapped the transport in a background lifecycle task INSIDE the fixture. That doesn't help: pytest-asyncio's setup `runner.run()` and teardown `runner.run()` are still separate tasks regardless of which task the wrapper code runs in. This PR moves the transport's `async with` into the test function's own task, where `__aenter__` and `__aexit__` run in the same task by definition.

## Test plan

- [x] All bridge tests pass locally (`uv run pytest frontend/ws_bridge/tests -v`)
- [x] CI green on Linux + Python 3.11 (`bridge_e2e` Playwright job + pytest jobs)
- [x] `httpx-ws` resolved to latest 0.8+ release in `uv.lock`
- [x] `TODOS.md` migration entry closed

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: Report back to the requester**

Summarize:
- Final commit count and file count
- Total bridge test count after migration (should match pre-migration baseline)
- The httpx-ws version that landed (whatever `uv lock` resolved)
- Confirmation that the TODO is closed

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 1 issue, 0 critical gaps, scope accepted |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — ready to implement
