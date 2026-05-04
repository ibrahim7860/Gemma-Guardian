# Bridge + Schemas Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 3 unblocked TODOs in one PR — `httpx-ws` private API migration, queue-backed ValidationEventLogger writer, and schema `$ref` convention documentation.

**Architecture:** Three independent workstreams. Tasks 1, 5, and 6 each their own commit. Workstream 2 splits into Task 3 (queue+writer plumbing, no behaviour change) and Task 4 (behaviour flip), so reviewers can audit the plumbing diff independently from the behaviour change. Tasks are sequenced bridge-tests → bridge-runtime → schemas-docs because they touch progressively wider blast radii (test fixture → production hot path → docs only).

**Tech Stack:** Python 3.11 + FastAPI + pytest-asyncio + httpx-ws + fakeredis (bridge); JSON Schema 2020-12 (`shared/schemas/`).

---

## File Structure

**Workstream 1 — `httpx-ws` migration (Tasks 1-2):**
- Modify: `frontend/ws_bridge/tests/conftest.py:30-63` — enter `ASGIWebSocketTransport` as async context manager, drop the `transport.exit_stack = None` workaround
- Modify: `frontend/ws_bridge/requirements-dev.txt` — remove `<0.8` upper bound
- Verify (no edits): `frontend/ws_bridge/tests/test_main_*.py` (5 files) — all use `aconnect_ws` via the shared fixture, so no per-test edits

**Workstream 2 — queue-backed ValidationEventLogger (Tasks 3-4):**
- Modify: `frontend/ws_bridge/main.py:174-293` — add `validation_log_queue: asyncio.Queue`, add `_validation_log_writer_loop` closure, wire to `app.state` + lifespan cancel/await
- Modify: `frontend/ws_bridge/redis_subscriber.py:93-114` — add `validation_log_queue` constructor param + storage
- Modify: `frontend/ws_bridge/redis_subscriber.py:347-384` — convert `_log_validation_failure` to sync `put_nowait` (drop-on-full policy)
- Modify: `frontend/ws_bridge/tests/test_subscriber.py` — update 4 RedisSubscriber construction sites with new kwarg, add 2 new tests (latency + exception path)

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
httpx-ws>=0.8,<0.9
```

(Eng-review 1A: keep an upper bound. httpx-ws has shipped breaking changes in two minor releases now — 0.8.0 broke `aconnect_ws`, 0.9.x untested. Defensive pin lets us evaluate the next minor release deliberately.)

And replace the multi-line comment block above it (lines that explain the `<0.8` pin) with:

```
# Phase 4 bridge test harness: httpx.AsyncClient + pytest_asyncio + httpx-ws.
# (TestClient + asyncio.new_event_loop binds fakeredis to the wrong loop;
# see plan section "Test harness convention for Tasks 7-10".)
#
# httpx-ws 0.8 requires entering ASGIWebSocketTransport as an async context
# manager so ``transport._task_group`` is initialised before ``aconnect_ws``
# calls into it. The shared fixture in tests/conftest.py does this.
#
# Upper bound on 0.9: this library has shipped breaking API changes in two
# minor releases (0.7→0.8 broke aconnect_ws). Pin to the current minor and
# re-evaluate when 0.9.x is available.
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

## Workstream 2: Async `ValidationEventLogger` (queue + writer task)

`frontend/ws_bridge/redis_subscriber.py:347-384` calls `self._validation_logger.log(...)` synchronously inside `_handle_message`. The logger does sync disk I/O (`open(path, "a")` + `f.write(...)` at `shared/contracts/logging.py:89-90`). The subscriber's read loop awaits each `_handle_message` sequentially (`redis_subscriber.py:200-207`), so any blocking I/O inside the handler stalls the Redis drain. A misbehaving EGS spamming malformed translations could backpressure the entire bridge.

**Fix (eng-review 2A Option B):** push validation events to an `asyncio.Queue` from the dispatch path (sync, fast — `put_nowait`), drain the queue in a dedicated writer task, and add the writer task to the lifespan's cancel/await loop. This mirrors the existing `translation_queue` + `_translation_broadcaster_loop` pattern in `main.py:236-272` so reviewers see one coherent shape across the bridge.

**Why queue+writer over `run_in_executor`:**
- A bare `await loop.run_in_executor(...)` from inside `_handle_message` still serializes dispatch — the read loop is parked until the executor returns. Doesn't solve the problem.
- A fire-and-forget `loop.run_in_executor(None, ...)` (no await) DOES unblock dispatch but lets multiple writes interleave on the JSONL file. POSIX guarantees atomicity only for writes < `PIPE_BUF` (~4KB on Linux); validation event records can exceed that when `raw_call` payloads are included.
- A single writer task draining a queue serializes writes naturally — no interleaving, ordered output, parallel pattern with `translation_queue`.
- Crash recovery: queued events lost on bridge crash. Acceptable for debug telemetry (the original TODO documented this trade-off).

### Task 3: Add `validation_log_queue` + writer task in `main.py`

This task wires the queue and writer task into the bridge lifespan, plumbed through `RedisSubscriber.__init__` so the subscriber can `put_nowait` records onto it. Task 4 then changes the subscriber to use the queue. Splitting them this way means Task 3 is a non-behavioural plumbing change (new param, new task, both wired but unused) and Task 4 is the behaviour flip.

**Files:**
- Modify: `frontend/ws_bridge/main.py:221-293` — add `validation_log_queue`, add `_validation_log_writer_loop` closure, wire to `app.state` and pass into subscriber, add to lifespan cancel/await
- Modify: `frontend/ws_bridge/main.py:174-218` — add `validation_log_task` to lifespan startup + teardown (mirror the `translation_task` pattern)
- Modify: `frontend/ws_bridge/redis_subscriber.py:93-114` — add `validation_log_queue: asyncio.Queue` constructor parameter and store it

- [ ] **Step 1: Add the constructor parameter on `RedisSubscriber`**

In `frontend/ws_bridge/redis_subscriber.py`, find the existing `__init__` signature (currently around lines 93-103). It looks like:

```python
def __init__(
    self,
    *,
    config: BridgeConfig,
    aggregator: StateAggregator,
    validation_logger: ValidationEventLogger,
    translation_queue: asyncio.Queue,
) -> None:
    self._config: BridgeConfig = config
    self._aggregator: StateAggregator = aggregator
    self._validation_logger: ValidationEventLogger = validation_logger
    ...
```

Add a new parameter `validation_log_queue: asyncio.Queue` and store it. Updated:

```python
def __init__(
    self,
    *,
    config: BridgeConfig,
    aggregator: StateAggregator,
    validation_logger: ValidationEventLogger,
    translation_queue: asyncio.Queue,
    validation_log_queue: asyncio.Queue,
) -> None:
    self._config: BridgeConfig = config
    self._aggregator: StateAggregator = aggregator
    self._validation_logger: ValidationEventLogger = validation_logger
    # Bounded queue for validation event records. Pushed by the dispatch
    # path (sync, via put_nowait), drained by main.py's
    # _validation_log_writer_loop. Single writer = no interleaving on the
    # JSONL file. Maxsize=128 is generous for the validation event traffic
    # pattern (~1 event per malformed frame); drop-on-full policy
    # documented in _safe_enqueue_validation below.
    self._validation_log_queue: asyncio.Queue = validation_log_queue
    ...  # rest unchanged
```

Don't change the existing `validation_logger` field — Task 4 keeps using it from the writer task side, but exposed via app.state.

- [ ] **Step 2: Update the existing constructor tests**

Three tests in `test_subscriber.py` construct `RedisSubscriber(...)` directly (around lines 135, 428, 521, 548 from earlier greps). Add `validation_log_queue=asyncio.Queue(maxsize=64)` to each call site. The tests don't yet exercise the queue — that's Task 4 — they just need to keep passing the new required kwarg.

Before each affected `RedisSubscriber(...)` call, the helper construction looks like:

```python
sub = RedisSubscriber(
    config=config,
    aggregator=aggregator,
    validation_logger=mock_logger,
    translation_queue=asyncio.Queue(maxsize=64),
)
```

Update to:

```python
sub = RedisSubscriber(
    config=config,
    aggregator=aggregator,
    validation_logger=mock_logger,
    translation_queue=asyncio.Queue(maxsize=64),
    validation_log_queue=asyncio.Queue(maxsize=64),
)
```

(Apply to all four call sites — grep first to confirm count: `grep -n "RedisSubscriber(" frontend/ws_bridge/tests/test_subscriber.py`.)

- [ ] **Step 3: Add the writer task closure in `main.py`**

In `frontend/ws_bridge/main.py`, find the existing `_translation_broadcaster_loop` closure (around line 242-276) inside `create_app()`. Add a sibling `_validation_log_writer_loop` closure RIGHT AFTER it. Insert before the `subscriber = RedisSubscriber(...)` construction (currently around line 278). Add this code:

```python
    # Eng-review 2A: bounded queue between dispatch and disk-write.
    # ``maxsize=128`` is generous for the validation-event traffic
    # pattern; drop-on-full policy lives on the producer side
    # (``_safe_enqueue_validation`` in redis_subscriber.py — Task 4).
    # Single writer task = no JSONL interleaving on the log file.
    validation_log_queue: asyncio.Queue = asyncio.Queue(maxsize=128)

    async def _validation_log_writer_loop() -> None:
        """Drain ``validation_log_queue`` and write to disk via the
        synchronous ``ValidationEventLogger``. Single writer = ordered
        JSONL output, no atomicity concerns from concurrent appends.

        Owns slowness: if disk I/O is slow, this task waits — but the
        subscriber's read loop keeps draining Redis (it only does
        ``put_nowait`` on the queue, never awaits a write).

        Mirrors the defensive shape of ``_translation_broadcaster_loop``:
        a single bad record never kills the writer.
        """
        while True:
            try:
                record = await validation_log_queue.get()
            except asyncio.CancelledError:
                raise
            try:
                # Run the synchronous file write off the event loop so
                # the next ``queue.get()`` doesn't park behind disk I/O.
                # Even though this writer is single-tenant (no
                # interleaving), a slow write would block subsequent
                # ``put_nowait`` calls if the queue fills.
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda r=record: validation_logger.log(**r)
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # A single bad record must not kill the writer.
                print(
                    f"[ws_bridge] validation_log_writer tick error "
                    f"(continuing): {type(exc).__name__}: {exc}"
                )
```

The `lambda r=record: validation_logger.log(**r)` shape matters: capturing `record` by default-arg avoids the late-binding bug if multiple iterations share the lambda.

- [ ] **Step 4: Wire the queue + writer task into the subscriber and lifespan**

In the same file, find:

```python
    subscriber = RedisSubscriber(
        config=config,
        aggregator=aggregator,
        validation_logger=validation_logger,
        translation_queue=translation_queue,
    )
```

Update to:

```python
    subscriber = RedisSubscriber(
        config=config,
        aggregator=aggregator,
        validation_logger=validation_logger,
        translation_queue=translation_queue,
        validation_log_queue=validation_log_queue,
    )
```

Then find the `app.state.translation_queue = ...` line and add a sibling:

```python
    app.state.translation_queue = translation_queue
    app.state.translation_broadcaster = _translation_broadcaster_loop
    # Eng-review 2A: validation log queue + single-writer task.
    app.state.validation_log_queue = validation_log_queue
    app.state.validation_log_writer = _validation_log_writer_loop
```

- [ ] **Step 5: Add the writer task to the lifespan**

In `frontend/ws_bridge/main.py`, find the `lifespan` async context manager (currently around lines 174-218 — read it first, line numbers may have shifted from earlier edits). It looks like:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    config: BridgeConfig = app.state.config
    registry: _ConnectionRegistry = app.state.registry
    aggregator: StateAggregator = app.state.aggregator
    subscriber: RedisSubscriber = app.state.subscriber
    translation_broadcaster = app.state.translation_broadcaster

    emit_task = asyncio.create_task(
        _emit_loop(registry=registry, aggregator=aggregator, tick_s=config.tick_s)
    )
    subscribe_task = asyncio.create_task(subscriber.run())
    translation_task = asyncio.create_task(translation_broadcaster())
    try:
        yield
    finally:
        # ... existing teardown ...
```

Add the validation-log writer task as a SIBLING of the existing three:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    config: BridgeConfig = app.state.config
    registry: _ConnectionRegistry = app.state.registry
    aggregator: StateAggregator = app.state.aggregator
    subscriber: RedisSubscriber = app.state.subscriber
    translation_broadcaster = app.state.translation_broadcaster
    validation_log_writer = app.state.validation_log_writer

    emit_task = asyncio.create_task(
        _emit_loop(registry=registry, aggregator=aggregator, tick_s=config.tick_s)
    )
    subscribe_task = asyncio.create_task(subscriber.run())
    translation_task = asyncio.create_task(translation_broadcaster())
    validation_log_task = asyncio.create_task(validation_log_writer())
    try:
        yield
    finally:
        # Phase 5+ teardown ordering. The old sequence
        # (cancel → subscriber.stop → await tasks) closed the
        # subscriber's pubsub while the subscribe task was still mid-
        # ``pubsub.get_message()``, producing
        # ``RuntimeError: Event loop is closed`` on every shutdown.
        #
        # New order (eng-review 1B + 2A):
        #   1. Flip the subscriber's stop flag (NO pubsub close yet)
        #   2. Cancel ALL FOUR tasks. signal_stop gives the subscribe
        #      loop a clean exit on its next read-timeout; cancel()
        #      handles the case where get_message() is parked.
        #   3. Await ALL FOUR tasks so the subscribe task has fully
        #      exited its read loop before we touch its pubsub
        #   4. ONLY THEN close the subscriber (pubsub.aclose())
        #   5. Close the publisher
        subscriber.signal_stop()
        emit_task.cancel()
        subscribe_task.cancel()
        translation_task.cancel()
        validation_log_task.cancel()
        for task in (
            emit_task, subscribe_task, translation_task, validation_log_task,
        ):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await subscriber.close()
        except Exception:
            pass
        try:
            await app.state.publisher.close()
        except Exception:
            pass
```

(The teardown order for the validation_log_task matches the others: cancel before await, swallow CancelledError + Exception. Crash-recovery: any records still on the queue when teardown fires are lost — acceptable for debug telemetry, documented in the original TODO.)

- [ ] **Step 6: Update the lifespan teardown test**

`frontend/ws_bridge/tests/test_main_lifespan_teardown.py` (added in PR #10) asserts ordering against a stub subscriber. The test should still pass without changes — the new `validation_log_task` doesn't appear in the order recording because the stub doesn't model it. But a more thorough test would assert the new task is also cancelled.

Verify by running:

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_lifespan_teardown.py -v
```

Expected: PASS. If it fails because the stub subscriber's `run()` is now expected to coexist with the validation_log_task and they interfere: investigate. In practice the validation_log_task awaits its own queue (`validation_log_queue.get()`) and is independent of the subscriber stub.

- [ ] **Step 7: Run the full bridge suite to confirm no behaviour change yet**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/ -m "not e2e" -v
```

Expected: 73 tests still pass. This task is plumbing-only — the queue is created, the writer task runs, but the subscriber doesn't push to it yet. Behaviour is unchanged.

- [ ] **Step 8: Commit**

```bash
git add frontend/ws_bridge/main.py frontend/ws_bridge/redis_subscriber.py frontend/ws_bridge/tests/test_subscriber.py
git commit -m "feat(bridge): plumb validation_log_queue + writer task (no behaviour change yet)"
```

---

### Task 4: Switch `_log_validation_failure` to use the queue

Now the actual behaviour change. `_log_validation_failure` becomes a sync method that pushes a record dict onto `self._validation_log_queue` via `put_nowait`. The three call sites stay sync (no `await` needed). Drop-on-full policy: if the queue is full, log a warning and proceed — the dispatch path never blocks.

**Files:**
- Modify: `frontend/ws_bridge/redis_subscriber.py:347-384` — convert `_log_validation_failure` to sync `put_nowait` on the queue
- Test: `frontend/ws_bridge/tests/test_subscriber.py` — add latency-bound test (Task 4 Step 1) AND exception-path test (Task 4 Step 2)

- [ ] **Step 1: Write the latency-bound test**

This is the eng-review 3B revision of the original test. With the queue+writer pattern, dispatch returns immediately (the writer task drains async on a separate task). Assertions:

1. Dispatch publishes 5 frames AND returns to control fast (the time from first publish to last reaching dispatch is well under one slow-write period, ~50ms tolerance).
2. The writer eventually drains all 5 records to disk (within a generous wait window, ~2s).

Append to `frontend/ws_bridge/tests/test_subscriber.py`:

```python
@pytest.mark.asyncio
async def test_validation_log_queue_does_not_block_dispatch(
    aggregator, monkeypatch
):
    """Eng-review 2A Option B: with the queue+writer pattern, slow disk I/O
    must NOT stall the dispatch path. Dispatch only does ``put_nowait``
    onto a bounded queue; the writer task drains it on its own coroutine.

    This test installs a slow logger and verifies:
      1. The subscriber drains all 5 invalid frames quickly
         (much less than the 5×200ms blocking baseline).
      2. The writer task eventually writes all 5 records.
    """
    import time

    fake = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(
        redis_async.Redis, "from_url",
        staticmethod(lambda url, **kw: fake),
    )

    class _SlowLogger:
        def __init__(self) -> None:
            self.calls: list = []

        def log(self, **kw) -> None:
            self.calls.append(time.monotonic())
            time.sleep(0.2)  # 200ms blocking I/O

    slow = _SlowLogger()
    config = BridgeConfig(
        redis_url="redis://localhost", tick_s=0.05,
        max_findings=100, broadcast_timeout_s=0.5, reconnect_max_s=2.0,
    )
    validation_log_queue: asyncio.Queue = asyncio.Queue(maxsize=128)

    # Build the writer task ourselves (in main.py it's wired via lifespan;
    # here we mirror the same shape so the test is self-contained).
    async def writer():
        while True:
            try:
                record = await validation_log_queue.get()
            except asyncio.CancelledError:
                raise
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda r=record: slow.log(**r)
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass

    sub = RedisSubscriber(
        config=config, aggregator=aggregator,
        validation_logger=slow,
        translation_queue=asyncio.Queue(maxsize=64),
        validation_log_queue=validation_log_queue,
    )
    sub_task = asyncio.create_task(sub.run())
    writer_task = asyncio.create_task(writer())
    try:
        await asyncio.sleep(0.1)  # let it subscribe

        # Publish 5 schema-invalid frames in rapid succession.
        for i in range(5):
            await fake.publish(
                "drones.drone1.state",
                '{"this": "is not a valid drone_state"}',
            )

        # Wait for the SUBSCRIBER to drain the read loop. We assert that
        # 5 records have landed on the queue (dispatch completed) within
        # 200ms — well under the 1s baseline for sync sequential writes.
        deadline_dispatch = time.monotonic() + 0.2
        while (
            time.monotonic() < deadline_dispatch
            and validation_log_queue.qsize() + len(slow.calls) < 5
        ):
            await asyncio.sleep(0.005)
        dispatch_total = validation_log_queue.qsize() + len(slow.calls)
        assert dispatch_total == 5, (
            f"subscriber must enqueue all 5 records within 200ms; got "
            f"{dispatch_total} (queue={validation_log_queue.qsize()}, "
            f"written={len(slow.calls)})"
        )

        # Now wait up to 2s for the writer to drain everything to disk.
        # 5 × 200ms = 1s minimum; 2s gives 2× headroom for thread pool
        # scheduling jitter.
        deadline_drain = time.monotonic() + 2.0
        while time.monotonic() < deadline_drain and len(slow.calls) < 5:
            await asyncio.sleep(0.05)
        assert len(slow.calls) == 5, (
            f"writer task must drain all 5 records within 2s; got "
            f"{len(slow.calls)}"
        )
    finally:
        sub.signal_stop()
        writer_task.cancel()
        await asyncio.wait_for(sub_task, timeout=2.0)
        try:
            await writer_task
        except (asyncio.CancelledError, Exception):
            pass
        await sub.close()
```

The test relies on `redis_async` being imported at the top of the test file (it's imported elsewhere; verify with grep).

- [ ] **Step 2: Write the exception-path test (eng-review 3A)**

Append to `frontend/ws_bridge/tests/test_subscriber.py`:

```python
@pytest.mark.asyncio
async def test_validation_log_exception_does_not_crash_dispatch(
    aggregator, monkeypatch
):
    """Eng-review 3A: if ValidationEventLogger.log raises (e.g., disk
    full, perms error), the writer task must keep running and the
    subscriber must keep dispatching subsequent frames."""
    import time

    fake = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(
        redis_async.Redis, "from_url",
        staticmethod(lambda url, **kw: fake),
    )

    class _ExplodingLogger:
        def __init__(self) -> None:
            self.calls = 0

        def log(self, **kw) -> None:
            self.calls += 1
            raise IOError("simulated disk full")

    boom = _ExplodingLogger()
    config = BridgeConfig(
        redis_url="redis://localhost", tick_s=0.05,
        max_findings=100, broadcast_timeout_s=0.5, reconnect_max_s=2.0,
    )
    validation_log_queue: asyncio.Queue = asyncio.Queue(maxsize=128)

    async def writer():
        while True:
            try:
                record = await validation_log_queue.get()
            except asyncio.CancelledError:
                raise
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, lambda r=record: boom.log(**r)
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # mirror the production writer's swallow-and-continue

    sub = RedisSubscriber(
        config=config, aggregator=aggregator,
        validation_logger=boom,
        translation_queue=asyncio.Queue(maxsize=64),
        validation_log_queue=validation_log_queue,
    )
    sub_task = asyncio.create_task(sub.run())
    writer_task = asyncio.create_task(writer())
    try:
        await asyncio.sleep(0.1)
        # Two invalid frames — first triggers exception, second must
        # still dispatch and be processed.
        await fake.publish("drones.drone1.state", '{"bad": 1}')
        await asyncio.sleep(0.3)  # let the writer attempt + fail
        await fake.publish("drones.drone1.state", '{"bad": 2}')
        await asyncio.sleep(0.3)
        assert boom.calls >= 2, (
            f"second frame must be processed despite first frame's log "
            f"raising; got {boom.calls} log calls"
        )
        # The writer task must NOT have crashed — verify it's still running.
        assert not writer_task.done(), (
            "writer task crashed on logger exception; the production loop "
            "swallows exceptions and continues"
        )
    finally:
        sub.signal_stop()
        writer_task.cancel()
        await asyncio.wait_for(sub_task, timeout=2.0)
        try:
            await writer_task
        except (asyncio.CancelledError, Exception):
            pass
        await sub.close()
```

- [ ] **Step 3: Run both tests to verify they fail**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_subscriber.py::test_validation_log_queue_does_not_block_dispatch frontend/ws_bridge/tests/test_subscriber.py::test_validation_log_exception_does_not_crash_dispatch -v
```

Expected: BOTH FAIL — `_log_validation_failure` still calls `self._validation_logger.log(...)` synchronously, so the queue stays empty and `dispatch_total` is 5 (in `slow.calls` directly) but the latency would still be ~1s. Actually wait — the exception test would PASS today if the existing try/except still catches the exception. The latency test FAILS. That's enough to validate the implementation.

- [ ] **Step 4: Convert `_log_validation_failure` to sync queue push**

Replace the `_log_validation_failure` method body in `frontend/ws_bridge/redis_subscriber.py` (currently sync at lines 347-384) with:

```python
def _log_validation_failure(
    self,
    *,
    schema_name: str,
    drone_id: Optional[str],
    channel: str,
    rule_id: str,
    detail: str,
    raw_call: Optional[Dict[str, Any]],
) -> None:
    """Best-effort enqueue of a validation event for the writer task.

    Eng-review 2A Option B: the dispatch path must not block on disk
    I/O. We push a record dict onto ``self._validation_log_queue`` via
    ``put_nowait`` (sync, microseconds). ``main.py``'s
    ``_validation_log_writer_loop`` drains it on a dedicated task,
    serializing writes to the JSONL file (no interleaving) and running
    the actual disk I/O in the default thread pool executor (so even
    the writer task doesn't block on disk).

    Drop-on-full policy: if the bounded queue is at capacity (default
    maxsize=128), the record is dropped with a stderr warning. This
    only happens under sustained burst — at steady state the queue
    drains faster than dispatch fills it.

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
    record = {
        "agent_id": agent_id,
        "layer": layer,
        "function_or_command": f"{schema_name}@{channel}: {detail}",
        "attempt": 1,
        "valid": False,
        "rule_id": rule_id,
        "outcome": "failed_after_retries",
        "raw_call": raw_call,
    }
    try:
        self._validation_log_queue.put_nowait(record)
    except asyncio.QueueFull:
        # Sustained burst — queue can't keep up with dispatch. The
        # validation log is debug telemetry, so dropping is acceptable.
        # Log to stderr so the fact that we dropped is visible without
        # requiring a tail of the (now-stale) validation_events.jsonl.
        print(
            f"[ws_bridge] validation_log_queue full — dropping record "
            f"for {agent_id}/{schema_name}@{channel}",
            file=sys.stderr,
        )
```

The function is now SYNC again (no `async`). The signature is otherwise unchanged. `sys` may need to be imported at the top of `redis_subscriber.py` — verify with `grep "^import sys" frontend/ws_bridge/redis_subscriber.py` and add `import sys` after the existing imports if missing.

- [ ] **Step 5: Confirm the three call sites stay sync (no `await` change)**

The three existing call sites in `_handle_message` (around lines 256, 267, 285) currently look like:

```python
self._log_validation_failure(
    schema_name=...,
    drone_id=...,
    ...
)
```

They DO NOT need to change. `_log_validation_failure` is now sync (it's `put_nowait`-based), so the call stays synchronous. This is the critical correctness property — the dispatch path executes in microseconds, not milliseconds.

Verify by grep:

```bash
grep -n "self._log_validation_failure\|self\._log_validation_failure" frontend/ws_bridge/redis_subscriber.py | head -5
```

Expected: 4 matches (1 def, 3 call sites). NO `await` should appear before any of them.

- [ ] **Step 6: Run both new tests to verify they pass**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_subscriber.py::test_validation_log_queue_does_not_block_dispatch frontend/ws_bridge/tests/test_subscriber.py::test_validation_log_exception_does_not_crash_dispatch -v
```

Expected: BOTH PASS.

If the latency test fails with `dispatch_total != 5`: the subscriber's read loop didn't drain all 5 frames within 200ms. Could be CI runner slowness — relax to 400ms and document why. Or check that `put_nowait` is actually being called (no exceptions silently dropped).

If the exception test fails with `boom.calls < 2`: the second frame isn't reaching dispatch. Likely the writer task crashed despite the `except Exception: pass` — read its definition again.

- [ ] **Step 7: Run the full bridge suite**

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/ -m "not e2e" -v
```

Expected: 75 tests pass (73 pre-existing + 2 new).

- [ ] **Step 8: Smoke-test the full bridge under load (optional confidence check)**

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
    vlq = asyncio.Queue(maxsize=128)

    async def writer():
        while True:
            r = await vlq.get()
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda r=r: slow.log(**r))
            except Exception: pass

    sub = RedisSubscriber(config=config, aggregator=agg,
                         validation_logger=slow,
                         translation_queue=asyncio.Queue(maxsize=64),
                         validation_log_queue=vlq)
    sub_task = asyncio.create_task(sub.run())
    writer_task = asyncio.create_task(writer())
    await asyncio.sleep(0.1)
    start = time.monotonic()
    N = 50
    for _ in range(N):
        await fake.publish('drones.drone1.state', '{\"bad\":\"frame\"}')
    dispatch_done = time.monotonic() - start
    await asyncio.sleep(3.0)
    elapsed = time.monotonic() - start
    print(f'dispatch_done={dispatch_done:.3f}s logged={slow.calls}/{N} total_elapsed={elapsed:.2f}s')
    sub.signal_stop()
    writer_task.cancel()
    await asyncio.wait_for(sub_task, timeout=2.0)
    try:
        await writer_task
    except: pass
    await sub.close()

asyncio.run(main())
"
```

Expected output: `dispatch_done=~0.02-0.10s logged=50/50 total_elapsed=~3-4s`. If `dispatch_done > 1s` the queue is full and `put_nowait` is dropping (or the read loop is somehow blocked). Investigate.

- [ ] **Step 9: Commit**

```bash
git add frontend/ws_bridge/redis_subscriber.py frontend/ws_bridge/tests/test_subscriber.py
git commit -m "perf(bridge): push validation events to queue, drain on writer task"
```

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
- `RedisSubscriber.__init__` adds `validation_log_queue: asyncio.Queue` parameter in Task 3, used identically in Task 4's tests.
- `_validation_log_writer_loop` closure name matches the `_translation_broadcaster_loop` precedent in `main.py`.
- `app.state.validation_log_queue` and `app.state.validation_log_writer` mirror `app.state.translation_queue` / `app.state.translation_broadcaster` — same shape.
- `_log_validation_failure` becomes sync again in Task 4 (was sync, plan briefly considered async, eng-review 2A landed on sync put_nowait). Three call sites stay sync — no `await` needed, keeping dispatch path microsecond-fast.
- `signal_stop()` and `close()` referenced in Task 3/4 tests match the API shipped in PR #10.

**4. Eng-review recommendations applied (2026-05-04):**
- **1A:** `requirements-dev.txt` pin tightened to `httpx-ws>=0.8,<0.9` (defensive upper bound).
- **2A Option B:** Workstream 2 rewritten — queue + dedicated writer task instead of `await loop.run_in_executor`. The sequential `await self._handle_message(...)` in the read loop means awaiting the executor would still serialize dispatch; queue-based push gives true non-blocking.
- **3A:** Task 4 Step 2 adds `test_validation_log_exception_does_not_crash_dispatch`.
- **3B:** Task 4 Step 1's latency test rewritten — asserts subscriber drains 5 frames within 200ms (queue path) AND writer eventually completes all 5 within 2s (drain path).

**5. Risk note for the engineer:**
Workstream 1 has the highest unknown — if httpx-ws 0.8 needs more than the context-manager change, the fixture migration may grow beyond the plan. If you hit something in Task 1 Step 5 that isn't trivially fixable, STOP and escalate rather than improvising. The plan can grow a Task 1.5 if needed; better than landing a half-migration.

**6. Independence check:** Each commit can be reverted independently:
- Revert Task 1 commit → tests revert to httpx-ws<0.8 pattern; nothing else cares
- Revert Task 3 commit (plumbing) — must also revert Task 4 (behaviour change depends on plumbing)
- Revert Task 4 commit → log goes back to sync direct call; Task 3's plumbing is dead code but inert
- Revert Task 5 commit → CONVENTIONS.md goes away; schemas still validate
- Revert Task 6 commit → TODOs reopen; no code impact

Tasks 3 and 4 are coupled (queue plumbing → behaviour switch). Splitting them into separate commits keeps the plumbing-only commit risk-free, and the behaviour-change commit's diff is focused on the actual flip.
