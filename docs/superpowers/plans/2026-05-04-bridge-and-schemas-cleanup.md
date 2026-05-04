# Bridge + Schemas Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 3 unblocked TODOs in one PR — `httpx-ws` private API migration, async ValidationEventLogger, and schema `$ref` convention documentation.

**Architecture:** Three independent workstreams, each its own commit so reviewers can audit them separately. Tasks are sequenced bridge-tests → bridge-runtime → schemas-docs because they touch progressively wider blast radii (test fixture → production hot path → docs only).

**Tech Stack:** Python 3.11 + FastAPI + pytest-asyncio + httpx-ws + fakeredis (bridge); JSON Schema 2020-12 (`shared/schemas/`).

---

## File Structure

**Workstream 1 — `httpx-ws` migration (Tasks 1-2):**
- Modify: `frontend/ws_bridge/tests/conftest.py:30-63` — enter `ASGIWebSocketTransport` as async context manager, drop the `transport.exit_stack = None` workaround
- Modify: `frontend/ws_bridge/requirements-dev.txt` — remove `<0.8` upper bound
- Verify (no edits): `frontend/ws_bridge/tests/test_main_*.py` (5 files) — all use `aconnect_ws` via the shared fixture, so no per-test edits

**Workstream 2 — async ValidationEventLogger (Tasks 3-4):**
- Modify: `frontend/ws_bridge/redis_subscriber.py:347-384` — make `_log_validation_failure` async, run sync I/O in executor, update three call sites to `await`
- Test: `frontend/ws_bridge/tests/test_subscriber.py` — add a regression test that asserts dispatch latency stays bounded under 100 rapid validation failures even with a slow logger

**Workstream 3 — schema `$ref` convention docs (Task 5):**
- Create: `shared/schemas/CONVENTIONS.md` — document the relative-ref + absolute-`$id` convention already in use across all 14 schemas
- No code changes — schemas already consistent (verified: every cross-file `$ref` uses relative paths like `_common.json#/$defs/foo`)

**TODO bookkeeping (Task 6):**
- Modify: `TODOS.md:16` (httpx-ws migration), `TODOS.md:125` ($ref convention), `TODOS.md:148` (ValidationEventLogger async)

---

## Workstream 1: `httpx-ws` Migration

The `<0.8` pin exists because `httpx-ws` 0.8.0 changed `ASGIWebSocketTransport`: `aconnect_ws` now reads `transport._task_group`, which is only set when the transport is entered as an async context manager. Our fixtures construct the transport directly (`ASGIWebSocketTransport(app=app)`), so `_task_group` is `None` and `aconnect_ws` raises `AttributeError` on 0.8+.

The migration: enter the transport as `async with ...`. Bonus side-effect — the AsyncExitStack inside the transport manages its own cleanup, so the `transport.exit_stack = None` private-attribute hack at teardown is no longer needed.

### Task 1: Enter `ASGIWebSocketTransport` as async context manager

**Files:**
- Modify: `frontend/ws_bridge/tests/conftest.py:30-63`
- Modify: `frontend/ws_bridge/requirements-dev.txt`

- [ ] **Step 1: Bump httpx-ws (no upper bound)**

Replace the `httpx-ws` line in `frontend/ws_bridge/requirements-dev.txt`:

```
# Was:  httpx-ws>=0.7.0,<0.8
httpx-ws>=0.8
```

And replace the multi-line comment block above it (lines that explain the `<0.8` pin) with:

```
# Phase 4 bridge test harness: httpx.AsyncClient + pytest_asyncio + httpx-ws.
# (TestClient + asyncio.new_event_loop binds fakeredis to the wrong loop;
# see plan section "Test harness convention for Tasks 7-10".)
#
# httpx-ws 0.8 requires entering ASGIWebSocketTransport as an async context
# manager so ``transport._task_group`` is initialised before ``aconnect_ws``
# calls into it. The shared fixture in tests/conftest.py does this.
```

- [ ] **Step 2: Reinstall**

Run:

```bash
pip install -r frontend/ws_bridge/requirements-dev.txt --upgrade
pip show httpx-ws | grep Version
```

Expected: `Version: 0.8.x` or higher.

- [ ] **Step 3: Verify the existing fixture FAILS on 0.8**

Run any single bridge test before changing the fixture:

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_error_paths.py -x -v 2>&1 | tail -20
```

Expected: FAIL with `AttributeError: 'ASGIWebSocketTransport' object has no attribute '_task_group'` (or similar — a 0.8-API mismatch).

If tests pass on 0.8 without changes, the migration is already non-breaking and you can skip directly to Step 5 (just delete the workaround line). Note the actual error in your commit body.

- [ ] **Step 4: Update conftest.py**

Replace the `app_and_client` fixture body in `frontend/ws_bridge/tests/conftest.py` (currently lines 30-63):

```python
@pytest_asyncio.fixture
async def app_and_client(monkeypatch, fake_client):
    """Construct the FastAPI app + httpx AsyncClient + ASGI WS transport
    against the fakeredis backend, run the bridge's lifespan context, and
    yield ``(app, http_client, fake_redis)``.

    Yields:
        tuple of (FastAPI app, httpx.AsyncClient, fakeredis client)

    httpx-ws 0.8 requires the transport to be entered as an async context
    manager so ``aconnect_ws`` can read ``transport._task_group``. The
    AsyncExitStack inside the transport handles its own cleanup, which
    obsoletes the ``transport.exit_stack = None`` workaround we used on
    httpx-ws 0.7.
    """
    import redis.asyncio as redis_async

    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )

    from frontend.ws_bridge.main import create_app

    app = create_app()
    async with ASGIWebSocketTransport(app=app) as transport:
        client = httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        )
        async with app.router.lifespan_context(app):
            try:
                yield app, client, fake_client
            finally:
                await client.aclose()
```

- [ ] **Step 5: Run the FULL bridge test suite (excluding e2e)**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/ -m "not e2e" -v 2>&1 | tail -10
```

Expected: 73/73 PASS (same number as before this PR).

If anything fails:
- Read the failure carefully. The most common failure mode is a fixture that opened resources expecting them to live until the OUTER `async with` exits, but the INNER `async with ASGIWebSocketTransport(...)` exits first and pulls the rug. If you see "task was destroyed but pending" or similar, look at the order.
- If the failure is reproducible and not flaky, STOP and escalate. The plan assumed 0.8's transport is drop-in compatible after the context-manager change. If it's not, this workstream may be blocked on an upstream issue.

- [ ] **Step 6: Run the e2e Playwright suite**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_e2e_playwright.py -m e2e -v 2>&1 | tail -10
```

Expected: 13/13 + 1 SKIP. (e2e tests use real subprocesses, not the conftest fixture, so this is verifying we didn't somehow regress a different code path.)

- [ ] **Step 7: Commit**

```bash
git add frontend/ws_bridge/tests/conftest.py frontend/ws_bridge/requirements-dev.txt
git commit -m "refactor(bridge-tests): migrate to httpx-ws 0.8 public lifecycle"
```

---

### Task 2: Verify version pin removal landed

This is a sanity-check task to make sure no stale `<0.8` reference survives.

- [ ] **Step 1: Grep for stale pins**

```bash
grep -rn "httpx-ws.*<0\.8\|httpx_ws.*<0\.8" frontend/ shared/ scripts/ docs/ 2>/dev/null | grep -v "docs/superpowers/plans/2026-05-04-"
```

Expected: NO output. (Plan files referencing the migration are excluded by the `grep -v`.)

If anything matches, update or remove it.

- [ ] **Step 2: Grep for stale `transport.exit_stack` references**

```bash
grep -rn "transport.exit_stack" frontend/ 2>/dev/null
```

Expected: NO output.

- [ ] **Step 3: Update the existing TODOS.md entry preview**

(Task 6 closes the TODO formally — this step is just a sanity check that the entry can be closed.)

```bash
grep -A1 "Migrate bridge tests off" TODOS.md | head -3
```

Expected: the open TODO header. If the body still mentions `<0.8`, that's fine — Task 6 strikes the whole entry through.

---

## Workstream 2: Async `ValidationEventLogger`

`frontend/ws_bridge/redis_subscriber.py:347-384` calls `self._validation_logger.log(...)` synchronously inside `_handle_message`. The logger does sync disk I/O (`open(path, "a")` + `f.write(...)` at `shared/contracts/logging.py:89-90`). A misbehaving EGS spamming malformed translations could stall the Redis drain on disk I/O latency, especially on slow disks or during log rotation.

Fix: convert `_log_validation_failure` to an async method that runs the blocking write in the default thread pool executor via `loop.run_in_executor(None, ...)`. Three call sites in `_handle_message` (lines 256, 267, 285 currently) get updated to `await`.

Why executor over a queue+writer task: the queue+writer pattern (mirrors `translation_queue`) is overkill for ~1-event-per-second steady-state traffic. The executor approach is a 4-line change. We can revisit if profiling shows pool starvation.

### Task 3: Make `_log_validation_failure` async

**Files:**
- Modify: `frontend/ws_bridge/redis_subscriber.py:347-384` — change to `async def`, wrap `.log()` in `run_in_executor`
- Modify: `frontend/ws_bridge/redis_subscriber.py:256, 267, 285` — three call sites updated to `await self._log_validation_failure(...)`

- [ ] **Step 1: Write the failing test**

Append to `frontend/ws_bridge/tests/test_subscriber.py`:

```python
@pytest.mark.asyncio
async def test_validation_log_does_not_block_dispatch(aggregator, monkeypatch):
    """Adversarial finding #7: ValidationEventLogger.log() did sync disk I/O
    on the subscriber dispatch path. A slow disk would stall the Redis drain.

    This test installs a deliberately slow logger and asserts that
    dispatch latency stays bounded — i.e. the slow log doesn't block the
    next message from being handled.
    """
    import time

    fake = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake),
    )

    class _SlowLogger:
        """Stand-in ValidationEventLogger that takes 200ms per write
        (simulates disk under load). Records call timestamps so we can
        verify the subscriber kept dispatching while writes are pending.
        """
        def __init__(self) -> None:
            self.calls: list = []

        def log(self, **kw) -> None:
            self.calls.append(time.monotonic())
            time.sleep(0.2)  # 200ms blocking I/O

    slow = _SlowLogger()
    config = BridgeConfig(
        redis_url="redis://localhost",
        tick_s=0.05,
        max_findings=100,
        broadcast_timeout_s=0.5,
        reconnect_max_s=2.0,
    )
    sub = RedisSubscriber(
        config=config,
        aggregator=aggregator,
        validation_logger=slow,
        translation_queue=asyncio.Queue(maxsize=64),
    )
    task = asyncio.create_task(sub.run())
    try:
        await asyncio.sleep(0.1)  # let it subscribe

        # Publish 5 schema-invalid frames in rapid succession. Without the
        # async log, each invalid frame's _log_validation_failure would
        # block the dispatch loop for 200ms (5 frames × 200ms = 1s).
        # With the async log, dispatch should complete in well under that.
        start = time.monotonic()
        for i in range(5):
            await fake.publish(
                "drones.drone1.state",
                '{"this": "is not a valid drone_state"}',  # schema-invalid
            )
        # Give the subscriber time to drain — but bound it.
        deadline = start + 0.5  # 500ms budget — must beat 5×200ms blocking
        while time.monotonic() < deadline and len(slow.calls) < 5:
            await asyncio.sleep(0.01)

        elapsed = time.monotonic() - start
        assert len(slow.calls) == 5, (
            f"expected 5 logged events, got {len(slow.calls)} "
            f"(slow logger may not be running off-loop)"
        )
        # The key assertion: all 5 dispatches completed in < 500ms
        # despite each blocking call taking 200ms. If sync, this would
        # take >= 1000ms.
        assert elapsed < 0.5, (
            f"dispatch took {elapsed:.3f}s with 5 slow log calls — "
            f"sync I/O is blocking dispatch (expected < 0.5s with executor)"
        )
    finally:
        sub.signal_stop()
        await asyncio.wait_for(task, timeout=2.0)
        await sub.close()
```

The test relies on `redis_async` already being imported at the top of the test file (it's imported as `import redis.asyncio as redis_async` for other tests). If not, add the import.

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_subscriber.py::test_validation_log_does_not_block_dispatch -v
```

Expected: FAIL with `assert 1.0xx < 0.5` or similar — the 5 sequential 200ms blocking calls take ~1s total, exceeding the 500ms budget.

- [ ] **Step 3: Convert `_log_validation_failure` to async**

In `frontend/ws_bridge/redis_subscriber.py`, replace the `_log_validation_failure` method (currently sync at lines 347-384) with:

```python
async def _log_validation_failure(
    self,
    *,
    schema_name: str,
    drone_id: Optional[str],
    channel: str,
    rule_id: str,
    detail: str,
    raw_call: Optional[Dict[str, Any]],
) -> None:
    """Best-effort ASYNC write to the validation event log.

    The underlying ``ValidationEventLogger.log()`` does sync disk I/O
    (``open(..., "a")`` + ``f.write(...)``). On slow disks or under log
    rotation, that I/O can stall the Redis drain. Adversarial review
    finding #7 (Phase 4) flagged this. Migrate to running the sync
    write in the default thread pool executor so dispatch never
    blocks on disk.

    Schema constraint: ``agent_id`` must be a drone_id or the literal
    ``"egs"``; ``layer`` must be ``drone`` / ``egs`` / ``operator``. We
    attribute drone-channel failures to the source drone and EGS-channel
    failures to ``egs``. ``raw_call`` carries the offending payload (or
    None for JSON-decode errors). The channel name and detail are folded
    into ``function_or_command`` so downstream readers can grep them.
    """
    if drone_id is not None:
        agent_id = drone_id
        layer = "drone"
    else:
        agent_id = "egs"
        layer = "egs"
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: self._validation_logger.log(
                agent_id=agent_id,
                layer=layer,
                function_or_command=f"{schema_name}@{channel}: {detail}",
                attempt=1,
                valid=False,
                rule_id=rule_id,
                outcome="failed_after_retries",
                raw_call=raw_call,
            ),
        )
    except Exception:  # pragma: no cover — never let logging crash dispatch
        _LOG.exception("RedisSubscriber: failed to write validation event")
```

Note: `Layer` and `Outcome` Literal types from `shared.contracts.logging` aren't referenced here (they were only on the underlying `.log()` signature) — the call still passes the same string values, just delivered through the executor.

- [ ] **Step 4: Update the three call sites to `await`**

In `frontend/ws_bridge/redis_subscriber.py`, find the three call sites of `self._log_validation_failure(...)` (currently around lines 256, 267, 285 — exact lines may have shifted from earlier edits). Each currently looks like:

```python
self._log_validation_failure(
    schema_name=...,
    drone_id=...,
    ...
)
```

Change each to:

```python
await self._log_validation_failure(
    schema_name=...,
    drone_id=...,
    ...
)
```

(Just prepend `await`. The surrounding `_handle_message` is already an async method, so `await` is allowed.)

- [ ] **Step 5: Run the new test to verify it passes**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_subscriber.py::test_validation_log_does_not_block_dispatch -v
```

Expected: PASS. Elapsed time should be ~250-350ms (5 dispatches in parallel, each waiting on a 200ms executor call but drained concurrently — actually executor is bounded by default pool size, but 5 tasks fit comfortably).

If the test fails with `assert N == 5` (slow.calls count too low), the dispatch finished before all logs ran. Either:
- Increase the deadline window (e.g., 800ms) — acceptable, just rebalance the constants
- Use `asyncio.wait_for(...)` on the actual fakeredis publish, which is more deterministic

If the test fails with `elapsed >= 0.5s`, the executor isn't actually offloading. Double-check `await loop.run_in_executor(None, ...)` is present.

- [ ] **Step 6: Run the full subscriber test file**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_subscriber.py -v
```

Expected: all tests pass — old sync-path tests still work because the `await` at the call site is invisible to the assertion logic.

- [ ] **Step 7: Run the full bridge test suite**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/ -m "not e2e" -v
```

Expected: all 74+ tests pass (73 pre-existing + 1 new).

- [ ] **Step 8: Commit**

```bash
git add frontend/ws_bridge/redis_subscriber.py frontend/ws_bridge/tests/test_subscriber.py
git commit -m "perf(bridge): run ValidationEventLogger writes off subscriber dispatch path"
```

---

### Task 4: Smoke-test under load (optional verification)

This is a sanity check that the executor approach doesn't have a hidden serialization bottleneck. Skip if Task 3 tests already give you confidence.

- [ ] **Step 1: Quick load smoke**

```bash
PYTHONPATH=. python3 -c "
import asyncio
import time
from frontend.ws_bridge.config import BridgeConfig
from frontend.ws_bridge.aggregator import StateAggregator
from frontend.ws_bridge.redis_subscriber import RedisSubscriber
from shared.contracts.logging import ValidationEventLogger
import fakeredis.aioredis as fakeredis_async
import redis.asyncio as redis_async

class _SlowLogger:
    def __init__(self): self.calls = 0
    def log(self, **kw):
        self.calls += 1
        time.sleep(0.05)

async def main():
    fake = fakeredis_async.FakeRedis()
    redis_async.Redis.from_url = staticmethod(lambda url, **kw: fake)
    config = BridgeConfig(redis_url='redis://localhost', tick_s=0.05,
                         max_findings=100, broadcast_timeout_s=0.5,
                         reconnect_max_s=2.0)
    seed = {'type':'state_update','timestamp':'2026-05-04T12:00:00.000Z','contract_version':'1.0.0','active_findings':[],'active_drones':[],'egs_state':{}}
    agg = StateAggregator(max_findings=100, seed_envelope=seed)
    slow = _SlowLogger()
    sub = RedisSubscriber(config=config, aggregator=agg,
                         validation_logger=slow,
                         translation_queue=asyncio.Queue(maxsize=64))
    task = asyncio.create_task(sub.run())
    await asyncio.sleep(0.1)
    start = time.monotonic()
    N = 50
    for _ in range(N):
        await fake.publish('drones.drone1.state', '{\"bad\":\"frame\"}')
    await asyncio.sleep(2.0)
    elapsed = time.monotonic() - start
    print(f'logged={slow.calls}/{N} elapsed={elapsed:.2f}s avg_per_dispatch={(elapsed/N)*1000:.1f}ms')
    sub.signal_stop()
    await asyncio.wait_for(task, timeout=2.0)
    await sub.close()

asyncio.run(main())
"
```

Expected: `logged=50/50 elapsed=~2-3s avg_per_dispatch=~50-60ms`. If `elapsed > 5s` the executor is somehow serializing — investigate.

This step doesn't produce a commit; it's just a confidence check.

---

## Workstream 3: Schema `$ref` Convention Documentation

Verified by grep: every cross-file `$ref` in `shared/schemas/*.json` already uses relative paths (`_common.json#/$defs/foo`, `drone_state.json`, etc.). Internal refs use `#/$defs/foo`. The 14 schemas are consistent. The `$id` URIs are absolute (`https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/<file>.json`) which lets relative refs resolve correctly per JSON Schema 2020-12 base resolution.

The TODO concern was "decide on a single style" — the codebase already did. This task documents it so future contributors don't re-introduce inconsistency.

### Task 5: Write `shared/schemas/CONVENTIONS.md`

**Files:**
- Create: `shared/schemas/CONVENTIONS.md`

- [ ] **Step 1: Create the convention doc**

Write `shared/schemas/CONVENTIONS.md` with this content:

```markdown
# `shared/schemas/` Conventions

This directory hosts the locked JSON Schema definitions referenced by
[Contract 1](../../docs/20-integration-contracts.md#contract-1-json-schema-locking).
Every schema in here is part of the agreed-upon Day-1 contract surface.
Do not change shapes without a contract-revision sign-off.

## `$id` Convention

Every top-level schema file MUST set an absolute `$id`:

```json
{
  "$id": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/<file>.json",
  ...
}
```

`v1` is the contract version. If we ever ship a `v2`, it goes in a
sibling directory and the `$id` base updates accordingly.

## `$ref` Convention

All `$ref` values are RELATIVE. There are two shapes:

### Internal refs (within the same file)

Use a fragment-only ref:

```json
{"$ref": "#/$defs/finding_approval"}
```

### Cross-file refs

Use the relative file name + fragment:

```json
{"$ref": "_common.json#/$defs/iso_timestamp_utc_ms"}
{"$ref": "drone_state.json"}
```

DO NOT use absolute URIs in `$ref`:

```json
// WRONG — DO NOT DO THIS
{"$ref": "https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/_common.json#/$defs/iso_timestamp_utc_ms"}
```

## Why Relative

JSON Schema 2020-12 resolves relative refs against the enclosing
schema's `$id` base. Because every schema's `$id` shares the same
`v1/` base, a relative ref like `_common.json#/$defs/foo` resolves
to `https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/_common.json#/$defs/foo`
correctly.

The benefit: if we ever rename the GitHub org, change the path, or
migrate to a different schema host, we only update the `$id` lines.
The `$ref` values are stable.

If we used absolute `$ref` URIs instead, every rename would require a
search-and-replace across every schema, with the risk of missing one.

## Adding a New Schema

1. Pick a filename: `<purpose>.json` (e.g., `peer_broadcast.json`).
2. Set `$id` to `https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/<filename>.json`.
3. Use relative `$ref` for any cross-file references.
4. Add fixtures under `shared/schemas/fixtures/valid/` and `fixtures/invalid/`.
5. Add a test under `shared/tests/test_<purpose>.py` that loads the
   schema, validates the fixtures, and references RuleIDs from
   `docs/20-integration-contracts.md`.

## Verifying Convention Compliance

Run:

```bash
# All cross-file refs must use relative paths (no http://)
grep -h '"\$ref"' shared/schemas/*.json | grep -E '"http' && echo "FAIL: absolute \$ref found" || echo "PASS"

# Every top-level schema must have an absolute $id
for f in shared/schemas/*.json; do
  grep -q '"\$id".*"https://' "$f" || echo "MISSING \$id: $f"
done
```

Both should print `PASS` / no missing-`$id` lines.
```

- [ ] **Step 2: Verify the convention compliance commands actually work**

Run the two verification commands from the doc:

```bash
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
grep -h '"\$ref"' shared/schemas/*.json | grep -E '"http' && echo "FAIL: absolute \$ref found" || echo "PASS"
```

Expected: `PASS`.

```bash
for f in shared/schemas/*.json; do
  grep -q '"\$id".*"https://' "$f" || echo "MISSING \$id: $f"
done
```

Expected: NO output (every schema has the absolute `$id`).

If either command reports a violation, fix the offending schema file BEFORE landing this PR — the convention doc is only meaningful if the codebase already complies.

- [ ] **Step 3: Run the schema test suite to confirm nothing regressed**

```bash
PYTHONPATH=. python3 -m pytest shared/tests/ -v 2>&1 | tail -10
```

Expected: all schema tests pass (sanity check — we didn't touch any schemas, but verify regardless).

- [ ] **Step 4: Commit**

```bash
git add shared/schemas/CONVENTIONS.md
git commit -m "docs(schemas): document relative \$ref + absolute \$id convention"
```

---

## Task 6: Close TODOs and open PR

- [ ] **Step 1: Update `TODOS.md`**

Three TODOs to close. For each, prepend `### ~~` and append `~~` to the heading line and add a `**CLOSED** — ...` body.

For "Migrate bridge tests off `httpx-ws` private API (Phase 5+)" (TODOS.md:16) replace its heading line with:

```markdown
### ~~Migrate bridge tests off `httpx-ws` private API (Phase 5+)~~ (closed in feat/bridge-and-schemas-cleanup)
**CLOSED** — `frontend/ws_bridge/tests/conftest.py` enters
`ASGIWebSocketTransport` as an async context manager; the
`transport.exit_stack = None` private-API workaround is removed.
`requirements-dev.txt` upper bound on `httpx-ws` lifted (now
`>=0.8`). Original entry retained below for historical context.
```

For "Move `ValidationEventLogger.log` off the subscriber dispatch path (Phase 5+)" (TODOS.md:148) replace its heading line with:

```markdown
### ~~Move `ValidationEventLogger.log` off the subscriber dispatch path (Phase 5+)~~ (closed in feat/bridge-and-schemas-cleanup)
**CLOSED** — `_log_validation_failure` is now async and runs
`ValidationEventLogger.log` via `loop.run_in_executor(None, ...)`.
Three call sites in `_handle_message` updated to `await`. Regression
test `test_validation_log_does_not_block_dispatch` asserts dispatch
latency stays bounded under 5×200ms slow logs. Original entry
retained below for historical context.
```

For "Repo-wide `$ref` convention pass (Phase 5+)" (TODOS.md:125) replace its heading line with:

```markdown
### ~~Repo-wide `$ref` convention pass (Phase 5+)~~ (closed in feat/bridge-and-schemas-cleanup)
**CLOSED** — verified by grep that all cross-file `$ref` values in
`shared/schemas/*.json` already use relative paths and all top-level
`$id` values use absolute URIs. Documented the convention in
`shared/schemas/CONVENTIONS.md` so future contributors don't
re-introduce inconsistency. Original entry retained below for
historical context.
```

- [ ] **Step 2: Commit TODO updates**

```bash
git add TODOS.md
git commit -m "docs(todos): close httpx-ws migration, async ValidationEventLogger, \$ref convention"
```

- [ ] **Step 3: Push and open PR**

Create branch first if not already on one:

```bash
git checkout -b feat/bridge-and-schemas-cleanup
git push -u origin feat/bridge-and-schemas-cleanup
gh pr create --title "Bridge + schemas cleanup: 3 unblocked TODOs in one PR" --body "$(cat <<'EOF'
## Summary
Three independent unblocked TODOs bundled into one PR. Each is its own commit so reviewers can audit them separately.

1. **Bridge tests: httpx-ws migration** — enter `ASGIWebSocketTransport` as async context manager; drop the `transport.exit_stack = None` private-API workaround; lift the `<0.8` version pin.
2. **Async ValidationEventLogger** — `_log_validation_failure` now runs sync disk I/O via `run_in_executor`. New regression test asserts dispatch latency stays bounded under slow-disk conditions. Closes adversarial finding #7 from Phase 4.
3. **Schema `$ref` convention docs** — verified existing schemas all comply (relative `$ref` + absolute `$id`); documented the convention in `shared/schemas/CONVENTIONS.md`. No code changes to schemas.

## Test plan
- [x] `pytest frontend/ws_bridge/tests/ -m "not e2e"` (74+ pass — 73 pre-existing + 1 new)
- [x] `pytest frontend/ws_bridge/tests/test_e2e_playwright.py -m e2e` (13/13 + 1 SKIP)
- [x] `pytest shared/tests/` (all schema tests still green)
- [x] Verification commands in `shared/schemas/CONVENTIONS.md` produce PASS / no missing-`$id`
- [ ] CI all 3 jobs green (verify after PR opens)

## Closes
- TODOS.md:16 — httpx-ws private API migration
- TODOS.md:125 — \$ref convention pass
- TODOS.md:148 — ValidationEventLogger async writer

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR opens. Watch the 3 CI jobs (`ws_bridge`, `flutter_dashboard`, `bridge_e2e`) for green.

- [ ] **Step 4: Verify CI**

```bash
sleep 60 && gh pr checks $(gh pr list --head feat/bridge-and-schemas-cleanup --json number -q '.[0].number')
```

Expected (after CI completes): all 3 jobs `pass`. If anything fails:
- `ws_bridge` failure → most likely Task 1 or Task 3. Read the failing test, identify which workstream, dispatch a fix.
- `flutter_dashboard` failure → unexpected; we didn't touch Flutter. If it's the Consumer-builder lint warning that bit us last time, the fix is the same one-line `__` → `_`. Otherwise investigate.
- `bridge_e2e` failure → most likely the Playwright UI dropdown flake on slow runner. Re-run before fixing — this is documented flake.

---

## Self-Review

**1. Spec coverage:**
- TODOS.md:16 (httpx-ws migration) → Tasks 1, 2.
- TODOS.md:125 (\$ref convention) → Task 5.
- TODOS.md:148 (ValidationEventLogger async) → Tasks 3, 4.
- TODO closure → Task 6.

**2. Placeholder scan:** No "TBD" / "implement later" / "fill in details" anywhere. Every step has full code or full commands. The one judgment call is Step 3 of Task 1 ("if tests pass on 0.8 without changes, skip to Step 5") — that's not a placeholder, it's a documented branch in the workflow.

**3. Type consistency:**
- `_log_validation_failure` signature unchanged across Tasks 3 and 4 (just `def` → `async def`).
- Conftest fixture name `app_and_client` and yields `(app, client, fake_client)` — unchanged across the migration.
- `signal_stop()` and `close()` referenced in Task 3's test (used to tear down) match the API shipped in PR #10.

**4. Risk note for the engineer:**
Workstream 1 has the highest unknown — if httpx-ws 0.8 needs more than the context-manager change, the fixture migration may grow beyond the plan. If you hit something in Task 1 Step 5 that isn't trivially fixable, STOP and escalate rather than improvising. The plan can grow a Task 1.5 if needed; better than landing a half-migration.

**5. Independence check:** Each commit (1, 3, 5, 6) can be reverted independently without breaking the others:
- Revert commit 1 → tests revert to httpx-ws<0.8 patten; nothing else cares
- Revert commit 3 → log goes back to sync; subscriber test still passes (the regression test reverts with it)
- Revert commit 5 → CONVENTIONS.md goes away; schemas still validate
- Revert commit 6 → TODOs reopen; no code impact
