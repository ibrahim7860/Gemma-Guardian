# Phase 2: Redis-backed WebSocket Bridge — Design Spec

**Date:** 2026-05-01
**Owner:** Person 4 (Ibrahim)
**Branch:** `feat/ws-bridge-skeleton` (continues from Phase 1)
**Predecessor:** [`2026-04-30-integration-contracts-design.md`](2026-04-30-integration-contracts-design.md)
**Replaces:** Phase 1A `_ticker` fake-publisher in `frontend/ws_bridge/main.py`

## Goal

Replace the Phase 1A fake-publisher inside `frontend/ws_bridge/main.py` with a real Redis pub/sub subscriber that aggregates per-drone state and findings into the `state_update` envelope defined by Contract 8 of `docs/20-integration-contracts.md`. The Flutter dashboard from Phase 1B continues to consume the same envelope at the same `ws://localhost:9090` endpoint at the same 1Hz cadence; nothing on the dashboard side needs to change.

The output of this phase is a bridge that, given a running Redis with valid contract messages on `egs.state`, `drones.*.state`, and `drones.*.findings`, produces schema-valid `state_update` envelopes that reflect upstream activity in real time, plus a standalone fake-producer script so Person 4 can develop and Playwright-test before Persons 1 and 3 ship their producers.

## Non-goals

- Operator command → Redis republish (Phase 3, paired with the multilingual command box)
- `command_translation`, `operator_command_dispatch`, `finding_approval` round-trips (Phase 3)
- Camera frame rendering (`drones.*.camera`)
- Mesh adjacency visualization (`mesh.adjacency_matrix`)
- `mission_id` change-detection across `egs.state` reboots
- Horizontal scaling, multiple bridge instances

## Architecture

```
                    ┌────────────────────────────────────────────────┐
                    │  frontend/ws_bridge/                           │
Redis pub/sub ──────►   redis_subscriber.py  ─update→  aggregator.py │
(egs.state,         │   (psubscribe loop +      writes  (3 buckets)  │
 drones.*.state,    │    backoff reconnect)                ▲          │
 drones.*.findings) │                                      │ snapshot │
                    │                                  1Hz │ (read)   │
                    │   main.py ── _emit_loop ─────────────┘          │
                    │   (FastAPI lifespan) ── broadcast() ──┐         │
                    └───────────────────────────────────────┼─────────┘
                                                            │
                                                            ▼
                                              Flutter dashboard (Phase 1B)
                                                  ws://localhost:9090
```

**Decoupling:** subscriber writes to buckets at the rate Redis delivers messages; emit loop reads buckets at a fixed 1Hz. A burst of findings updates buckets but produces only one WS frame per second. This matches Contract 8's "single envelope per second" guarantee.

**Process boundary:** one FastAPI process. Three asyncio tasks: subscribe loop, emit loop, one task per WS connection. Shared state behind a single `asyncio.Lock`.

## Components

### `frontend/ws_bridge/config.py` (new)

Single source of truth for tunables. `BridgeConfig` dataclass loaded from env vars on startup.

```
REDIS_URL                default redis://localhost:6379
BRIDGE_TICK_S            default 1.0
BRIDGE_MAX_FINDINGS      default 50
BRIDGE_RECONNECT_MAX_S   default 10
BRIDGE_BROADCAST_TIMEOUT_S default 0.5  (per-client send timeout)
```

### `frontend/ws_bridge/aggregator.py` (new)

Pure logic, no I/O. Holds the three buckets, owns retention and dedup.

```python
class StateAggregator:
    def __init__(self, *, max_findings: int, seed_envelope: dict) -> None: ...
    def update_egs_state(self, payload: dict) -> None: ...
    def update_drone_state(self, drone_id: str, payload: dict) -> None: ...
    def add_finding(self, payload: dict) -> None: ...   # dedup by finding_id
    def snapshot(self, *, timestamp_iso: str) -> dict:
        """Return a state_update envelope. Schema-valid even on empty buckets
        (initial buckets seeded from seed_envelope)."""
```

Buckets:
- `_egs: dict` (latest `egs.state` payload, defaults to `seed_envelope["egs_state"]`)
- `_drones: Dict[str, dict]` (drone_id → latest `drone_state` payload)
- `_findings: "collections.OrderedDict[str, dict]"` (finding_id → finding payload, capped at `max_findings`, FIFO eviction by insertion order)

`add_finding` semantics:
- If `finding_id` already present: replace the value in place. Insertion order is preserved (dict assignment to an existing key does not change OrderedDict position). The dashboard sees the latest version of a finding (e.g., upgraded severity) without it jumping to the top of the list.
- If `finding_id` is new and bucket is at `max_findings`: evict the oldest entry via `popitem(last=False)`, then insert the new one at the end.
- If `finding_id` is new and bucket has room: insert at the end.

### `frontend/ws_bridge/redis_subscriber.py` (new)

Owns the asyncio subscribe task. Subscribes to:
- `egs.state` (literal) → `egs_state` schema
- `drones.*.state` (pattern) → `drone_state` schema, drone_id parsed from channel
- `drones.*.findings` (pattern) → `finding` schema

Channel patterns come from `shared.contracts.topics`; do not hard-code. Use the constants `EGS_STATE`, `PER_DRONE_STATE`, `PER_DRONE_FINDINGS` and replace `{drone_id}` with `*` for the subscribe pattern.

```python
class RedisSubscriber:
    def __init__(self, *, config: BridgeConfig, aggregator: StateAggregator,
                 validation_logger: ValidationEventLogger) -> None: ...
    async def run(self) -> None:
        """Connect with backoff, psubscribe, dispatch messages.
        On any RedisError: log + sleep with exponential backoff, retry."""
```

Per-message flow:
1. Decode JSON → catch `json.JSONDecodeError` → log validation event with `rule_id="STRUCTURAL_VALIDATION_FAILED"`, `field_path="<root>"`, channel in metadata, drop.
2. `validate(schema_name, payload)` → on failure, log validation event with the structural error, drop.
3. Dispatch by channel:
   - `egs.state` → `aggregator.update_egs_state(payload)`
   - `drones.<id>.state` → parse `<id>` from channel, `aggregator.update_drone_state(id, payload)`
   - `drones.<id>.findings` → `aggregator.add_finding(payload)`

Reconnect: exponential backoff `1s → 2s → 4s → 8s`, capped at `BRIDGE_RECONNECT_MAX_S`. Logs each retry attempt.

### `frontend/ws_bridge/main.py` (modified)

Phase 1A's `_ticker` is replaced. The new `_emit_loop`:

```python
async def _emit_loop(registry, aggregator, config) -> None:
    while True:
        env = aggregator.snapshot(timestamp_iso=_now_iso_ms())
        env["contract_version"] = VERSION
        outcome = validate("websocket_messages", env)
        if outcome.valid:
            await registry.broadcast(env)
        else:
            print(f"[ws_bridge] BUG: aggregator emitted invalid envelope: {outcome.errors}")
        await asyncio.sleep(config.tick_s)
```

`_ConnectionRegistry.broadcast()` is updated to send in parallel with per-client timeout (eng review finding 1A):

```python
async def broadcast(self, message: dict) -> None:
    async with self._lock:
        targets = list(self._clients)
    encoded = json.dumps(message)
    async def _send(ws):
        try:
            await asyncio.wait_for(ws.send_text(encoded), timeout=self._send_timeout_s)
            return None
        except Exception:
            return ws
    results = await asyncio.gather(*[_send(ws) for ws in targets], return_exceptions=False)
    dead = [ws for ws in results if ws is not None]
    if dead:
        async with self._lock:
            for ws in dead:
                self._clients.discard(ws)
```

WS endpoint inbound handling: validate `operator_command` frames against `websocket_messages.operator_command`. On invalid, send back `{"type":"echo","error":"invalid_operator_command","detail":<errors>}`. On valid, log and echo (real republish is Phase 3).

Lifespan wiring:
1. Load `BridgeConfig` from env.
2. Load seed envelope from `shared/schemas/fixtures/valid/websocket_messages/01_state_update.json`.
3. Construct `ValidationEventLogger` (component `ws_bridge`).
4. Construct `StateAggregator(max_findings, seed_envelope)`.
5. Construct `RedisSubscriber(config, aggregator, validation_logger)`.
6. Start subscribe task and emit task.
7. On shutdown: cancel both, await cancellation.

### `scripts/dev_fake_producers.py` (new)

Standalone CLI publisher. Connects to `REDIS_URL`, publishes scripted contract-valid payloads on a timer.

Default behavior:
- Publishes `egs.state` every 2s with a stable `mission_id="dev_mission"` and incrementing `timestamp`.
- Publishes `drones.dev_drone1.state` every 1s with battery decreasing slowly.
- Every 8s, publishes a `drones.dev_drone1.findings` event with rotating `finding_type` and `finding_id="f_dev_drone1_<counter>"`.

Why `dev_drone1` (not `drone1`): when Person 1's sim ships and starts publishing on `drones.drone1.state`, the dev fake-producer must not collide. Distinct prefix gives zero ambiguity. The `--drone-id` CLI flag overrides for tests that need to pin a specific id.

CLI:
```
python scripts/dev_fake_producers.py [--redis-url URL] [--drone-id ID] [--tick-s 1.0]
```

### Tests

Five files under `frontend/ws_bridge/tests/`:

1. `test_aggregator.py` — pure unit tests (no I/O). Coverage:
   - First `update_egs_state` replaces seed.
   - First `update_drone_state` adds drone; second updates same drone in place.
   - Multi-drone: `update_drone_state("d1",...)` and `update_drone_state("d2",...)` both appear in `snapshot()["active_drones"]`.
   - `add_finding` appends; duplicate `finding_id` replaces in place; cap at `max_findings` evicts oldest.
   - `snapshot()` on a freshly constructed aggregator (empty buckets) produces a schema-valid `state_update` (regression: must match Phase 1A behavior).

2. `test_subscriber.py` — `fakeredis>=2.20` integration. Coverage:
   - Publish to `egs.state` → aggregator's egs bucket updates.
   - Publish to `drones.drone7.state` → matched by pattern, drone_id parsed correctly.
   - Publish to `drones.drone1.findings` and `drones.drone2.findings` → both findings present.
   - Publish invalid JSON → drop, validation event logged, aggregator unchanged.
   - Publish JSON that fails schema → drop, validation event logged, aggregator unchanged.
   - Disconnect mid-stream → subscriber retries; after reconnect, new messages flow through.

3. `test_envelope.py` — extended from Phase 1A. Coverage:
   - Snapshot envelope validates against `websocket_messages` for empty, partial, and fully-populated buckets.
   - `contract_version` always stamped from `shared.VERSION`.
   - `timestamp` advances between successive snapshots.
   - Embedded `egs_state` validates against its own schema; each `active_drones[i]` validates against `drone_state`; each `active_findings[i]` validates against `finding`.

4. `test_broadcast.py` — `_ConnectionRegistry` tests. Coverage:
   - Two clients receive the same payload.
   - One slow client (mocked `send_text` blocks beyond `BRIDGE_BROADCAST_TIMEOUT_S`) → dropped from registry; second client still receives.
   - Disconnected client (raises in `send_text`) → dropped without affecting others.

5. `test_e2e_playwright.py` — pytest-playwright + real `redis-server` + `dev_fake_producers.py` + bridge + Flutter web `build/web` served via `python -m http.server`. Coverage:
   - App-bar shows "connected" within 3s.
   - After fake-producer publishes a finding with `severity=4` and `visual_description="test victim"`, the findings panel renders "test victim" within 3s. Verified via JS `evaluate` capturing rendered text since Flutter web canvas-renders text (see Phase 1 verification notes).
   - Multi-drone test: producer publishes for `dev_drone1` and `dev_drone2` → drone status panel reflects both (count = 2).
   - Captured WS frames re-validated by Python `validate("websocket_messages", env)` — every frame passes.
   - Restart test: kill Redis mid-test → app-bar still shows "connected" (WS connection independent), data freezes; restart Redis → updates resume within 11s (10s reconnect cap + 1 tick).
   - 0 console errors, 0 unhandled WS frame types.

## Failure modes

| Failure | Test | Error handling | User-visible |
|---|---|---|---|
| Redis down at startup | `test_subscriber` reconnect, `test_envelope` empty-bucket | Backoff retry; emit loop continues with seed envelope | Dashboard renders empty state, no error toast |
| Redis dies mid-session | E2E restart test | Subscribe loop catches `RedisError`, reconnects | Data freezes for ≤ reconnect window |
| Producer publishes invalid JSON | `test_subscriber` invalid-json case | `JSONDecodeError` caught, validation event logged, dropped | None |
| Producer publishes schema-invalid JSON | `test_subscriber` invalid-schema case | Validation event logged, dropped | None |
| Producer publishes for unknown drone_id | `test_aggregator` multi-drone | Accepted as a new drone | New drone appears in panel (correct behavior — new producer arrived) |
| WS client slow/dead | `test_broadcast` slow-client case | Per-client `wait_for(timeout)`; dropped from registry | Other clients unaffected |
| Bridge process killed | manual | Lifespan `finally` cancels tasks; OS restarts process (out of scope) | Dashboard sees WS close, reconnects |

No critical gaps.

## Configuration & operations

Run order for development:
```bash
# Terminal 1: Redis
redis-server

# Terminal 2: Fake producers (Phase 2 only — replaced by Person 1 + Person 3 in real runs)
python scripts/dev_fake_producers.py

# Terminal 3: Bridge
uvicorn frontend.ws_bridge.main:app --host 0.0.0.0 --port 9090

# Terminal 4: Dashboard (Phase 1B)
cd frontend/flutter_dashboard && flutter run -d chrome
```

In real (Person 1 + Person 3 shipped) runs, Terminal 2 is replaced by `sim/waypoint_runner.py` and the EGS coordinator. Bridge code is identical. That's the whole point of Contract 9.

Logging: existing `shared.contracts.logging.setup_logging("ws_bridge")` plus `ValidationEventLogger("ws_bridge")` for invalid-payload events written as JSONL per Contract 11.

## Boundaries with other team members

- **Person 1 (sim) interface:** publishes `drones.<id>.state` with payloads validating against `drone_state` schema. Bridge couldn't care less which process publishes; the Contract 9 channel name and Contract 2 payload shape are the only contract.
- **Person 3 (EGS) interface:** publishes `egs.state` and `drones.<id>.findings`. Same indifference. The bridge subscribes to those channels and validates payloads. If EGS publishes anything that fails the schema, the bridge drops it and writes a validation event — Person 3 can read those JSONL files to debug.
- **No new shared contracts.** All schemas exist; topics.yaml stays unchanged. Phase 2 is pure consumer.

## Open follow-ups (deferred)

- Replace `print(...)` debug lines with structured logger calls everywhere (codebase-wide cleanup).
- Add `data_age_ms` field to `state_update` if Phase 5 polish wants explicit "data is stale" UI. Requires Contract 8 schema bump → cross-team review.
- Camera frame rendering inside the map panel (Phase 4 stretch).
