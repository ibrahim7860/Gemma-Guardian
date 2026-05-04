"""Integration tests for the Phase 2 RedisSubscriber against fakeredis.

The subscriber owns the asyncio task that reads from `egs.state`,
`drones.*.state`, and `drones.*.findings`, validates each payload against the
matching contract schema, and dispatches into the StateAggregator. These tests
drive that loop end-to-end with `fakeredis.aioredis.FakeRedis` standing in for
real Redis.

fakeredis design constraint: fakeredis 2.35 async pub/sub does NOT share
delivery state across separate `FakeRedis` instances even when they share a
`FakeServer` or are constructed with the same URL. Subscribers and publishers
must use the SAME `FakeRedis` instance for messages to be delivered. We
therefore monkeypatch `redis.asyncio.Redis.from_url` to return a single
test-controlled `FakeRedis`; the subscriber task and the test publishers all
operate against that one instance.

All tests are `async def` and decorated with `@pytest.mark.asyncio`; the repo
has no `asyncio_mode = "auto"` config, so explicit decoration is required.
"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest
from fakeredis.aioredis import FakeRedis

from shared.contracts.logging import ValidationEventLogger

from frontend.ws_bridge.aggregator import StateAggregator
from frontend.ws_bridge.config import BridgeConfig
from frontend.ws_bridge.redis_subscriber import RedisSubscriber

# ---- fixtures ---------------------------------------------------------------

_FIXTURES_ROOT = (
    Path(__file__).parent.parent.parent.parent
    / "shared" / "schemas" / "fixtures" / "valid"
)
_SEED_PATH = _FIXTURES_ROOT / "websocket_messages" / "01_state_update.json"
_DRONE_FIXTURE = _FIXTURES_ROOT / "drone_state" / "01_active.json"
_FINDING_FIXTURE = _FIXTURES_ROOT / "finding" / "01_victim.json"
_EGS_FIXTURE = _FIXTURES_ROOT / "egs_state" / "01_active.json"


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text())


@pytest.fixture
def seed_envelope() -> Dict[str, Any]:
    return _load(_SEED_PATH)


@pytest.fixture
def egs_payload() -> Dict[str, Any]:
    return _load(_EGS_FIXTURE)


@pytest.fixture
def drone_payload() -> Dict[str, Any]:
    return _load(_DRONE_FIXTURE)


@pytest.fixture
def finding_payload() -> Dict[str, Any]:
    return _load(_FINDING_FIXTURE)


@pytest.fixture
def aggregator(seed_envelope: Dict[str, Any]) -> StateAggregator:
    return StateAggregator(max_findings=50, seed_envelope=seed_envelope)


@pytest.fixture
def config() -> BridgeConfig:
    return BridgeConfig(
        redis_url="redis://localhost:6379",
        tick_s=1.0,
        max_findings=50,
        reconnect_max_s=10.0,
        broadcast_timeout_s=0.5,
    )


@pytest.fixture
def mock_logger() -> MagicMock:
    """A MagicMock standing in for ValidationEventLogger.

    We use `spec=ValidationEventLogger` so attribute access is type-checked
    against the real API; tests assert on `.log` calls.
    """
    return MagicMock(spec=ValidationEventLogger)


# ---- helpers ---------------------------------------------------------------

async def _wait_for(predicate, *, timeout: float = 2.0, interval: float = 0.02) -> bool:
    """Poll ``predicate()`` until it returns truthy or timeout elapses."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


async def _start_subscriber(
    monkeypatch: pytest.MonkeyPatch,
    config: BridgeConfig,
    aggregator: StateAggregator,
    logger: ValidationEventLogger,
) -> tuple:
    """Patch redis.asyncio.Redis.from_url to return a shared FakeRedis instance,
    construct the subscriber, kick off its run() task, and return
    (fake_redis, subscriber, task, validation_log_queue) for the test to drive.

    Caller must call `subscriber.signal_stop()`, await the task, then
    `await subscriber.close()` for clean shutdown (the `_stop_subscriber`
    helper handles this; cancellation is the fallback).
    """
    fake = FakeRedis()

    def _from_url(url, *args, **kwargs):  # noqa: ANN001, ARG001
        return fake

    import redis.asyncio as redis_async
    monkeypatch.setattr(redis_async.Redis, "from_url", staticmethod(_from_url))

    validation_log_queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    subscriber = RedisSubscriber(
        config=config, aggregator=aggregator, validation_logger=logger,
        validation_log_queue=validation_log_queue,
    )
    task = asyncio.create_task(subscriber.run())
    # Give the subscriber a moment to call from_url, open pubsub, and psubscribe.
    # If we publish before the psubscribe registration is in place, the message
    # is dropped on the floor by fakeredis (no buffering on un-subscribed channels).
    await asyncio.sleep(0.1)
    return fake, subscriber, task, validation_log_queue


async def _stop_subscriber(subscriber: RedisSubscriber, task: asyncio.Task) -> None:
    subscriber.signal_stop()
    try:
        await asyncio.wait_for(task, timeout=2.0)  # let the run loop exit on the flag
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    await subscriber.close()


# ---- 0. Sanity: psubscribe + publish round-trip works in fakeredis 2.35 ----

@pytest.mark.asyncio
async def test_fakeredis_psubscribe_roundtrip():
    """Trivial test verifying the test infrastructure works.

    Confirms fakeredis 2.35 supports psubscribe -> publish -> get_message
    against a single FakeRedis instance, which is the foundation our subscriber
    tests rely on.
    """
    r = FakeRedis()
    pubsub = r.pubsub()
    await pubsub.psubscribe("drones.*.state")
    await pubsub.subscribe("egs.state")
    await asyncio.sleep(0.05)

    await r.publish("drones.drone7.state", "pattern_payload")
    await r.publish("egs.state", "literal_payload")

    received: List[Dict[str, Any]] = []
    for _ in range(20):
        m = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.05)
        if m is not None:
            received.append(m)
        if len(received) >= 2:
            break

    channels = {m["channel"] for m in received}
    assert b"drones.drone7.state" in channels
    assert b"egs.state" in channels
    await pubsub.aclose()


# ---- 1. egs.state payload updates egs bucket -------------------------------

@pytest.mark.asyncio
async def test_egs_state_payload_updates_egs_bucket(
    monkeypatch, config, aggregator, mock_logger, egs_payload, seed_envelope,
):
    fake, subscriber, task, _ = await _start_subscriber(
        monkeypatch, config, aggregator, mock_logger,
    )
    try:
        # Pre-condition: aggregator's egs bucket reflects the seed.
        assert aggregator._egs["mission_id"] == seed_envelope["egs_state"]["mission_id"]

        await fake.publish("egs.state", json.dumps(egs_payload))
        ok = await _wait_for(
            lambda: aggregator._egs.get("mission_id") == egs_payload["mission_id"],
        )
        assert ok, "egs bucket did not pick up published payload"
        mock_logger.log.assert_not_called()
    finally:
        await _stop_subscriber(subscriber, task)


# ---- 2. drones.<id>.state payload matches pattern, drone_id parsed ---------

@pytest.mark.asyncio
async def test_drone_state_payload_updates_drone_bucket(
    monkeypatch, config, aggregator, mock_logger, drone_payload,
):
    fake, subscriber, task, _ = await _start_subscriber(
        monkeypatch, config, aggregator, mock_logger,
    )
    try:
        payload = deepcopy(drone_payload)
        payload["drone_id"] = "drone7"
        await fake.publish("drones.drone7.state", json.dumps(payload))

        ok = await _wait_for(lambda: "drone7" in aggregator._drones)
        assert ok, "drone7 not added to bucket"
        assert aggregator._drones["drone7"]["drone_id"] == "drone7"
        mock_logger.log.assert_not_called()
    finally:
        await _stop_subscriber(subscriber, task)


# ---- 3. drones.<id>.findings: multiple drones flow through -----------------

@pytest.mark.asyncio
async def test_finding_payload_added_to_findings(
    monkeypatch, config, aggregator, mock_logger, finding_payload,
):
    fake, subscriber, task, _ = await _start_subscriber(
        monkeypatch, config, aggregator, mock_logger,
    )
    try:
        f1 = deepcopy(finding_payload)
        f1["finding_id"] = "f_drone1_001"
        f1["source_drone_id"] = "drone1"

        f2 = deepcopy(finding_payload)
        f2["finding_id"] = "f_drone2_002"
        f2["source_drone_id"] = "drone2"

        await fake.publish("drones.drone1.findings", json.dumps(f1))
        await fake.publish("drones.drone2.findings", json.dumps(f2))

        ok = await _wait_for(
            lambda: {"f_drone1_001", "f_drone2_002"}.issubset(set(aggregator._findings.keys())),
        )
        assert ok, f"expected both findings; got {list(aggregator._findings.keys())}"
        mock_logger.log.assert_not_called()
    finally:
        await _stop_subscriber(subscriber, task)


# ---- 4. invalid JSON: drop, log, aggregator unchanged ----------------------

@pytest.mark.asyncio
async def test_invalid_json_dropped_and_logged(
    monkeypatch, config, aggregator, mock_logger, seed_envelope,
):
    fake, subscriber, task, validation_log_queue = await _start_subscriber(
        monkeypatch, config, aggregator, mock_logger,
    )
    try:
        baseline_egs = deepcopy(aggregator._egs)
        baseline_drones = deepcopy(aggregator._drones)
        baseline_findings = list(aggregator._findings.keys())

        # Bad bytes — not valid JSON at all.
        await fake.publish("egs.state", b"\xff\xfe not even close to json {{{")
        # Wait for the message to be processed (record enqueued on validation_log_queue).
        ok = await _wait_for(lambda: not validation_log_queue.empty())
        assert ok, "expected a validation record to be enqueued for invalid JSON"

        # Aggregator unchanged.
        assert aggregator._egs == baseline_egs
        assert aggregator._drones == baseline_drones
        assert list(aggregator._findings.keys()) == baseline_findings
    finally:
        await _stop_subscriber(subscriber, task)


# ---- 5. schema-invalid: drop, log with STRUCTURAL_VALIDATION_FAILED --------

@pytest.mark.asyncio
async def test_schema_invalid_payload_dropped_and_logged(
    monkeypatch, config, aggregator, mock_logger,
):
    fake, subscriber, task, validation_log_queue = await _start_subscriber(
        monkeypatch, config, aggregator, mock_logger,
    )
    try:
        baseline_egs = deepcopy(aggregator._egs)

        # Valid JSON but missing required egs_state fields.
        bad_payload = {"mission_id": "demo", "i_am_not": "valid"}
        await fake.publish("egs.state", json.dumps(bad_payload))

        ok = await _wait_for(lambda: not validation_log_queue.empty())
        assert ok, "expected a validation record to be enqueued for schema-invalid payload"

        # Aggregator unchanged.
        assert aggregator._egs == baseline_egs

        # The enqueued record must carry rule_id="STRUCTURAL_VALIDATION_FAILED".
        records: List[Dict[str, Any]] = []
        while not validation_log_queue.empty():
            records.append(validation_log_queue.get_nowait())
        rule_ids = [r.get("rule_id") for r in records]
        assert "STRUCTURAL_VALIDATION_FAILED" in rule_ids, (
            f"expected STRUCTURAL_VALIDATION_FAILED in rule_ids; got {rule_ids}"
        )
    finally:
        await _stop_subscriber(subscriber, task)


# ---- 6. reconnect after disconnect ----------------------------------------

class _BreakablePubSub:
    """Wraps a real FakeRedis pubsub. After ``break_now()``, every
    ``get_message`` call raises ``ConnectionError`` once, then the wrapper
    is considered broken and stays broken (subscriber should reconnect via
    a fresh ``from_url``).
    """

    def __init__(self, real_pubsub) -> None:
        self._real = real_pubsub
        self._broken = False

    def break_now(self) -> None:
        self._broken = True

    async def subscribe(self, *args, **kwargs):
        return await self._real.subscribe(*args, **kwargs)

    async def psubscribe(self, *args, **kwargs):
        return await self._real.psubscribe(*args, **kwargs)

    async def unsubscribe(self, *args, **kwargs):
        return await self._real.unsubscribe(*args, **kwargs)

    async def punsubscribe(self, *args, **kwargs):
        return await self._real.punsubscribe(*args, **kwargs)

    async def get_message(self, *args, **kwargs):
        if self._broken:
            raise ConnectionError("simulated drop")
        return await self._real.get_message(*args, **kwargs)

    async def aclose(self):
        return await self._real.aclose()


class _FakeRedisFacade:
    """Wraps a FakeRedis so we can swap in a ``_BreakablePubSub`` and forward
    ``publish`` / ``aclose``. The subscriber sees this as ``redis.asyncio.Redis``."""

    def __init__(self, fake: FakeRedis) -> None:
        self._fake = fake
        self._breakable: Optional[_BreakablePubSub] = None

    def pubsub(self):
        self._breakable = _BreakablePubSub(self._fake.pubsub())
        return self._breakable

    @property
    def breakable(self) -> Optional[_BreakablePubSub]:
        return self._breakable

    @property
    def fake(self) -> FakeRedis:
        return self._fake

    async def publish(self, *args, **kwargs):
        return await self._fake.publish(*args, **kwargs)

    async def aclose(self):
        return await self._fake.aclose()


@pytest.mark.asyncio
async def test_reconnect_after_disconnect(
    monkeypatch, config, aggregator, mock_logger, egs_payload,
):
    """Subscriber must catch a connection drop and re-subscribe.

    fakeredis 2.35's async pubsub doesn't react to ``connection_pool.disconnect``
    at the application layer (everything is in-process), so we simulate the
    drop by wrapping the pubsub in a ``_BreakablePubSub`` whose
    ``get_message`` raises ``ConnectionError`` once we flip a flag. The
    ``from_url`` stub returns facade #1 first, then facade #2 on reconnect.
    A publish into facade #2 after the reconnect flows through to the
    aggregator, proving the loop recovered.
    """
    facade1 = _FakeRedisFacade(FakeRedis())
    facade2 = _FakeRedisFacade(FakeRedis())
    instances = iter([facade1, facade2])

    def _from_url(url, *args, **kwargs):  # noqa: ANN001, ARG001
        try:
            return next(instances)
        except StopIteration:
            return facade2

    import redis.asyncio as redis_async
    monkeypatch.setattr(redis_async.Redis, "from_url", staticmethod(_from_url))

    # Tighten backoff so the test doesn't sleep for full seconds.
    fast_config = BridgeConfig(
        redis_url=config.redis_url,
        tick_s=config.tick_s,
        max_findings=config.max_findings,
        reconnect_max_s=0.2,
        broadcast_timeout_s=config.broadcast_timeout_s,
    )

    subscriber = RedisSubscriber(
        config=fast_config, aggregator=aggregator, validation_logger=mock_logger,
        validation_log_queue=asyncio.Queue(maxsize=64),
    )
    task = asyncio.create_task(subscriber.run())
    try:
        # Wait until the subscriber has called pubsub() on facade1.
        ok = await _wait_for(lambda: facade1.breakable is not None, timeout=2.0)
        assert ok, "subscriber never called pubsub() on facade1"
        await asyncio.sleep(0.05)  # let psubscribe register

        # Sanity: messages flow through facade1.
        await facade1.publish("egs.state", json.dumps(egs_payload))
        ok = await _wait_for(
            lambda: aggregator._egs.get("mission_id") == egs_payload["mission_id"],
            timeout=1.5,
        )
        assert ok, "facade1 path did not work pre-disconnect"

        # Trip the disconnect.
        facade1.breakable.break_now()

        # Wait for the subscriber to call pubsub() on facade2 (reconnect happened).
        ok = await _wait_for(lambda: facade2.breakable is not None, timeout=3.0)
        assert ok, "subscriber did not reconnect to facade2"
        await asyncio.sleep(0.1)  # let the new psubscribe register

        # Publish through facade2; aggregator should see the new mission_id.
        new_payload = deepcopy(egs_payload)
        new_payload["mission_id"] = "post_reconnect_mission"

        async def _seen() -> bool:
            deadline = asyncio.get_event_loop().time() + 3.0
            while asyncio.get_event_loop().time() < deadline:
                await facade2.publish("egs.state", json.dumps(new_payload))
                if aggregator._egs.get("mission_id") == "post_reconnect_mission":
                    return True
                await asyncio.sleep(0.1)
            return False

        assert await _seen(), (
            "subscriber did not deliver via facade2; "
            f"final mission_id = {aggregator._egs.get('mission_id')!r}"
        )
    finally:
        await _stop_subscriber(subscriber, task)


# ---- 7. backoff helper unit test ------------------------------------------

def test_next_backoff_sequence():
    """Pure helper: exponential doubling capped at the ceiling."""
    from frontend.ws_bridge.redis_subscriber import _next_backoff

    cap = 10.0
    seq = []
    cur = 0.0
    for _ in range(8):
        cur = _next_backoff(cur, cap)
        seq.append(cur)
    # First step jumps to 1; doubling 1,2,4,8 then capped at 10.
    assert seq == [1.0, 2.0, 4.0, 8.0, 10.0, 10.0, 10.0, 10.0]


def test_next_backoff_cap_smaller_than_one():
    """If the cap is below 1s, the first step clamps to the cap."""
    from frontend.ws_bridge.redis_subscriber import _next_backoff

    assert _next_backoff(0.0, 0.2) == 0.2
    assert _next_backoff(0.2, 0.2) == 0.2


# ---- 8. signal_stop() sets flag without closing pubsub ---------------------

@pytest.mark.asyncio
async def test_signal_stop_only_sets_flag_does_not_close_pubsub(
    monkeypatch, config, aggregator, mock_logger,
):
    """signal_stop() must set _stopping=True without touching pubsub.

    The lifespan handler relies on this so it can await the run task
    (which exits cleanly because the flag is set) before closing the
    pubsub via close().
    """
    fake = FakeRedis()

    def _from_url(url, *args, **kwargs):  # noqa: ANN001, ARG001
        return fake

    import redis.asyncio as redis_async
    monkeypatch.setattr(redis_async.Redis, "from_url", staticmethod(_from_url))

    sub = RedisSubscriber(
        config=config,
        aggregator=aggregator,
        validation_logger=mock_logger,
        validation_log_queue=asyncio.Queue(maxsize=64),
    )
    task = asyncio.create_task(sub.run())
    await asyncio.sleep(0.05)  # let it subscribe

    sub.signal_stop()
    assert sub._stopping is True
    # pubsub is still open at this point — we only signalled.
    assert sub._pubsub is not None

    # Now the run task should exit on its own.
    await asyncio.wait_for(task, timeout=2.0)

    # And close() actually tears down.
    await sub.close()
    assert sub._pubsub is None


# ---- 9. close() is idempotent -----------------------------------------------

@pytest.mark.asyncio
async def test_close_is_idempotent(monkeypatch, config, aggregator, mock_logger):
    """close() must be safe to call twice. Lifespan cleanup paths
    can re-enter close() under exception conditions."""
    sub = RedisSubscriber(
        config=config,
        aggregator=aggregator,
        validation_logger=mock_logger,
        validation_log_queue=asyncio.Queue(maxsize=64),
    )
    # Never run — just close twice.
    await sub.close()
    await sub.close()  # must not raise
    assert sub._pubsub is None
    assert sub._client is None


# ---- 10. latency-bound: validation log queue does not block dispatch ---------

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

    import fakeredis.aioredis
    import redis.asyncio as redis_async

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


# ---- 11. exception-path: logger exception does not crash dispatch ------------

@pytest.mark.asyncio
async def test_validation_log_exception_does_not_crash_dispatch(
    aggregator, monkeypatch
):
    """Eng-review 3A: if ValidationEventLogger.log raises (e.g., disk
    full, perms error), the writer task must keep running and the
    subscriber must keep dispatching subsequent frames."""
    import time

    import fakeredis.aioredis
    import redis.asyncio as redis_async

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
