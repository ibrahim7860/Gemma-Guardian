# Plan: Beat 5 Path A-full — Disconnection-Tolerant Findings Pipeline

**Owner:** Person 4 (Ibrahim)
**Date drafted:** 2026-05-10 (Day 10 / 8 days to deadline)
**Revised:** 2026-05-10 post `/plan-eng-review` — 3 high-leverage edits applied (Component 2 trim, PR-split, mesh-sim healthcheck) + 7 test gaps closed.
**Supersedes:** `docs/plans/2026-05-10-beat5-offline-proof.md` (Path B sections; absorbs all storyboard / capture-rig tasks)
**Hackathon track:** Global Resilience (primary). This work is the load-bearing demonstration of the offline claim.

---

## 1. Goal

Make the FieldAgent system genuinely **disconnection-tolerant** between any drone and the EGS, so the storyboard's Beat 5 image — *"during the network outage the drone made a decision; on reconnect, that decision was reconciled to the EGS, no data lost"* — is captured against the real running system, not against a synthetic playback.

This is also a writeup §Resilience contribution worth standing on its own: durable mesh-aware delivery on top of a fire-and-forget Redis pub/sub layer.

## 2. What this fixes

The original Beat 5 plan assumed a "state syncs on reconnect" image (D2). Investigation against the codebase showed three independent reasons that image cannot be captured today:

**Architectural finding 1.** `agents/drone_agent/redis_io.py:46-51` — `RedisPublisher.publish()` is fire-and-forget. No queue, no retry, no replay. A finding produced "while standalone" goes to a Redis broker the drone is supposedly cut off from; if the broker delivers it, the EGS gets it instantly (no backfill image possible); if the broker drops it (it doesn't today), the finding is gone forever (also no backfill possible).

**Architectural finding 2.** `sim/waypoint_runner.py:171-176` — the `egs_link_drop` scripted event is observational. Comment literally says: *"egs_link_drop / egs_link_restore are observational for the sim — they don't change kinematics. Mesh sim and EGS handle the operational consequences."* Neither does. The wire is never severed.

**Architectural finding 3.** `agents/egs_agent/coordinator.py:113` — `counts[ftype] += 1` increments on every accepted finding with no `finding_id` deduplication. If we did somehow replay buffered findings, the EGS would double-count any that had been previously delivered. Pre-existing P0 in the codebase, surfaced by this work.

A-full closes all three.

## 3. Architecture — before and after

### Before

```
                        ┌────────────────────────────────────┐
                        │  drones.<id>.findings              │
   ┌─────────┐          │  (Redis pub/sub channel)           │       ┌──────────────┐
   │ drone N │─publish──┤                                    ├──sub──│  EGS         │
   └─────────┘          │                                    │       └──────────────┘
                        │                                    │       ┌──────────────┐
                        │                                    ├──sub──│  WS bridge   │
                        └────────────────────────────────────┘       └──────────────┘

   egs.state (1 Hz)     ┌────────────────────────────────────┐
   ┌─────────┐          │                                    │       ┌──────────────┐
   │  EGS    │─publish──│                                    ├──sub──│  drone N     │
   └─────────┘          └────────────────────────────────────┘       │  (no link    │
                                                                      │  detection   │
                                                                      │  today)      │
                                                                      └──────────────┘

   egs_link_drop event  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ no-op (observational only)
```

### After Path A-full (revised)

```
   drones.<id>.findings (drone-side raw publish, unchanged channel)
   ┌─────────┐                ┌──────────────────┐
   │ drone N │── publish ────▶│   mesh_simulator │
   │         │                │   findings gate  │
   │ buffer  │                │   (haversine vs  │
   │ if      │                │   egs_link_range │
   │ stand-  │                │   + scripted     │
   │ alone   │                │   override)      │
   └─────────┘                └────────┬─────────┘
        ▲                              │
        │                              │ pass if in range
        │                              │ DROP if out of range
        │                              ▼
        │                  drones.<id>.findings.delivered (new channel)
        │                  ┌────────────────────────────┐    ┌──────────────┐
        │                  │                            ├sub─│ EGS          │
        │                  │                            │    │ + finding_id │
        │                  │                            │    │   dedup set  │
        │                  │                            │    │ + mesh-sim   │
        │                  │                            │    │   healthcheck│
        │                  └─────────────┬──────────────┘    └──────────────┘
        │                                │                   ┌──────────────┐
        │                                └──────────sub──────│ WS bridge    │
        │                                                    └──────────────┘
        │
        │   mesh.link_status (event-driven, single channel)
        │   ┌──────────┐    payload: {drone_id, link: up|down, t}
        │   │ mesh_sim │────publish───▶ ┌──────────────┐
        │   └──────────┘                │ drone N      │
        │                               │ subscribes,  │
        └─────── sub ◀──────────────────┤ flips its    │
                                        │ standalone   │
                                        │ bit on event │
                                        └──────────────┘
            (1 Hz heartbeat publish keeps liveness; >10s without any
             event = staleness fallback to standalone)

   egs_link_drop event  ━━━▶  publishes to sim.scripted_events (new channel)
                              mesh_sim subscribes; flips per-drone gate +
                              publishes a mesh.link_status event for the drone
```

**Channel additions (revised — 1 fewer than original):**
- `drones.<id>.findings.delivered` — mesh-sim-gated EGS-bound copy
- `mesh.link_status` — event-driven, mesh sim publishes per-drone link transitions
- `sim.scripted_events` — sim broadcasts scripted timeline events for cross-component reactions

**Why this is simpler than the original:**
- Drone-side detection is event-driven (~20 LOC subscriber), not staleness-polling (~50 LOC `EgsHeartbeatMonitor` with clock injection).
- One fewer channel (no `egs.state.delivered.<id>`).
- Mesh sim is sole authority on link state; drone trusts events.
- 10s staleness fallback covers the rare case where a `mesh.link_status` event is missed.

**Channels unchanged:**
- `drones.<id>.findings` (drone publishes here, mesh sim consumes)
- `egs.state` (EGS publishes here, drone subscribes here directly — used for orientation, not link detection)
- `drones.<id>.state` (high-frequency telemetry; bypasses mesh sim — drone is always *visible* on the map even when EGS-link-dropped)
- `swarm.broadcasts.*` / `swarm.*.visible_to.*` (already mesh-sim-gated; unchanged)

## 4. Component breakdown

Seven components. Components 1-3 are independent of components 4-6 and can land in parallel branches. Component 7 (integration) is sequential after the others.

### Component 1 — Drone-side buffer + replay (~180 LOC)

**Files touched:**
- `agents/drone_agent/redis_io.py` — wrap `RedisPublisher` with buffer-aware logic
- `agents/drone_agent/memory.py` — add `buffered_findings` deque + JSONL persistence
- `agents/drone_agent/runtime.py` — toggle buffer mode based on link state
- `agents/drone_agent/tests/test_buffered_publisher.py` (new)
- `agents/drone_agent/tests/test_memory_buffer_persist.py` (new)

**Interface:**
```python
class BufferedPublisher:
    """Publisher that buffers when in_standalone is True, flushes when False.

    Wraps any Publisher (Protocol from action.py). Persistence via MemoryStore.
    """
    def __init__(self, inner: Publisher, memory: MemoryStore, drone_id: str): ...

    def publish(self, channel: str, payload: dict) -> None:
        """If in_standalone: buffer + persist. Else: pass through to inner."""

    def set_standalone(self, value: bool) -> None:
        """Called by runtime when link state changes."""

    def flush_buffered(self) -> int:
        """Drain buffer → publish all in FIFO order. Returns count flushed."""
```

**Persistence format:** `{log_dir}/{drone_id}_findings_queue.jsonl`. One JSON line per buffered finding. On startup, MemoryStore reads the file and rehydrates the deque (covers the rare case of a drone crash mid-buffer).

**Acceptance criteria:**
- Test: `test_publish_passes_through_when_not_standalone` — calls `publish`, asserts inner.publish was called.
- Test: `test_publish_buffers_when_standalone` — flips standalone=True, calls `publish` 3×, asserts inner.publish was called 0× and buffer has 3 entries.
- Test: `test_flush_drains_in_order` — buffer 3 findings (f_001, f_002, f_003), flip standalone=False, call `flush_buffered()`, assert inner.publish called 3× in order.
- Test: `test_flush_persists_to_jsonl` — buffer 3, restart MemoryStore in same dir, assert deque is rehydrated with 3 entries.
- Test: `test_buffer_only_for_findings_channel` — verify buffer logic gates on channel name (peer broadcasts and state should NOT be buffered; only `drones.<id>.findings`).

**Effort:** ~3.5 CC-hours.

### Component 2 — Drone-side link-state subscriber (~25 LOC, revised)

**Files touched:**
- `agents/drone_agent/runtime.py` — add `LinkStateMonitor` class (event-driven, with staleness fallback)
- `agents/drone_agent/redis_io.py` — add `LinkStatusSubscriber` (subscribes to `mesh.link_status` filtered by drone_id)
- `agents/drone_agent/tests/test_link_state_monitor.py` (new)

**Interface:**
```python
class LinkStateMonitor:
    """Event-driven standalone detection. Primary signal: mesh.link_status events.
    Fallback: stale beyond `staleness_threshold_s` (default 10.0) → assume standalone.
    """
    def __init__(self, drone_id: str, staleness_threshold_s: float = 10.0): ...
    def note_event(self, link: str) -> None:  # link == "up" | "down"
        """Called by LinkStatusSubscriber on each event."""
    def is_standalone(self) -> bool:
        """True if last event was 'down' OR no event in staleness_threshold_s."""
```

Wired in `DroneRuntime.__init__`. Consulted in `_state_republish_loop` (writes `agent_status: "standalone" | "active"` into the republished state). Also drives `BufferedPublisher.set_standalone()` on flip transitions.

**Acceptance criteria:**
- Test: `test_initially_standalone_until_first_event` — fresh monitor reports `is_standalone() == True` (defensive default).
- Test: `test_active_after_link_up_event` — `note_event("up")`, assert `is_standalone() == False`.
- Test: `test_standalone_after_link_down_event` — `note_event("up")`, then `note_event("down")`, assert standalone.
- Test: `test_staleness_fallback_after_threshold` — `note_event("up")`, fast-forward clock past threshold, assert standalone.
- Test: `test_buffer_flushes_on_link_restore` — integration: standalone → buffer 2 findings → link_up event → buffer flushed.
- Test: `test_missed_event_recovery` — `note_event("up")`, no further events, after 10s the monitor reports standalone (regression: ensures fallback engages even if mesh sim crashes mid-emit).

**This component supersedes Kaleel's TODO** (TODOS.md "Wire `agent_status` flips in drone state republish"). The drone now self-detects standalone and writes the field itself; Kaleel's runtime work for `agent_status` is no longer on the GATE-4 critical path. Notify him.

**Effort:** ~0.8 CC-hours (down from 1.5h pre-revision).

### Component 3 — Mesh-sim findings gateway + link_status emitter (~70 LOC, revised)

**Files touched:**
- `agents/mesh_simulator/main.py` — add `forward_finding()`, `emit_link_status()` methods + psub setup
- `agents/mesh_simulator/range_filter.py` — extract `is_drone_in_egs_link_range()` helper
- `shared/contracts/topics.yaml` — add `findings_delivered`, `mesh_link_status`, `sim_scripted_events`
- `shared/contracts/topics.py` — regenerate via `scripts/gen_topic_constants.py`
- `frontend/flutter_dashboard/lib/contracts/topics.dart` — regenerate
- `shared/schemas/scripted_event.json` (new) — schema for `sim.scripted_events` payloads
- `shared/schemas/mesh_link_status.json` (new) — schema for `mesh.link_status` events
- `agents/mesh_simulator/tests/test_findings_gate.py` (new)
- `agents/mesh_simulator/tests/test_link_status_emitter.py` (new)
- `agents/mesh_simulator/tests/test_two_drones_standalone.py` (new — covers test gap)

**Interface (additions to `MeshSimulator`):**
```python
async def forward_finding(self, drone_id: str, raw_payload: bytes) -> None:
    """If drone is in egs_link_range AND not in _link_down_overrides,
    republish to drones.<id>.findings.delivered. Else drop.
    """

def emit_link_status(self, drone_id: str, link: str) -> None:
    """Publish a mesh.link_status event {drone_id, link: 'up'|'down', t}.
    Called on (a) link transitions detected by geometric range checks
    at 1 Hz, and (b) scripted-event-driven transitions.
    """

def apply_scripted_event(self, event: dict) -> None:
    """Handle egs_link_drop / egs_link_restore.
    Maintains _link_down_overrides: set[str].
    On transition, calls emit_link_status() so subscribed drones flip immediately.
    """
```

**Critical design choice — geometry vs scripted override.** Two ways a drone ends up "out of EGS link":
1. **Geometric** — drone has flown beyond `egs_link_range_meters` (500 m). Mesh sim already knows positions; haversine check is cheap.
2. **Scripted override** — `egs_link_drop <drone_id>` event fires regardless of position. Useful when scenario geometry doesn't naturally drop.

The mesh sim treats *either* signal as a link-down. `_link_down_overrides` is a set of drone-ids force-overridden until `egs_link_restore` clears them. The geometric check still runs at 1 Hz; transitions emit `mesh.link_status` events.

**Buffer overflow policy (closes test gap):** drone-side `BufferedPublisher` uses `deque(maxlen=1000)` → drops *oldest* on overflow. Document in code comment + storyboard footnote: "in standalone windows >16 minutes (1000 findings × 1/min), early findings are lost."

**Acceptance criteria:**
- Test: `test_in_range_finding_forwarded` — drone1 at 100 m from EGS, range 500 m → finding republished to `.delivered`.
- Test: `test_out_of_range_finding_dropped` — drone1 at 1 km from EGS, range 500 m → no message on `.delivered`.
- Test: `test_scripted_link_drop_overrides_geometry` — drone1 at 100 m (in range) but `egs_link_drop drone1` fired → finding dropped.
- Test: `test_link_restore_clears_override` — after `egs_link_restore`, finding republished again.
- Test: `test_link_status_emitted_on_geometric_transition` — drone crosses 500 m boundary → `mesh.link_status` event fires with `link="down"`.
- Test: `test_link_status_emitted_on_scripted_event` — `egs_link_drop` fired → `mesh.link_status` event fires immediately.
- Test: `test_two_drones_standalone_simultaneously` — drone1 + drone3 both forced down → each gets its own `mesh.link_status` event; drone2 (in range) does NOT get a "down" event meant for the others. **Closes test gap from review.**

**Effort:** ~2 CC-hours.

### Component 4 — EGS finding_id dedup + channel migration + mesh-sim healthcheck (~70 LOC, revised)

**Files touched:**
- `agents/egs_agent/main.py` — (a) change subscription from `drones.*.findings` to `drones.*.findings.delivered`; (b) add mesh-sim availability healthcheck on startup; (c) emit `[info] egs.findings_consumed total=N` log every 30s (silent-zero detection)
- `agents/egs_agent/coordinator.py` — add `_seen_finding_ids: deque[(str, float)]` with FIFO eviction; check before incrementing in `process_findings`
- `agents/egs_agent/tests/test_coordinator_dedup.py` (new)
- `agents/egs_agent/tests/test_main_findings_subscribe_channel.py` (new — guards against accidental subscription regression)
- `agents/egs_agent/tests/test_main_mesh_sim_healthcheck.py` (new — fail-fast on missing mesh sim)
- `agents/egs_agent/tests/test_main_silent_zero_warning.py` (new — verifies the periodic log fires)

**Mesh-sim healthcheck (closes review finding #3 — SPoF):**
```python
# In agents/egs_agent/main.py at startup, before psub on .delivered:
async def _await_mesh_sim(redis_client, timeout_s: float = 5.0) -> None:
    """Wait for at least one heartbeat on mesh.adjacency_matrix.
    The mesh sim publishes adjacency at 1 Hz unconditionally.
    Absence after timeout_s = mesh sim isn't running; exit non-zero.
    """
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("mesh.adjacency_matrix")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        msg = await pubsub.get_message(timeout=0.5, ignore_subscribe_messages=True)
        if msg is not None:
            await pubsub.unsubscribe("mesh.adjacency_matrix")
            return
    await pubsub.unsubscribe("mesh.adjacency_matrix")
    raise RuntimeError(
        "mesh_simulator not detected on mesh.adjacency_matrix within "
        f"{timeout_s}s. Findings WILL NOT be delivered to EGS without it. "
        "Start it: `python -m agents.mesh_simulator`."
    )
```

**Interface change in `EGSCoordinator.process_findings`:**
```python
def process_findings(self, state: EGSState) -> EGSState:
    SEEN_TTL_S = 300.0  # 5 min — generous vs realistic outage windows
    now_s = time.time()
    # Evict stale entries
    self._seen_finding_ids = {
        fid: ts for fid, ts in self._seen_finding_ids.items()
        if now_s - ts < SEEN_TTL_S
    }
    for f in state.get("incoming_findings", []):
        fid = f.get("finding_id")
        if fid in self._seen_finding_ids:
            logger.info("egs.findings duplicate dropped finding_id=%s", fid)
            continue
        val_res = self.validation_node.validate_finding(f)
        if val_res.valid:
            self._seen_finding_ids[fid] = now_s
            counts[ftype] += 1
            ...
```

**Acceptance criteria:**
- Test: `test_first_finding_increments` — single finding → counts increment by 1.
- Test: `test_duplicate_finding_id_does_not_increment` — same finding_id twice → counts increment by 1 total.
- Test: `test_duplicate_after_ttl_expires_re_increments` — same finding_id at t=0 and t=400s → both count (TTL evicted). Verifies the deque doesn't leak.
- Test: `test_subscription_channel_is_findings_delivered` — verifies EGS subscribes to the gated channel post-migration.
- Test: `test_startup_fails_without_mesh_sim` — start EGS without mesh sim → RuntimeError raised within 5s, exits non-zero. **Closes review finding #3.**
- Test: `test_silent_zero_warning_logged` — EGS runs for 30s with no findings → `[info] egs.findings_consumed total=0` line appears, providing the diagnostic fingerprint for broken migrations.

**Migration risk:** Several existing tests publish directly to `drones.<id>.findings` and expect the EGS to consume. List of tests to update (from research):
- `agents/egs_agent/tests/test_main_findings_count_increment.py`
- `agents/egs_agent/tests/test_validation.py`
- `frontend/ws_bridge/tests/test_e2e_playwright_egs_findings.py`
- Any integration test in the `bridge_e2e` CI job

These need to either (a) publish to `drones.<id>.findings.delivered` directly (bypassing mesh sim, simpler for unit tests), or (b) launch a real mesh sim alongside. **Recommend (a) for unit/integration tests, (b) only for true end-to-end.**

**Effort:** ~1.5 CC-hours including test migration.

### Component 5 — Drone counter durability (~30 LOC)

**Files touched:**
- `agents/drone_agent/memory.py` — persist `_finding_counter` to disk; load on init
- `agents/drone_agent/tests/test_memory_finding_id.py` — extend with restart test

**Interface:**
```python
# In MemoryStore.__init__:
counter_path = base / f"{drone_id}_finding_counter.txt"
if counter_path.exists():
    self._finding_counter = int(counter_path.read_text().strip() or "0")
else:
    self._finding_counter = 0
self._counter_path = counter_path

def next_finding_id(self) -> str:
    self._finding_counter += 1
    self._counter_path.write_text(str(self._finding_counter))  # synchronous, ~µs
    return f"f_{self.drone_id}_{self._finding_counter}"
```

**Acceptance criteria:**
- Test: `test_counter_persists_across_restart` — generate 3 ids, throw away store, recreate in same dir, generate id, expect `f_drone1_4`.
- Test: `test_counter_starts_at_zero_when_no_file` — fresh dir, first id is `f_drone1_1`.
- Test: `test_counter_recovers_from_empty_file` — file exists but empty; treat as 0.

**Effort:** ~0.5 CC-hours.

### Component 6 — Sim publishes scripted events (~40 LOC)

**Files touched:**
- `sim/waypoint_runner.py` — extend `_fire()` to publish on `sim.scripted_events`
- `shared/contracts/topics.yaml` — already covered by component 3
- `sim/tests/test_scripted_events_publish.py` (new)

**Interface change in `_fire()`:**
```python
def _fire(self, event: ScriptedEvent) -> None:
    if event.type == "drone_failure" and event.drone_id in self._drones:
        self._drones[event.drone_id].failed = True
    # Publish ALL scripted events to sim.scripted_events for cross-component
    # reactions. This reverses the 2026-05-08 "observational only" comment;
    # mesh sim and EGS now both consume these.
    payload = {
        "t": event.t, "type": event.type,
        "drone_id": event.drone_id, "detail": event.detail,
        "wall_clock_iso_ms": now_iso_ms(),
    }
    self._publisher.publish(SIM_SCRIPTED_EVENTS, payload)
```

**Acceptance criteria:**
- Test: `test_egs_link_drop_event_published` — fire `egs_link_drop drone3` at t=120, assert message lands on `sim.scripted_events`.
- Test: `test_event_payload_shape` — schema-validate against new `shared/schemas/scripted_event.json` (also new — keep contract additions consistent).

**Effort:** ~1 CC-hour.

### Component 7 — End-to-end integration tests + capture rig + storyboard (~250 LOC)

This rolls together the deliverables from the original Beat 5 plan, now implementable because Components 1–6 made the architecture honest.

**Files added:**
- `frontend/ws_bridge/tests/test_e2e_playwright_beat5_offline_recovery.py` — synth-WS-driven, replays envelope sequence proving the dashboard renders the full sequence (banner up, badge up, finding tile arrives after restore, chip ticks once).
- `agents/egs_agent/tests/test_e2e_link_drop_replay.py` (new) — REAL e2e against an ephemeral redis: launch sim + drone agents + mesh sim + EGS, fire the resilience scenario, assert drone3's standalone-window finding arrives at EGS *after* `egs_link_restore` and dashboard chip ticks exactly once.
- `scripts/run_beat5_capture.sh` — capture-rig orchestrator, locked to `resilience_v1`, ports + log dir + pre-warm + status line.
- `scripts/check_beat5.py` — programmatic verifier: A1 standalone entry, A2 finding while standalone, A3 chip tick after restore, A4 return to active.
- `docs/runbooks/mcp-dom-verification.md` — append "Beat 5 offline-proof capture path" section mirroring Beat 3 / Beat 4 patterns.
- `docs/21-demo-storyboard.md` — replace lines 108–120 with the frame-by-frame mechanics from the original plan, now actually filmable.

**Acceptance criteria:** the verifier exits 0 against a complete uninterrupted run of `resilience_v1` with all components 1–6 deployed. All new tests green. Test coverage diagram from Section §3 of the original plan now shows 100%.

**Effort:** ~5 CC-hours.

## 5. Sequencing and parallelization (revised — refactor-first split)

Per `/plan-eng-review` finding #2 (Beck's "make the change easy, then make the easy change"), this lands as two PRs: a behavior-preserving refactor first, then the actual gate + buffer + dedup behavior.

```
═══════════════════════════════════════════════════════════════════════
PHASE 0 — Shared infrastructure (sequential, ~30 min, do myself)
═══════════════════════════════════════════════════════════════════════
   - Add new channels to topics.yaml
   - Regenerate topics.py + topics.dart
   - Add scripted_event.json + mesh_link_status.json schemas

═══════════════════════════════════════════════════════════════════════
PR1 — REFACTOR ONLY (sequential, ~1.5 h, one subagent)
═══════════════════════════════════════════════════════════════════════
   - Mesh sim psubscribes drones.*.findings, REPUBLISHES verbatim
     (no gate, no override) to drones.<id>.findings.delivered
   - EGS migrates subscription from .findings to .findings.delivered
   - Bridge migrates subscription from .findings to .findings.delivered
   - All existing tests still pass — zero behavioral change
   - Smoke test: EGS startup logs "subscribing to drones.*.findings.delivered"

═══════════════════════════════════════════════════════════════════════
PR2 — BEHAVIOR (parallel via subagents)
═══════════════════════════════════════════════════════════════════════

WAVE 1 (parallel, ~2 h wall — 3 subagents)
───────────────────────────────────────────────────────────────────────
   Lane A: Component 1 (drone buffer + replay) ~3 h
   Lane B: Component 5 (counter durability)    ~0.5 h
   Lane C: Component 6 (sim scripted events)   ~1 h

WAVE 2 (parallel, ~2 h wall — 2 subagents)
───────────────────────────────────────────────────────────────────────
   Lane D: Component 3 (mesh sim gate + link_status emitter) ~2 h
   Lane E: Component 2 (link_status subscriber + monitor)    ~0.8 h
            └─ depends on Lane D's mesh_link_status payload shape;
               Lane E starts ~30 min after Lane D for that overlap

WAVE 3 (sequential, ~3 h)
───────────────────────────────────────────────────────────────────────
   Component 4 (EGS dedup + healthcheck + silent-zero log) ~1 h
   Component 7 (integration + capture rig + Playwright + storyboard) ~5 h
```

**Realistic wall-clock with parallel subagents:** ~9 hours. **Without parallelism:** ~13 hours.

**Conflict flags:**
- Lane A and Lane E both touch `agents/drone_agent/runtime.py`. **Sequence them** — A's `BufferedPublisher` integration goes first, then E's `LinkStateMonitor` integration. OR: same worktree, sequential. Recommend: same worktree, A finishes runtime integration before E starts.
- All Wave 2 lanes touch `agents/mesh_simulator/main.py` and `agents/drone_agent/runtime.py`. Wave 1 lanes are isolated to `memory.py`, `redis_io.py`, and `sim/waypoint_runner.py` respectively — clean parallelism.

## 6. Test strategy

### Test types per component

| Component | Unit tests | Integration tests | E2E |
|---|---|---|---|
| 1 (buffer) | 5 (BufferedPublisher in isolation) | 1 (with FakeStrictRedis) | covered in C7 |
| 2 (link detect) | 4 (clock-injected) | 1 (subscriber + monitor) | covered in C7 |
| 3 (mesh gateway) | 5 (range_filter logic) | 2 (FakeStrictRedis pub/sub round-trip) | covered in C7 |
| 4 (EGS dedup) | 4 (process_findings) | 1 (channel migration smoke) | covered in C7 |
| 5 (counter durability) | 3 (file-system) | — | covered in C7 |
| 6 (sim publish) | 2 (fire path) | 1 (round-trip) | covered in C7 |
| 7 (integration) | — | 2 (synth-WS Playwright + real-redis) | 1 (full pipeline against ephemeral redis) |

**Total new tests:** ~32 across 9 new test files + minor edits to ~5 existing files.

### Reuses existing infrastructure

- `_RecordingPublisher` spy from `agents/drone_agent/tests/test_action_finding_publish.py:7-11`
- `FakeStrictRedis` + `FakeRedis` from `agents/drone_agent/tests/conftest.py`
- Synth-WS pattern from `frontend/ws_bridge/tests/test_e2e_playwright_standalone_mode.py`
- Free-port fixture from `frontend/ws_bridge/tests/conftest.py`
- `flutter_static_server` fixture from same conftest

No new test infrastructure required.

### Regression coverage for existing behavior

The channel migration in Component 4 changes EGS's subscription from `drones.*.findings` to `drones.*.findings.delivered`. If a developer reverts the migration (or fails to launch mesh sim), the EGS will silently see zero findings. Add a startup log line that explicitly states the subscription channel, plus a smoke test (`test_main_findings_subscribe_channel.py`) that constructs the EGS main and asserts the psub call lands on the right channel.

## 7. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **R1 — Channel migration breaks the bridge** | Medium | High (dashboard goes blank) | Bridge migrates in same PR as EGS migration; regression test in `bridge_e2e` CI verifies bridge subscribes to `.delivered`. |
| **R2 — Mesh sim missing in dev/test environments** | Medium | High (findings never reach EGS at all) | Drone agent's `__main__.py` already requires `--mesh-required` flag for production; default behavior in tests is to publish to `.delivered` directly (bypass mesh sim). Document this in `docs/13-runtime-setup.md`. |
| **R3 — Counter persist file lock contention** | Low | Low (rare, harmless retry) | Counter writes are infrequent (per finding, ~1/min); single-writer per drone process; OS-level append is atomic on macOS/Linux for <PIPE_BUF. |
| **R4 — `_seen_finding_ids` dict grows unbounded** | Low | Medium (memory leak in long-running EGS) | TTL eviction every call (~5 min window); 1000 findings/min × 5 min = 5000 keys × ~50 bytes = ~250 KB. Negligible. |
| **R5 — Heartbeat-staleness flips standalone mid-publish** | Medium | Medium (race condition; finding ends up in buffer or wire depending on timing) | Tolerable — the user-visible effect is at most one finding being delivered "via the standalone path even though link came back" or vice versa. Both are correctness-preserving. Document in code comment. |
| **R6 — GATE-3/GATE-4 merge conflicts** | Medium | Medium (delays demo capture) | All Phase 1 worktrees branch from current `main`, not from teammates' active branches. Coordinate merge order: this PR lands first, others rebase. Notify Kaleel + Qasim before merging. |
| **R7 — Demo machine doesn't actually drop external network** | Low | High (offline proof unconvincing) | Connectivity-probe pane (from original Beat 5 plan) is the authoritative signal; verified against the demo machine on Day 12. |
| **R8 — Replay window timing tight** | Medium | Medium | Resilience scenario has 60-s drop window (t=120 to t=180). Drone3 produces ~1 finding/min in that window (frame_mappings). Buffer has 60 s of slack. If frame mapping changes, re-verify. |

## 8. Cross-team coordination

| Teammate | What they own | What this PR touches | Action required from them |
|---|---|---|---|
| **Kaleel** | `agents/drone_agent/`, `ml/` | `runtime.py`, `redis_io.py`, `memory.py` | Review PR. Be aware: this supersedes the `agent_status` flips TODO. |
| **Qasim** | `agents/egs_agent/` | `coordinator.py`, `main.py` (channel migration) | Review PR. Coordinate merge order with his GATE-4 branch. |
| **Hazim** | `sim/`, `agents/mesh_simulator/` | `mesh_simulator/main.py`, `range_filter.py`, `waypoint_runner.py`, `topics.yaml` | Review PR. Architectural change to mesh sim; biggest blast radius for him. |
| **Thayyil** | sim co-pilot | none directly | None — informational only. |

**Slack messages to send before starting Phase 1:**

- **Kaleel:** "Day 10 plan: I'm shipping disconnection-tolerant findings (buffer-on-drone, dedup-on-EGS, mesh-sim-gates-the-wire). Touches your `runtime.py`, `redis_io.py`, `memory.py`. The buffer toggle uses `egs.state` heartbeat staleness — your TODO for `agent_status` runtime flips becomes redundant after this. OK if I land this before your GATE-3 merge?"
- **Qasim:** "Day 10 plan: adding `_seen_finding_ids` dedup in `coordinator.process_findings` and migrating EGS subscription from `drones.*.findings` to `drones.*.findings.delivered` (mesh sim becomes the gate). Lands near your replan logic; want a 5-minute call before I open the PR?"
- **Hazim:** "Day 10 plan: making `egs_link_drop` actually sever findings + per-drone egs.state delivery. Mesh sim psubs `drones.*.findings`, applies egs_link_range gate, republishes to `drones.<id>.findings.delivered`. Two new channels in topics.yaml. 15-min review when I'm ready?"

## 9. Acceptance criteria — whole effort

This plan is "done" when ALL of the following are green:

1. **`scripts/check_beat5.py` exits 0** against a complete uninterrupted run of `resilience_v1` on the demo machine. Verifies:
   - drone3 enters `agent_status == "standalone"` between t=120 and t=130.
   - drone3 publishes ≥1 Contract-4 finding while standalone.
   - That finding lands on `drones.drone3.findings.delivered` *only after* `egs_link_restore` (t≈180).
   - `egs.state.findings_count_by_type` reflects the drone3-while-standalone finding within 5 s of `egs_link_restore`.
   - drone3 returns to `agent_status == "active"` after t=180.
   - The same `finding_id` does NOT cause a second count increment.

2. **All new unit tests green.** ~32 new tests across 9 new test files.

3. **CI bridge_e2e job green** with the new `test_e2e_playwright_beat5_offline_recovery.py` plus the existing dom-render test (un-regressed).

4. **Beat 5 frame-by-frame capture** at `docs_assets/beat5-offline-proof.mp4` reproduces the storyboard's mechanics table on the demo machine, captured per `docs/runbooks/mcp-dom-verification.md` "Beat 5 offline-proof capture path."

5. **Storyboard `docs/21-demo-storyboard.md`** lines 108–120 replaced with the frame-by-frame from the original plan; reference asset row points at the new mp4 and the new runbook section.

6. **Writeup `docs/22-writeup-draft.md` §Resilience** mentions the durable-replay buffer as a contribution. One paragraph; specific.

7. **TODOS.md** entries cleaned: "Wire `agent_status` flips" closed (superseded by Component 2); new entry added if any Phase 1 lane discovers follow-up work; original `2026-05-10-beat5-offline-proof.md` plan marked SUPERSEDED.

## 10. What this plan does NOT cover

- **Demo video editing** (DaVinci Resolve, narration, music) — Days 14–16, separate track.
- **Two-machine backup capture** — Day 15 with Thayyil.
- **xBD fine-tuning go/no-go** — GATE 3, Kaleel's track.
- **EGS-side `finding_approval` consumer for `egs.operator_actions`** — Qasim's open TODO; orthogonal.
- **Bridge UI animation polish** for the chip-tick-on-restore (originally R6 in the prior plan) — bumped to TODOS.md if Day 11 finds it doesn't read on video.
- **Runtime config exposure** of `egs_link_range_meters` — already in `shared/config.yaml`, already plumbed; no new ergonomics.

## 11. Estimated total effort

- **Phase 1 (parallel):** ~3.5 h wall clock (3 lanes; longest is Component 1 at ~3.5 h)
- **Phase 2 (sequential after C):** ~1.5 h
- **Phase 3 (sequential):** ~5 h
- **Buffer for integration/debugging/cross-team review:** ~2 h

**Total realistic budget: 12 hours of focused work.** Fits Day 10 evening + Day 11 if uninterrupted.

**Day-by-day shape:**
- **Day 10 (today):** Phase 1 lanes launched in 3 worktrees. Aim to merge all four (A/C/D/E) by EOD.
- **Day 11 morning:** Lane B + Phase 2 (Component 4 / channel migration). Land before noon.
- **Day 11 afternoon:** Phase 3 — capture rig, integration tests, storyboard rewrite. End of day: a green `check_beat5.py` run.
- **Day 12:** real demo-machine capture session; record 50× per storyboard production notes; pick top 3 takes.

## 12. First action

Create branch `ibrahim/day10-beat5-path-a-full` off current `main`. Send the three Slack notifications. Spin up three Agent worktrees for Phase 1 lanes A, C, D. Lane E (sim event publish) can also kick off in parallel if a fourth worktree is available.

Lane B (link detection) waits ~5 min for Lane C's channel name to be published in topics.yaml; then starts.
