# Bridge Asyncio Pollution Fix + `conftest.py` Extraction

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the documented full-suite asyncio pollution in `frontend/ws_bridge/tests/` so `pytest frontend/ws_bridge/tests/` runs green as a single invocation, and extract the duplicated `fake_client` / `app_and_client` fixtures plus the `_drain_until` helper into shared modules. Then collapse the CI per-file workaround into a single pytest invocation, and add a separate CI job that exercises the existing Playwright e2e tests.

**Architecture:** Two new shared modules under `frontend/ws_bridge/tests/`: `conftest.py` (pytest-discovered fixtures: `fake_client`, `app_and_client`) and `_helpers.py` (the plain `_drain_until` async helper, since it isn't a fixture). All five duplicated test files import from these instead of redefining. A repo-root `pytest.ini` update configures pytest-asyncio in `auto` mode with `asyncio_default_fixture_loop_scope = "function"` — the documented remedy for the loop-binding mismatch that fakeredis surfaces under pytest-asyncio strict mode (https://github.com/pytest-dev/pytest-asyncio/issues/660). CI gains a third job, `bridge_e2e`, that builds the Flutter web bundle, installs Playwright chromium, and runs the `@pytest.mark.e2e` Playwright tests against real `redis-server` + `uvicorn` + `http.server` subprocesses.

**Tech Stack:** `pytest`, `pytest-asyncio` (auto mode), `fakeredis`, `httpx`, `httpx-ws`, GitHub Actions (`subosito/flutter-action@v2`, `actions/setup-python@v5`), Playwright chromium.

---

## Why now

Phase 4 is on `main`. Day 5 is tomorrow (Mon May 5) but the next blocking-on-others work for Person 4 is Day 8 (May 8: multilingual command box — already shipped). That gives a real ~5-day window with no inbound dependencies. The CI per-file workaround is documented but ugly: every new bridge test file inherits the duplication tax (already bit us — `_drain_until.max_frames` defaults have drifted to {10, 10, 10, 20, 30} across five files). Person 3's EGS subscriber and Person 5's drone agent are about to start landing PRs against `main`; cleaning the test harness BEFORE that traffic hits is the right ordering.

The user explicitly asked for both unit-test verification AND Playwright coverage. Today CI exercises zero Playwright — `test_e2e_playwright.py` is `@pytest.mark.e2e` and excluded by `pytest.ini`. We have the test file, just no CI job. This plan adds it.

---

## Out of scope

- Touching the per-test-method `e2e` marker logic. Existing tests stay marked.
- Renaming or restructuring the existing test files (only their fixture/helper imports change).
- Cross-platform CI (macOS/Windows runners). Linux ubuntu-latest is sufficient — that's where the documented pollution actually reproduces; locally on macOS+py3.9 it doesn't manifest at all.
- Migrating off the private `httpx-ws` API (`transport.exit_stack`). That's a separate concern and the `<0.8` pin already covers it.
- Any change to `agents/`, `shared/`, or other test surfaces.
- The "Bridge lifespan teardown ordering" TODO and "ValidationEventLogger off dispatch path" TODO. Each gets its own PR.

---

## File Structure

**Create:**
- `frontend/ws_bridge/tests/conftest.py` (~60 lines) — `fake_client`, `app_and_client` fixtures
- `frontend/ws_bridge/tests/_helpers.py` (~25 lines) — `drain_until` async helper
- `frontend/ws_bridge/tests/test_helpers.py` (~20 lines) — positive unit tests for `drain_until`

**Modify:**
- `pytest.ini` — add `asyncio_mode = auto`, `asyncio_default_fixture_loop_scope = function`, and `timeout = 30` (eng-review issue 4A: hang protection)
- `frontend/ws_bridge/requirements-dev.txt` — add `pytest-timeout` (powers the `timeout = 30` setting above)
- `.github/workflows/test.yml` — collapse per-file loop to single pytest invocation in `bridge` job; add new `bridge_e2e` job
- `frontend/ws_bridge/tests/test_main_command_translation_forward.py` — drop local fixtures + helper, import from conftest/`_helpers`
- `frontend/ws_bridge/tests/test_main_finding_id_allowlist.py` — same
- `frontend/ws_bridge/tests/test_main_operator_command_dispatch.py` — same
- `frontend/ws_bridge/tests/test_main_operator_command_publish.py` — same
- `frontend/ws_bridge/tests/test_main_error_paths.py` — same (also drops `_IsoMsCounter` if it stays test-local; verdict in Task 4)
- `TODOS.md` — close the two relevant entries; reword if anything residual remains

**No changes to:** `frontend/ws_bridge/main.py`, `frontend/ws_bridge/redis_subscriber.py`, `redis_publisher.py`, `aggregator.py`, `config.py`, or any non-`test_main_*.py` test file (`test_aggregator.py`, `test_subscriber.py`, etc. don't use these fixtures).

---

## Testing Strategy

The user asked for both Playwright AND regular unit tests. This plan exercises both:

**Per-task verification (regular unit tests):** every migration task ends with `pytest -m "not e2e"` against the bridge tests, plus the specific files touched. The bar is "all 68 non-e2e tests pass in a single pytest invocation, on Linux+Python 3.11 in CI." Locally, my Python 3.9 setup happens not to manifest the pollution, so CI is the deterministic validator — every task that could affect the harness pushes a commit and waits for the green check before proceeding.

**E2E verification (Playwright):** Task 8 adds the new `bridge_e2e` CI job. It builds Flutter web, installs chromium, runs `pytest -m e2e`. The four existing tests in `test_e2e_playwright.py` (`test_dashboard_loads_and_connects`, `test_finding_appears_in_panel`, `test_captured_ws_frames_revalidate`, `test_drone_state_reflects_battery`) become the regression net for "the bridge still works through a real browser." If a future fixture refactor accidentally breaks the production code path, Playwright catches it. The unit tests catch the harness-level break.

**Why both matter:** unit tests use `httpx.AsyncClient + ASGIWebSocketTransport` — they exercise FastAPI's request/response lifecycle but not the actual `uvicorn` socket layer, real Redis pub/sub, or browser WebSocket negotiation. The Playwright job is the only thing that tests the `uvicorn → real redis-server → chromium WebSocket` path end-to-end. Without it, a CI green doesn't prove the dashboard actually receives frames in a browser.

---

## Task 1: Configure pytest-asyncio for stable loop binding (was Task 2; eng-review 1C dropped the diagnostic-baseline branch)

**Files:**
- Modify: `pytest.ini`
- Modify: `frontend/ws_bridge/requirements-dev.txt` (eng-review 4A: add `pytest-timeout`)

The fakeredis-aioredis client binds to `asyncio.get_running_loop()` at construction time. Under pytest-asyncio strict mode, fixtures and tests can end up on different loops if the fixture loop scope isn't pinned. `auto` mode + `function`-scoped fixture loop fixes both legs.

Eng-review 4A also lands here: `pytest-timeout` + `timeout = 30` in `pytest.ini` is a repo-wide safety net so a hanging `drain_until` (or any future bad-state await) fails fast with a traceback instead of hanging CI for hours. Same blast radius as the asyncio mode change, so it belongs in the same commit.

- [ ] **Step 1: Branch off and update `requirements-dev.txt`**

```bash
git checkout main
git pull
git checkout -b chore/bridge-test-harness-cleanup
```

Append to `frontend/ws_bridge/requirements-dev.txt`:
```
# Hang protection: pytest.ini sets timeout = 30 (eng-review 4A). Without
# this dep, the timeout setting is silently ignored.
pytest-timeout>=2.3
```

- [ ] **Step 2: Update `pytest.ini`**

Current contents:
```ini
[pytest]
markers =
    e2e: end-to-end tests that spawn real subprocesses (redis-server, uvicorn, http.server, chromium). Slow; excluded from quick runs via `-m "not e2e"`.
```

Change to:
```ini
[pytest]
markers =
    e2e: end-to-end tests that spawn real subprocesses (redis-server, uvicorn, http.server, chromium). Slow; excluded from quick runs via `-m "not e2e"`.
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
timeout = 30
```

The `timeout = 30` setting applies to every test repo-wide. The Playwright e2e tests (~10s each) fit comfortably under it. If any test legitimately needs more, override with `@pytest.mark.timeout(60)`.

- [ ] **Step 3: Install the new dep locally**

```bash
PYTHONPATH=. python3 -m pip install -r frontend/ws_bridge/requirements-dev.txt
```
Expected: pytest-timeout installs without conflict.

- [ ] **Step 4: Run bridge non-e2e tests to verify nothing broke from the config change**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/ -m "not e2e" -q
```
Expected: 68 passed. (If anything fails, the most likely cause is a fixture that was relying on strict-mode-only behavior — investigate before proceeding.)

- [ ] **Step 5: Verify the config change does NOT break other test directories (eng-review 2A)**

The `pytest.ini` change is repo-wide. Other test surfaces exist at `agents/drone_agent/tests/`, `agents/egs_agent/tests/`, `shared/tests/`, and `scripts/`. If `asyncio_mode = auto` or the timeout breaks Person 3's or Person 5's tests, we ship a regression onto main.

```bash
PYTHONPATH=. python3 -m pytest shared/ -q
PYTHONPATH=. python3 -m pytest agents/drone_agent/tests/ -q || echo "drone_agent has issues — check if pre-existing or new"
PYTHONPATH=. python3 -m pytest agents/egs_agent/tests/ -q || echo "egs_agent has issues — check if pre-existing or new"
PYTHONPATH=. python3 -m pytest scripts/ -q || echo "scripts has issues — check if pre-existing or new"
```

For each: capture the result. If any of these directories regress (passed before, fails now) **because of** the config change, do NOT proceed — either narrow the config to bridge tests via a local conftest, or talk to the affected owner. If a directory was already broken on main before this change, that's pre-existing and out of scope; document the status in the commit message and continue.

To prove pre-existing vs. caused-by-this-change:
```bash
git stash
PYTHONPATH=. python3 -m pytest <affected_dir> -q   # baseline on the new branch
git stash pop
```

- [ ] **Step 6: Commit**

```bash
git add pytest.ini frontend/ws_bridge/requirements-dev.txt
git commit -m "chore(tests): pytest-asyncio auto mode + function fixture loop + 30s timeout

Documented remedy for cross-file fakeredis loop-binding pollution
(pytest-dev/pytest-asyncio#660). Establishes the loop discipline that
the upcoming conftest.py extraction will rely on.

Adds pytest-timeout + timeout=30 as repo-wide hang protection: a
runaway drain_until or any future bad-state await fails in 30s with a
traceback instead of hanging CI for hours.

Verified non-bridge test directories (shared/, agents/, scripts/)
still pass under the new config — see eng-review 2A."
```

---

## Task 2: Create `_helpers.py` with `drain_until` (was Task 3)

**Files:**
- Create: `frontend/ws_bridge/tests/_helpers.py`
- Create: `frontend/ws_bridge/tests/test_helpers.py` (eng-review 3A: positive raise-path test)

`_drain_until` is a plain async function, not a fixture. It does not belong in `conftest.py` (conftest is for fixtures and pytest hooks). Putting it in a sibling helper module keeps responsibilities clean and lets test files import it explicitly.

Eng-review 3A: the helper's `AssertionError` path has no positive test today — it only fires implicitly when a regression breaks the bridge's echo path. If someone refactors `drain_until` to silently return `None` on miss, every dependent test would silently pass. Lock the contract with one tiny test file.

- [ ] **Step 1: Write `_helpers.py`**

```python
"""Shared async helpers for bridge WS tests.

These are NOT fixtures — they're plain functions imported explicitly by
the test files. Fixtures live in conftest.py; everything else lives here.
"""
from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Dict


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
```

- [ ] **Step 2: Verify the import path resolves**

```bash
PYTHONPATH=. python3 -c "from frontend.ws_bridge.tests._helpers import drain_until; print(drain_until.__doc__[:60])"
```
Expected: prints the first line of the docstring without ImportError.

- [ ] **Step 3: Write `test_helpers.py` (eng-review 3A)**

```python
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
```

Run:
```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_helpers.py -v
```
Expected: 2 passed.

- [ ] **Step 4: Commit**

```bash
git add frontend/ws_bridge/tests/_helpers.py frontend/ws_bridge/tests/test_helpers.py
git commit -m "test(bridge): extract drain_until into _helpers module

Single source of truth for the drain-frame-until-predicate helper. The
five existing copies had already drifted to four different max_frames
defaults (10/10/10/20/30); consolidating around 20 covers every call
site. Tests that need a different ceiling pass it explicitly."
```

---

## Task 3: Create `conftest.py` with shared fixtures (was Task 4)

**Files:**
- Create: `frontend/ws_bridge/tests/conftest.py`

Pytest auto-discovers `conftest.py` and makes its fixtures available to every test file in the directory and its subdirectories — no imports required at the call site. We hoist `fake_client` and `app_and_client` here.

`_IsoMsCounter` from `test_main_error_paths.py` stays local to that file. It's only used by error-path tests and exists to assert the bridge's stamping path actually executed (eng-review 1A guard from the previous plan). Hoisting it to conftest would couple it to tests that don't care.

- [ ] **Step 1: Write `conftest.py`**

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
async def app_and_client(monkeypatch, fake_client):
    """Construct the FastAPI app + httpx AsyncClient + ASGI WS transport
    against the fakeredis backend, run the bridge's lifespan context, and
    yield ``(app, http_client, fake_redis)``.

    Yields:
        tuple of (FastAPI app, httpx.AsyncClient, fakeredis client)

    Teardown: ``transport.exit_stack = None`` is a documented workaround
    for the httpx-ws<0.8 transport's circular-reference at shutdown. See
    requirements-dev.txt for the upper-bound pin and the migration TODO.
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

- [ ] **Step 2: Verify discovery**

Use a tiny throwaway test file to confirm pytest finds the fixture without any import:
```bash
cat > /tmp/_check_conftest.py <<'EOF'
import pytest

@pytest.mark.asyncio
async def test_conftest_discovery(fake_client):
    assert fake_client is not None
EOF
cp /tmp/_check_conftest.py frontend/ws_bridge/tests/test_zzz_conftest_check.py
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_zzz_conftest_check.py -v
rm frontend/ws_bridge/tests/test_zzz_conftest_check.py
```
Expected: 1 passed. If it fails with "fixture 'fake_client' not found", `conftest.py` has a typo or wrong location.

- [ ] **Step 3: Commit**

```bash
git add frontend/ws_bridge/tests/conftest.py
git commit -m "test(bridge): hoist fake_client and app_and_client to conftest.py

Pytest auto-discovers conftest fixtures across every test file in the
directory, so the five test_main_*.py files stop redefining identical
plumbing. Function-scoped + asyncio auto-mode (set in pytest.ini)
ensures fakeredis binds to the same loop as the test."
```

---

## Task 4: Migrate `test_main_error_paths.py` (newest, cleanest baseline) (was Task 5)

**Files:**
- Modify: `frontend/ws_bridge/tests/test_main_error_paths.py`

This is the file I just authored, so the imports are still fresh in my head. Migrating it first establishes the pattern for the other four files.

- [ ] **Step 1: Read the current file**

```bash
cat frontend/ws_bridge/tests/test_main_error_paths.py | head -100
```

Identify what to remove: `fake_client` fixture (lines 47-51), `app_and_client` fixture (lines 54-77), `_drain_until` helper (lines 82-90).

Identify what to keep: `_IsoMsCounter` class, `_FINDING_FIXTURE` constant, `_seed_finding` helper (all error-path-specific).

- [ ] **Step 2: Apply edits**

Remove the imports that only fed the deleted fixtures:
```python
# DELETE these lines (they're now in conftest.py):
import fakeredis.aioredis as fakeredis_async
import httpx
import pytest_asyncio
from httpx_ws.transport import ASGIWebSocketTransport
```

Keep `from httpx_ws import aconnect_ws` (used directly in tests).

Add the helper import:
```python
from frontend.ws_bridge.tests._helpers import drain_until
```

Delete the fixture definitions (`fake_client`, `app_and_client`) and the local `_drain_until` function.

Replace every call site of `_drain_until(` with `drain_until(`. Same for the function name in the docstring.

- [ ] **Step 3: Run the file in isolation**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_error_paths.py -v
```
Expected: 6 passed.

- [ ] **Step 4: Commit**

```bash
git add frontend/ws_bridge/tests/test_main_error_paths.py
git commit -m "test(bridge): migrate test_main_error_paths.py to shared conftest"
```

---

## Task 5: Migrate the four remaining `test_main_*.py` files (was Task 6)

**Files:**
- Modify: `frontend/ws_bridge/tests/test_main_command_translation_forward.py`
- Modify: `frontend/ws_bridge/tests/test_main_finding_id_allowlist.py`
- Modify: `frontend/ws_bridge/tests/test_main_operator_command_dispatch.py`
- Modify: `frontend/ws_bridge/tests/test_main_operator_command_publish.py`

Same shape as Task 4: drop fixtures, drop helper, import `drain_until` from `_helpers`, rename call sites.

- [ ] **Step 1: For each of the four files, apply the same edit**

For each file, do exactly:
1. Delete the `fake_client` async fixture block.
2. Delete the `app_and_client` async fixture block.
3. Delete the local `_drain_until` async function.
4. Remove now-unused imports: `fakeredis.aioredis as fakeredis_async`, `httpx`, `pytest_asyncio`, `from httpx_ws.transport import ASGIWebSocketTransport`. Keep `from httpx_ws import aconnect_ws` (still used in tests).
5. Add `from frontend.ws_bridge.tests._helpers import drain_until`.
6. Replace `_drain_until(` with `drain_until(` everywhere in the file (call sites, raise messages, docstrings).

- [ ] **Step 2: Run each file in isolation to confirm it still passes**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_command_translation_forward.py -v
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_finding_id_allowlist.py -v
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_operator_command_dispatch.py -v
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_operator_command_publish.py -v
```
Expected each: all tests pass. The exact counts as of today are: command_translation_forward=2, finding_id_allowlist=2, operator_command_dispatch=1, operator_command_publish=2.

- [ ] **Step 3: Run the FULL bridge non-e2e suite as a single invocation**

This is the regression check that proves the asyncio pollution fix:

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/ -m "not e2e" -v
```
Expected: 68 passed (or whatever total the non-e2e count is — see Task 1 baseline). If failures, this is where pollution would surface; iterate on `pytest.ini` (Task 2) or fixture scope before continuing.

- [ ] **Step 4: Commit**

```bash
git add frontend/ws_bridge/tests/test_main_command_translation_forward.py \
        frontend/ws_bridge/tests/test_main_finding_id_allowlist.py \
        frontend/ws_bridge/tests/test_main_operator_command_dispatch.py \
        frontend/ws_bridge/tests/test_main_operator_command_publish.py
git commit -m "test(bridge): migrate remaining test_main_*.py files to shared conftest

Five test files no longer redefine identical fake_client/app_and_client
fixtures or the _drain_until helper. Single source of truth in
conftest.py + _helpers.py. Removes ~150 lines of duplication."
```

---

## Task 6: Collapse CI per-file workaround to single pytest invocation (was Task 7; this is now where the asyncio-pollution diagnostic lands per eng-review 1C)

**Files:**
- Modify: `.github/workflows/test.yml`

With the asyncio pollution fixed, the per-file loop is no longer needed. **This task is also the diagnostic moment** for the asyncio pollution claim in TODOS.md (per eng-review 1C, the standalone diagnostic branch was dropped — Step 3 below captures the same data without the extra branch).

- [ ] **Step 1: Push current branch and verify CI is green BEFORE removing the workaround**

```bash
git push -u origin chore/bridge-test-harness-cleanup
gh pr create --draft --title "chore: bridge test harness cleanup" --body "WIP — see plan at docs/superpowers/plans/2026-05-03-asyncio-pollution-conftest-extraction.md"
```
Wait for CI green on the per-file path (existing workflow). This proves the migration didn't break anything BEFORE the workflow itself changes.

```bash
gh run list --workflow=tests --branch chore/bridge-test-harness-cleanup --limit 1
gh run watch <RUN_ID> --exit-status
```

- [ ] **Step 2: Edit `.github/workflows/test.yml`**

Replace this block:
```yaml
      # Per-file invocation is the documented workaround for cross-file
      # asyncio loop-binding pollution (TODOS.md "Bridge full-suite
      # asyncio test pollution"). Each file passes in isolation; running
      # them in one pytest invocation produces ~20 false failures.
      - name: Run ws_bridge tests (per file)
        run: |
          set -e
          for f in frontend/ws_bridge/tests/test_*.py; do
            echo "::group::$f"
            PYTHONPATH=. python -m pytest "$f" -v
            echo "::endgroup::"
          done
```
With:
```yaml
      - name: Run ws_bridge tests
        run: PYTHONPATH=. python -m pytest frontend/ws_bridge/tests/ -m "not e2e" -v
```

Note the `-m "not e2e"` — the new `bridge_e2e` job in Task 7 owns the e2e tests.

- [ ] **Step 3: Push and verify CI is green on the new pytest invocation (asyncio-pollution diagnostic moment)**

```bash
git add .github/workflows/test.yml
git commit -m "ci(bridge): single pytest invocation now that asyncio pollution is fixed

The per-file workaround is no longer needed. pytest-asyncio auto mode
+ function-scoped fixture loop + the conftest extraction lets the full
suite run in one invocation. Removes ~10 lines of CI shell."
git push
gh run watch <RUN_ID> --exit-status
```

**Three possible outcomes — handle each explicitly:**

1. **Bridge job green on single-invocation.** The pollution fix worked. Document this in the eventual PR description: "Confirmed: pytest-asyncio auto mode + function fixture loop + conftest dedup eliminates the previously documented full-suite pollution. Single-invocation run is now reliable on Linux+Python 3.11."

2. **Bridge job fails on single-invocation but passed per-file in Step 1.** Pollution survived the fix. Capture the failure shape:
   ```bash
   gh run view <RUN_ID> --log-failed > /tmp/pollution-actual.log
   head -100 /tmp/pollution-actual.log
   ```
   Read the trace. Likely culprits in order: (a) a fixture in the migrated `conftest.py` is module-scoped instead of function-scoped — fix in `conftest.py`; (b) `pytest.ini` config didn't actually apply — verify with `pytest --collect-only` shows asyncio mode auto; (c) one of the legacy non-`test_main_*.py` files (`test_subscriber.py`, `test_redis_publisher.py`, `test_outbound_publish.py`) still has its own loop-bound fixture — those weren't migrated because they don't use `app_and_client`, but they may still need the same fixture-loop discipline.
   
   Treat this as a regression of Task 1's config + Task 3's fixtures. Fix and push another commit. Do NOT proceed to Task 7 until this is resolved.

3. **Bridge job fails differently from how the legacy per-file mode passed.** Read the trace. If it's a real regression introduced by the migration (not pollution), revert the workflow change, fix the migration, re-push.

If the bridge job is green, append a one-liner to this plan file under a new `## Pollution outcome` section: "Single-invocation pytest passed on Linux+Python 3.11. Pollution claim from TODOS.md was real but has been resolved by this PR." If outcome 2 happens, append the captured failure trace and the fix that resolved it.

---

## Task 7: Add `bridge_e2e` Playwright CI job (was Task 8)

**Files:**
- Modify: `.github/workflows/test.yml`

The existing `test_e2e_playwright.py` runs four tests against real subprocesses. Today it runs zero times in CI. We add a third job.

- [ ] **Step 1: Append the new job to `.github/workflows/test.yml`**

Add after the `flutter` job:
```yaml
  bridge_e2e:
    name: bridge e2e (Playwright)
    runs-on: ubuntu-latest
    needs: [bridge, flutter]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - uses: subosito/flutter-action@v2
        with:
          channel: stable
          cache: true
      - name: Install redis-server
        run: sudo apt-get update && sudo apt-get install -y redis-server
      - name: Install Python dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r frontend/ws_bridge/requirements.txt
          pip install -r frontend/ws_bridge/requirements-dev.txt
          pip install -r shared/requirements.txt
      - name: Install Playwright chromium
        run: python -m playwright install --with-deps chromium
      - name: Generate topic constants
        run: PYTHONPATH=. python scripts/gen_topic_constants.py
      - name: Build Flutter web bundle
        working-directory: frontend/flutter_dashboard
        run: |
          flutter pub get
          flutter build web --release
      - name: Run bridge e2e Playwright tests
        run: PYTHONPATH=. python -m pytest frontend/ws_bridge/tests/test_e2e_playwright.py -m e2e -v
```

Notes on this job:
- `needs: [bridge, flutter]` — only run if the cheap unit-test jobs are green. No point burning Playwright minutes on a known-broken bridge.
- `redis-server` from apt — the test fixture's `_resolve_redis_server` already falls back to `shutil.which("redis-server")`, so apt's `/usr/bin/redis-server` is fine.
- `--with-deps chromium` — installs Playwright's chromium plus the system libs (libnss3 etc.) it needs in headless Linux.
- `flutter build web --release` — the test fixture skips with a clear message if `frontend/flutter_dashboard/build/web/index.html` is missing.
- `-m e2e` — only the four Playwright tests, not the unit tests already covered by the `bridge` job.

- [ ] **Step 2: Push and check the new job runs**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add bridge_e2e Playwright job

Builds Flutter web, installs redis-server + chromium, runs the four
existing @pytest.mark.e2e tests against real uvicorn + redis-server +
http.server subprocesses. Catches regressions the in-process httpx
unit tests can't see."
git push
```

- [ ] **Step 3: Watch the new job and debug if needed**

```bash
gh run list --workflow=tests --branch chore/bridge-test-harness-cleanup --limit 1
gh run watch <RUN_ID>
```

Expected: all three jobs green. Common first-run issues to expect and how to handle:

- **`redis-server: command not found`** — apt install line failed; check the runner image. Workaround: pin `ubuntu-22.04` if `ubuntu-latest` ships without redis-server in repos.
- **`Flutter web build missing at .../build/web`** — `flutter build web --release` step failed silently or wrote to wrong path. Check the build step logs, verify `working-directory` is right.
- **Playwright timeout opening WebSocket** — likely a port-binding race in `_pick_free_port`. The test does retry; if it consistently fails on CI but passes locally, increase `_wait_http_ready` timeout or add a 1s sleep after `subprocess.Popen` for redis-server.
- **`browser closed unexpectedly`** — chromium missing system libs; ensure `--with-deps` was passed.

Iterate on the workflow file until green. Each fix is a new commit; do not squash diagnostic commits until the job is reliable.

- [ ] **Step 4: Confirm Playwright tests actually run end-to-end**

Once the job is green, sanity-check the log to make sure all four tests ran (not skipped):

```bash
gh run view <RUN_ID> --log | grep -E "test_dashboard_loads_and_connects|test_finding_appears_in_panel|test_captured_ws_frames_revalidate|test_drone_state_reflects_battery"
```

Expected: each test appears with `PASSED`. If any shows `SKIPPED`, the build-web step probably didn't produce the expected files; check the fixture's skip condition.

---

## Task 8: Update `TODOS.md` and finalize PR (was Task 9)

**Files:**
- Modify: `TODOS.md`

Close the two relevant entries; flag anything residual.

- [ ] **Step 1: Edit `TODOS.md`**

Find the entry `### Bridge full-suite asyncio test pollution (Phase 5+)`. Mark it closed:
```markdown
### ~~Bridge full-suite asyncio test pollution~~ (closed in chore/bridge-test-harness-cleanup)
**CLOSED** — fixed by `pytest.ini` setting `asyncio_mode = auto` and
`asyncio_default_fixture_loop_scope = function`, plus the conftest.py
extraction (single fakeredis fixture binds to the running loop). CI
now runs the full bridge suite in one pytest invocation. Original
entry retained below for historical context.
```
(then leave the original body)

Find the entry `### Extract bridge WS test helpers to conftest.py (Phase 5+)`. Mark it closed:
```markdown
### ~~Extract bridge WS test helpers to conftest.py~~ (closed in chore/bridge-test-harness-cleanup)
**CLOSED** — `frontend/ws_bridge/tests/conftest.py` hosts `fake_client`
and `app_and_client`; `frontend/ws_bridge/tests/_helpers.py` hosts the
`drain_until` async helper. Five test files migrated. ~150 lines of
duplication removed. Original entry retained below for historical
context.
```

Add a new entry under "Phase 4+" for the Playwright job's residual concern:
```markdown
### Migrate bridge tests off `httpx-ws` private API (Phase 5+)
- **What:** `frontend/ws_bridge/tests/conftest.py`'s `app_and_client`
  fixture pokes `transport.exit_stack = None` to break a circular ref at
  shutdown. This reaches into private API; `httpx-ws` 0.8.0 already
  changed `ASGIWebSocketTransport`'s internals (we pin `<0.8` in
  requirements-dev.txt). Migrate to the public `aconnect_ws` lifecycle
  pattern when the public API supports our use case.
- **Why:** The pin will rot. Future security/perf releases of httpx-ws
  will land behind 0.8, and we'll be stuck.
- **Owner:** Person 4.
```

- [ ] **Step 2: Commit and push**

```bash
git add TODOS.md
git commit -m "docs: close asyncio pollution + conftest extraction TODOs

Both items resolved in this PR. New TODO filed for migrating off
httpx-ws private API (transport.exit_stack), since the <0.8 pin is a
known stopgap that should not stay forever."
git push
```

- [ ] **Step 3: Mark PR ready and request review**

```bash
gh pr ready
gh pr view --web   # eyeball the diff one more time
```

Verify all three CI jobs are green (`bridge`, `flutter`, `bridge_e2e`). Do not merge until all three are green AND the diff matches the plan (no surprise files).

- [ ] **Step 4: Squash-merge once approved**

```bash
gh pr merge --squash --delete-branch
git checkout main
git pull
```

---

## Self-Review (updated post-eng-review)

**Spec coverage:**
- ✅ Asyncio pollution: Task 1 (config + timeout) + Task 3 (conftest) + Task 5 (full-suite verification) + Task 6 (CI workflow collapse, where the diagnostic moment lives)
- ✅ `conftest.py` extraction: Task 3 (create) + Tasks 4-5 (migrate)
- ✅ Playwright testing: Task 7 (new CI job) + Task 7 Step 4 (sanity-check)
- ✅ Regular unit tests: Task 2 Step 3 (drain_until raise/match positive tests), Task 4 Step 3, Task 5 Steps 2-3 (per-file and full-suite verification at every migration)

**Eng-review fixes applied:**
- ✅ **1C** — Dropped diagnostic-baseline branch. Task 6 Step 3 is now the diagnostic moment with explicit branch points for green vs. surviving-pollution outcomes.
- ✅ **2A** — Task 1 Step 5 verifies `agents/`, `shared/`, `scripts/` test directories don't regress under the new pytest.ini config.
- ✅ **3A** — New `test_helpers.py` (Task 2 Step 3) with positive raise-path test plus a happy-path counterpart.
- ✅ **4A** — `pytest-timeout` added to requirements-dev.txt; `timeout = 30` added to pytest.ini in Task 1.

**Placeholder scan:** None. Every step has the exact command, exact file edit, and expected output.

**Type/name consistency:** `drain_until` (no leading underscore — it's a public helper module export) is consistent across Tasks 2, 4, 5. `fake_client` and `app_and_client` keep their existing names. `_IsoMsCounter` stays test-local in `test_main_error_paths.py` (Task 4 docs why).

**Scope check:** Single concern (test harness cleanup). Does NOT touch production code in `main.py`, `redis_subscriber.py`, etc. Does NOT touch other test files (`test_aggregator.py`, `test_subscriber.py`, etc.) that don't use these fixtures. The Playwright CI job uses tests that already exist; we don't write new e2e tests.

**Risk surface:**
1. **Playwright job flakiness.** Task 7 lists the four most likely first-run failure modes and the iteration loop. Budget time for 2-3 commits before the job is reliable.
2. **`pytest.ini` asyncio + timeout change affects every test directory.** Mitigated by Task 1 Step 5's repo-wide verification (eng-review 2A). If a non-bridge directory regresses, the fix is to narrow the config to a directory-local conftest before continuing.
3. **`timeout = 30` may be too aggressive for Playwright tests under cold-start CI.** Each Playwright test fixture spins up redis + uvicorn + http.server + chromium; cold-start could exceed 30s on a slow runner. Mitigation: if the e2e job times out, override per-test with `@pytest.mark.timeout(60)` on the e2e module, or set `timeout_method = thread` to allow longer waits in subprocess-heavy tests. Task 7 should watch for this.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-03-asyncio-pollution-conftest-extraction.md`.**

Two execution options:

1. **Inline execution (recommended for this plan)** — I drive each task in this session. Faster iteration, single context, the user can interrupt if Task 6's pollution diagnostic reveals something unexpected.
2. **Subagent-driven** — overkill for an 8-task harness cleanup with high task interdependence (each migration must verify before the next).

Recommendation: option 1. Say "ready" to begin Task 1.

---

## Pollution outcome

Single-invocation pytest passed on Linux+Python 3.11 in CI run #25287073503. The pollution claim from TODOS.md was real but has been resolved by this PR (pytest-asyncio auto mode + function-scoped fixture loop + conftest dedup eliminated the cross-file loop-binding mismatch). Confirmed by green check on PR #7.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR | 4 issues, 1 critical gap, all 4 recommendations applied (1C, 2A, 3A, 4A) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (test infrastructure) |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — ready to implement. All 4 review recommendations folded into the plan inline.
