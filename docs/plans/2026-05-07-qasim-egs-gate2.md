# Qasim EGS GATE 2 Implementation Plan

**Date:** 2026-05-07 (Day 7 — GATE 2 evaluation day)
**Owner:** Qasim (EGS / Coordination)
**Plan author:** Ibrahim
**Spec sources:** [`docs/06-edge-ground-station.md`](../06-edge-ground-station.md), [`docs/20-integration-contracts.md`](../20-integration-contracts.md), [`docs/STATUS.md`](../STATUS.md) Qasim row
**Branch convention:** `feature/qasim-egs-gate2-scenario-aligned`

**Plan-eng-review (2026-05-07):** reviewed; 4 contested decisions resolved (see decision log at end of doc). Inline fixes applied: T-GAP-1/2/3 added to test list, `_M_PER_DEG_LON` calibration comment, 60s→30s dedup-window doc fix folded into Task 9, validation-event schema-filter added to `tail()`, replan converted to fire-and-forget background task, refresh_validation_events runs every 5th tick.

---

## 1. Goal

Close out Qasim's three GATE 2 critical items so the live integrated demo (real sim → real drone agent → real EGS → real bridge → Flutter) renders end-to-end with all four panels populated and counts incrementing under live drone findings:

1. **EGS subscribes to `drones.<id>.findings` from real drone agents** (not `dev_fake_producers`).
2. **Findings reflect into `egs.state` for the dashboard** — `findings_count_by_type` increments on every accepted finding.
3. **`zone_polygon` aligns with the active scenario YAML** — drop the hardcoded LA bbox in `agents/egs_agent/main.py:47-50`; derive it from `sim/scenarios/<scenario_id>.yaml`.

Plus the smaller correctness fixes that surface while doing the above:

4. Initial replan trigger fix — coordinator currently no-ops at startup because `trigger_replan=True` fires before any drone has reported `agent_status="active"`.
5. `recent_validation_events` consumer (Contract 11) — currently never populated despite being a required field.
6. `survey_points` aligned with the scenario's actual waypoints (not the hardcoded `sp_001`/`sp_002`).

GATE 2 evaluation passes when:
- `pytest agents/egs_agent/tests/ -q` is green.
- `pytest frontend/ws_bridge/tests/test_e2e_playwright_egs_findings.py` is green.
- A Playwright MCP live capture at `docs_assets/dashboard-egs-state-counts.png` shows the dashboard reading non-zero `findings_count_by_type` driven by the real drone agent (not a fake producer).
- `docs/STATUS.md` Qasim row flips GATE 2 from ⚠️ to ✅.

---

## 2. Architecture

### 2.1 What changes

```
sim/scenarios/<id>.yaml ──────┐
                              │ load_scenario()
                              ▼
            agents/egs_agent/scenario_state.py  ◄── NEW
                              │ build_initial_egs_state()
                              ▼
            agents/egs_agent/main.py             (replaces hardcoded init block)
                              │
                              ├─ subscribes drones.*.state    ◄── unchanged
                              ├─ subscribes drones.*.findings ◄── unchanged subscribe; fix downstream
                              │
                              ▼
            agents/egs_agent/coordinator.py     (process_findings increments counts;
                                                 process_telemetry triggers initial replan)
                              │
                              ▼
            egs.state on Redis @ 1Hz             ◄── unchanged channel
                              │
                              ▼
            frontend/ws_bridge → Flutter         ◄── unchanged consumer
```

### 2.2 What does NOT change (locked by Contract 3)

- `egs.state` schema — `mission_id`, `zone_polygon`, `survey_points`, `drones_summary`, `findings_count_by_type`, `recent_validation_events`, `active_zone_ids`. We reorganize WHERE the values come from, not WHAT shape they take.
- Channel names — `drones.<id>.state`, `drones.<id>.findings`, `egs.state`. Touching these fails the `topics_codegen_fresh` test.
- `EGSValidationNode` cross-drone dedup window (10m / 30s). The spec at `docs/06` says 10m / 60s but the locked validator is 30s; do **not** change it without a contract version bump.

### 2.3 Why scenario-derived `zone_polygon`

The hardcoded polygon at `agents/egs_agent/main.py:47-50` is at `34.123, -118.568` (Burbank). Every scenario YAML ships an `origin: {lat: 34.0000, lon: -118.5000}` and `area_m: 200|1500`. The Flutter map panel renders zone outlines from this polygon — if it doesn't enclose the drones plotted from `drones.<id>.state`, the dashboard looks broken.

Derivation rule: take the bounding box of all `drones[].waypoints[].{lat,lon}` from the scenario, expand by 50m on each side, emit as a 4-vertex closed polygon (CCW). This is also the natural source for `survey_points` — one entry per waypoint, with `id`/`lat`/`lon` from the YAML and `status: "unassigned"`, `assigned_to: null` until the EGS coordinator reassigns.

---

## 3. Tasks

Tasks are sized to land in 1-2 commits each. Order matters: Task 1 is a pure helper with no runtime change (safe to land alone); Task 2 wires it in (the scenario-derived state appears in Redis); Tasks 3-5 are the smaller correctness fixes; Tasks 6-9 are tests and docs.

### Task 1: Scenario-state derivation helper (pure, no I/O surprises)

**Files:**
- Create: `agents/egs_agent/scenario_state.py`
- Test:   `agents/egs_agent/tests/test_scenario_state.py`

**Behavior:**

```python
# agents/egs_agent/scenario_state.py
from pathlib import Path
from typing import Any, Dict
from datetime import datetime, timezone

from sim.scenario import load_scenario, Scenario

SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "sim" / "scenarios"
ZONE_BUFFER_M = 50.0  # outset around waypoint extents
# 1 deg latitude ≈ 111_320 m; lon scaling is _cos(lat) * 111_320, but for
# 50m buffers at LA latitude (~34°) the per-degree lon factor is ~92_300.
# We use a fixed approximation to keep this pure (no library calls).
_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = 92_300.0
# NOTE: _M_PER_DEG_LON is calibrated for ~34°N (cos(34°) × 111_320 ≈ 92_240).
# Every shipped scenario lands within 0.01° of 34.0000 so the 50m buffer is
# accurate to <1m. If a future scenario uses a very different latitude, the
# buffer width along longitude will be off; recompute then or switch to a
# proper cos(lat) factor.


def _bbox_polygon(scenario: Scenario, buffer_m: float) -> list[list[float]]:
    """Return CCW closed bounding-box polygon for all scenario waypoints,
    outset by `buffer_m` on each side."""
    lats = [w.lat for d in scenario.drones for w in d.waypoints]
    lons = [w.lon for d in scenario.drones for w in d.waypoints]
    dlat = buffer_m / _M_PER_DEG_LAT
    dlon = buffer_m / _M_PER_DEG_LON
    lat_min, lat_max = min(lats) - dlat, max(lats) + dlat
    lon_min, lon_max = min(lons) - dlon, max(lons) + dlon
    # CCW from SW corner: SW -> SE -> NE -> NW -> SW (closed).
    return [
        [lat_min, lon_min],
        [lat_min, lon_max],
        [lat_max, lon_max],
        [lat_max, lon_min],
        [lat_min, lon_min],
    ]


def build_initial_egs_state(scenario_id: str) -> Dict[str, Any]:
    """Build a schema-valid initial egs_state from the active scenario YAML.

    Returned dict satisfies shared/schemas/egs_state.json. Caller is
    responsible for stamping `timestamp` on each publish tick.
    """
    path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    scenario = load_scenario(path)

    survey_points = [
        {
            "id": w.id,
            "lat": w.lat,
            "lon": w.lon,
            "assigned_to": None,
            "status": "unassigned",
        }
        for d in scenario.drones
        for w in d.waypoints
    ]

    return {
        "mission_id": scenario.scenario_id,
        "mission_status": "active",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "zone_polygon": _bbox_polygon(scenario, ZONE_BUFFER_M),
        "survey_points": survey_points,
        "drones_summary": {},
        "findings_count_by_type": {
            "victim": 0, "fire": 0, "smoke": 0,
            "damaged_structure": 0, "blocked_route": 0,
        },
        "recent_validation_events": [],
        "active_zone_ids": [],
    }
```

**Tests** (`agents/egs_agent/tests/test_scenario_state.py`):

- `test_build_initial_state_disaster_zone_v1` — load scenario; assert `mission_id == "disaster_zone_v1"`; assert `len(survey_points) == 10` (4+3+3); assert every waypoint id appears once; assert `survey_points[i]["status"] == "unassigned"`; assert `drones_summary == {}`.
- `test_build_initial_state_passes_egs_state_schema` — `from shared.contracts import validate; outcome = validate("egs_state", build_initial_egs_state("single_drone_smoke")); assert outcome.valid is True`. This is the load-bearing assertion: if our derived dict doesn't pass Contract 3, nothing else matters.
- `test_zone_polygon_encloses_all_waypoints` — for each drone waypoint, assert `lat_min <= w.lat <= lat_max and lon_min <= w.lon <= lon_max` after extracting the bbox from `zone_polygon[0]` and `zone_polygon[2]`. Catches buffer-sign bugs.
- `test_zone_polygon_is_closed_ccw` — assert `polygon[0] == polygon[-1]` (closed) and that the signed area is positive (CCW).
- `test_unknown_scenario_id_raises` — `with pytest.raises(FileNotFoundError): build_initial_egs_state("does_not_exist")`.
- **T-GAP-2** `test_build_initial_state_single_drone_smoke_degenerate_bbox` — single-drone × two-waypoint scenario. Assert post-buffer `lat_max - lat_min > 0` and `lon_max - lon_min > 0` (no zero-area bbox even when waypoints are tightly clustered).
- **T-GAP-3** `test_malformed_scenario_yaml_raises_clean_error` — write a temp YAML with a missing required field (e.g., drop `origin`); assert `pydantic.ValidationError` is raised by `load_scenario`. Catches the silent-half-built-state failure mode.

Run: `uv run pytest agents/egs_agent/tests/test_scenario_state.py -v` → expect 7/7 pass.

Commit: `feat(egs): scenario-derived initial state helper`.

---

### Task 2: Wire scenario_state into `agents/egs_agent/main.py`

**Files:**
- Modify: `agents/egs_agent/main.py:43-61`
- No new tests (Task 1 covers correctness; Task 6 covers integration).

**Change:**

Replace lines 43-61 (the hardcoded `egs_state = {…}` block) with:

```python
from agents.egs_agent.scenario_state import build_initial_egs_state

# Initial state derived from the active scenario YAML (Contract 3-compliant).
egs_state = build_initial_egs_state(CONFIG.mission.scenario_id)
```

That's the entire diff for this task. The downstream `state_ref`, `state`, and `publish_egs_state` paths are unchanged — they consume the dict shape, which is preserved.

Run a quick sanity check after the edit:

```bash
uv run python -c "
from agents.egs_agent.scenario_state import build_initial_egs_state
from shared.contracts import validate
s = build_initial_egs_state('disaster_zone_v1')
print('mission_id:', s['mission_id'])
print('zone bbox:', s['zone_polygon'][0], s['zone_polygon'][2])
print('survey_points:', len(s['survey_points']))
print('schema valid:', validate('egs_state', s).valid)
"
```

Expected output:
```
mission_id: disaster_zone_v1
zone bbox: [33.99955..., -118.50074...] [34.00125..., -118.49846...]
survey_points: 10
schema valid: True
```

Commit: `feat(egs): replace hardcoded zone_polygon with scenario-derived state`.

---

### Task 3: Initial-replan-after-first-telemetry fix + fire-and-forget replan

**Why:** today, `agents/egs_agent/main.py:73` ships `trigger_replan: True` at startup. The graph runs `replan` → `assign_survey_points` → returns `{}` because `drones_summary` is empty, then leaves `trigger_replan=False`. When telemetry arrives, `process_telemetry` only sets `trigger_replan=True` on `active → offline` transitions. So the initial assignment never fires under the live demo. Spec at `docs/06` Task 3 says "Initial assignment: once at mission start" — we need this to actually happen.

**Plus:** the `replan` LLM call takes 5-15s per attempt × up to 3 retries. If it runs synchronously inside the LangGraph tick, the coordinator stalls processing of incoming telemetry/findings until replan returns. Per the eng-review Q4 decision (2026-05-07), replan becomes a **fire-and-forget background task**: the graph node spawns the replan via `asyncio.create_task` and returns immediately. The background task publishes results directly to Redis (bypassing `messages_to_publish`, which is per-tick). A re-entrancy guard prevents stacking parallel replans.

**Files:**
- Modify: `agents/egs_agent/coordinator.py` (process_telemetry transition rule + fire-and-forget replan)
- Modify: `agents/egs_agent/main.py` (drop unconditional startup `trigger_replan=True`; pass `redis_client` into `EGSCoordinator` constructor for background-task publishes)
- Test:   `agents/egs_agent/tests/test_coordinator_initial_replan.py`

**Coordinator change** (`process_telemetry`, around line 65):

```python
# Existing transition: active → offline triggers replan.
if prev_status == "active" and new_status == "offline":
    trigger_replan = True

# NEW: first time we see this drone *and* it's reporting "active",
# trigger an initial replan so the assignment runs once drones are up.
if prev_status is None and new_status == "active":
    trigger_replan = True
```

**main.py change** (line 73):

```python
state = {
    "egs_state": egs_state,
    "incoming_telemetry": [],
    "incoming_findings": [],
    "incoming_commands": [],
    "messages_to_publish": [],
    "trigger_replan": False,   # was True; coordinator now triggers on first telemetry
}
```

**Background-task wiring (per Q4):**

```python
# In EGSCoordinator.__init__: accept redis_client + add re-entrancy state.
def __init__(self, validation_node, redis_client=None):
    self.validation_node = validation_node
    self.redis_client = redis_client
    self._replan_in_flight = False  # re-entrancy guard
    self.graph = self._build_graph()

# Replace synchronous replan node with fire-and-forget spawner.
async def replan(self, state):
    if self._replan_in_flight:
        logger.info("egs.replan skipped (already in flight)")
        return {**state, "trigger_replan": False}
    snapshot = deepcopy(state["egs_state"])
    asyncio.create_task(self._replan_impl(snapshot))
    return {**state, "trigger_replan": False}

async def _replan_impl(self, egs_state_snapshot):
    self._replan_in_flight = True
    try:
        assignment = await assign_survey_points(egs_state_snapshot, self.validation_node)
        if not assignment or not self.redis_client:
            return
        for a in assignment.get("arguments", {}).get("assignments", []):
            drone_id = a.get("drone_id")
            points = a.get("survey_point_ids", [])
            await self.redis_client.publish(
                per_drone_tasks_channel(drone_id),
                json.dumps({"task_id": f"task_{datetime.utcnow().timestamp()}",
                            "drone_id": drone_id, ...}),
            )
        # Optional: flip survey_points status via a redis-backed mutation
        # message back to coordinator (out of scope for GATE 2; survey_points
        # status tracking can stay in-memory for now).
    except Exception as e:
        logger.exception("egs.replan background task failed: %s", e)
    finally:
        self._replan_in_flight = False
```

**Tests** (`test_coordinator_initial_replan.py`):

- `test_first_telemetry_active_triggers_replan` — empty `drones_summary`, one incoming `agent_status: "active"` telemetry → `trigger_replan` flips True.
- `test_subsequent_active_telemetry_does_not_retrigger` — drone already in summary as "active", another "active" telemetry → `trigger_replan` stays False.
- `test_active_to_offline_still_triggers_replan` — regression test for the existing path; should keep passing.
- **T-GAP-1** `test_full_graph_first_active_publishes_task_via_background` — boots `EGSCoordinator(validation_node, redis_client=fake_redis)` where `fake_redis` is an `AsyncMock` capturing `publish()` calls. Mock `assign_survey_points` to return a deterministic two-drone assignment. Run `coord.graph.ainvoke(initial_state)` with a first-active telemetry. Assert: (a) graph returns within ~10ms (does NOT block on the LLM), (b) after `await asyncio.sleep(0.1)` the background task completes, (c) `fake_redis.publish` was called with channel `drones.<id>.tasks` and a task-shaped payload. **Critical regression-adjacent coverage.**
- `test_replan_reentrancy_guard_skips_concurrent_calls` — call `replan` twice in quick succession; assert only one background task spawned.

Run: `uv run pytest agents/egs_agent/tests/test_coordinator_initial_replan.py agents/egs_agent/tests/test_coordinator.py -v`.

Commit: `fix(egs): trigger initial replan + run replan as fire-and-forget background task`.

---

### Task 4: `recent_validation_events` consumer (Contract 11)

**Why:** Contract 11 says "agents/egs_agent aggregates the last N entries into `egs.state.recent_validation_events`". Today this field is initialized as `[]` and never updated. The dashboard's "Recent Validation Events" panel silently shows empty even when Kaleel's drone agent is logging retries.

**Files:**
- Create: `agents/egs_agent/validation_log_tail.py`
- Modify: `agents/egs_agent/coordinator.py` (refresh `recent_validation_events` on each tick)
- Test:   `agents/egs_agent/tests/test_validation_log_tail.py`

**Implementation:**

```python
# agents/egs_agent/validation_log_tail.py
"""Tail the validation event log (Contract 11) and surface the last N entries.

The log file is JSONL; we read it bottom-up, parse, and return up to N entries
in chronological order. This is the EGS-side consumer of what every agent
writes via shared.contracts.logging.ValidationEventLogger.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any, Dict, List

from shared.contracts import CONFIG, validate

LOG_PATH = Path(CONFIG.logging.base_dir) / "validation_events.jsonl"


def tail(n: int = 10, path: Path = LOG_PATH) -> List[Dict[str, Any]]:
    """Return the last n schema-valid validation events as parsed dicts,
    oldest-first.

    Per eng-review Q3 (2026-05-07), each parsed event is run through
    `validate("validation_event", evt)` before inclusion. This protects
    `egs_state.recent_validation_events` (which is itself in Contract 3) from
    being poisoned by a malformed-but-JSON-valid line, which would otherwise
    fail `validate("egs_state", ...)` downstream and break the dashboard
    publish path.

    Returns [] if the file does not exist or is empty. Lines that fail JSON
    parse OR schema validation are skipped silently (best-effort read of a
    live log).
    """
    if not path.exists():
        return []
    buf: deque[Dict[str, Any]] = deque(maxlen=n)
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not validate("validation_event", evt).valid:
                continue
            buf.append(evt)
    return list(buf)
```

**Coordinator wiring:** add a node `refresh_validation_events` to the graph that runs every 5th tick (per eng-review Q2, 2026-05-07) so the file I/O cost stays bounded on long runs:

```python
# In EGSCoordinator.__init__:
self._validation_refresh_counter = 0
VALIDATION_REFRESH_EVERY_N_TICKS = 5

# In _build_graph(), before the conditional edge to replan:
workflow.add_node("refresh_validation_events", self.refresh_validation_events)
# Run on every tick, after process_commands, before the should_replan branch.
workflow.add_edge("process_commands", "refresh_validation_events")

def should_replan(state):
    return "replan" if state.get("trigger_replan", False) else END

workflow.add_conditional_edges("refresh_validation_events", should_replan)
workflow.add_edge("replan", END)
```

```python
def refresh_validation_events(self, state):
    self._validation_refresh_counter += 1
    if self._validation_refresh_counter % VALIDATION_REFRESH_EVERY_N_TICKS != 0:
        return state
    from agents.egs_agent.validation_log_tail import tail
    egs_state = state["egs_state"].copy()
    egs_state["recent_validation_events"] = tail(n=10)
    return {**state, "egs_state": egs_state}
```

The 1-Hz `egs.state` publish runs in a separate task and reads the latest `egs_state` from `state_ref`, so the once-per-5-ticks refresh is plenty for dashboard latency (worst-case 5 graph ticks of staleness, typically <1s).

**Tests** (`test_validation_log_tail.py`):

- `test_tail_returns_empty_when_file_missing` — `tail(n=5, path=Path("/tmp/does_not_exist.jsonl")) == []`.
- `test_tail_returns_last_n_in_order` — write 12 lines (each a valid validation_event JSON), assert `tail(10)` returns lines 3-12 in order.
- `test_tail_skips_malformed_json_lines` — write 5 valid + 1 garbage line, assert garbage is skipped.
- `test_tail_skips_schema_invalid_events` (per Q3) — write a JSON-valid but schema-invalid event (e.g., missing `outcome` field) interleaved with valid events; assert it's filtered out by the `validate("validation_event", evt)` gate, valid events pass through. Closes the critical-gap failure mode flagged in eng-review.
- `test_coordinator_refreshes_recent_validation_events` (in `test_coordinator.py`) — write 3 events, run graph 5 times to hit the every-Nth-tick gate, assert `egs_state["recent_validation_events"]` has 3 entries.
- `test_coordinator_does_not_refresh_on_off_ticks` — run graph 4 times, assert `egs_state["recent_validation_events"]` is still `[]` (no refresh fired).

**Schema gotcha:** Contract 3 requires each event to have `{timestamp, agent, task, outcome, issue}` with `issue` being a `rule_id` enum or null. Test fixture writers must use `shared.contracts.logging.ValidationEventLogger` (or hand-roll a payload that passes `validate("validation_event", event)`) so we don't ship malformed entries that fail `validate("egs_state", ...)`.

Run: `uv run pytest agents/egs_agent/tests/test_validation_log_tail.py -v`.

Commit: `feat(egs): tail validation_events.jsonl into egs.state recent_validation_events`.

---

### Task 5: Findings flow observability + accepted-finding log line

**Why:** today `process_findings` increments counts but emits no INFO line under successful flow, only on rejected duplicates. When debugging the live integration ("is the EGS even seeing drone1's report_finding?") this is the difference between 30 minutes of `redis-cli MONITOR` and a one-line glance at `egs.log`.

**Files:**
- Modify: `agents/egs_agent/coordinator.py` (`process_findings`, line 87-95)
- Test:   extend `agents/egs_agent/tests/test_coordinator.py`

**Change:**

```python
def process_findings(self, state):
    egs_state = state["egs_state"].copy()
    counts = egs_state.setdefault("findings_count_by_type", {
        "victim": 0, "fire": 0, "smoke": 0, "damaged_structure": 0, "blocked_route": 0,
    })

    for f in state.get("incoming_findings", []):
        val_res = self.validation_node.validate_finding(f)
        if val_res.valid:
            ftype = f.get("type")
            if ftype in counts:
                counts[ftype] += 1
            logger.info(
                "egs.findings accepted source=%s type=%s finding_id=%s "
                "gps=(%s,%s) total_%s=%d",
                f.get("source_drone_id"), ftype, f.get("finding_id"),
                f.get("gps_lat"), f.get("gps_lon"), ftype, counts.get(ftype, 0),
            )
        else:
            logger.info("egs.findings rejected reason=%s detail=%s",
                        val_res.failure_reason, val_res.detail)

    return {**state, "egs_state": egs_state, "incoming_findings": []}
```

**Test:**

- `test_process_findings_logs_accepted_count` — use `caplog` fixture to assert the INFO line emits with `source=drone1`, `type=victim`, `total_victim=1`.
- `test_process_findings_increments_only_known_types` — feed an unknown finding type, assert no count change and `caplog` shows the rejection.

Commit: `chore(egs): log accepted finding lines for live integration debugging`.

---

### Task 6: Integration test — findings end-to-end through the coordinator

**Files:**
- Create: `agents/egs_agent/tests/test_main_findings_count_increment.py`

**What it covers:** boot the coordinator graph in-process (no Redis, no Ollama), inject three real-shape finding payloads, assert the resulting `egs_state` is schema-valid and `findings_count_by_type` increments.

```python
import asyncio
import pytest
from agents.egs_agent.coordinator import EGSCoordinator
from agents.egs_agent.validation import EGSValidationNode
from agents.egs_agent.scenario_state import build_initial_egs_state
from shared.contracts import validate


def _finding(drone_id: str, ftype: str, lat: float, lon: float, fid: str, ts: str):
    return {
        "finding_id": fid,
        "source_drone_id": drone_id,
        "timestamp": ts,
        "type": ftype,
        "severity": 3,
        "gps_lat": lat,
        "gps_lon": lon,
        "altitude": 25.0,
        "confidence": 0.85,
        "visual_description": "Test fixture finding for integration coverage.",
        "image_path": "/tmp/findings/test.jpg",
        "validated": True,
        "validation_retries": 0,
        "operator_status": "pending",
    }


def test_three_findings_increment_counts_and_remain_schema_valid():
    async def run():
        coord = EGSCoordinator(EGSValidationNode())
        state = {
            "egs_state": build_initial_egs_state("disaster_zone_v1"),
            "incoming_telemetry": [],
            "incoming_findings": [
                _finding("drone1", "victim",
                         34.0028, -118.5000, "f_drone1_001",
                         "2026-05-07T10:00:00.000Z"),
                _finding("drone2", "fire",
                         34.0000, -118.4972, "f_drone2_001",
                         "2026-05-07T10:00:01.000Z"),
                _finding("drone3", "smoke",
                         33.9990, -118.5000, "f_drone3_001",
                         "2026-05-07T10:00:02.000Z"),
            ],
            "incoming_commands": [],
            "messages_to_publish": [],
            "trigger_replan": False,
        }

        new_state = await coord.graph.ainvoke(state)

        counts = new_state["egs_state"]["findings_count_by_type"]
        assert counts["victim"] == 1
        assert counts["fire"] == 1
        assert counts["smoke"] == 1
        assert counts["damaged_structure"] == 0
        assert counts["blocked_route"] == 0

        outcome = validate("egs_state", new_state["egs_state"])
        assert outcome.valid, outcome.errors

    asyncio.run(run())
```

Run: `uv run pytest agents/egs_agent/tests/test_main_findings_count_increment.py -v`.

Commit: `test(egs): integration test for findings count increment + schema validity`.

---

### Task 7: Playwright MCP e2e — live findings visible in dashboard

**Why:** unit + integration tests cover the EGS in isolation. The GATE 2 acceptance criterion is "the dashboard shows findings driven by the real drone agent" — that needs a live cross-stack test like `test_e2e_playwright_dom_render.py`.

**Files:**
- Create: `frontend/ws_bridge/tests/test_e2e_playwright_egs_findings.py`

**Pattern:** mirror `test_e2e_playwright_dom_render.py` (already in repo). Reuse the `flutter_static_server` and `flutter_web_build_dir` fixtures from `frontend/ws_bridge/tests/conftest.py`. Boot:

1. System Redis (already-running, owned by the user — script uses `redis-cli ping` to confirm; skips with a clear message if not).
2. `agents/egs_agent/main.py` as a subprocess.
3. `dev_fake_producers.py --emit=findings --drone-id drone1` as a single-shot finding emitter (we *want* the EGS to consume this; `dev_fake_producers` writes the same Contract-4 shape Kaleel's drone agent does, so this exercises the EGS path end-to-end without needing a live Ollama).
4. `frontend/ws_bridge/main.py` (uvicorn on a free port).
5. Flutter static server (existing fixture).
6. Playwright Chromium against `?ws=ws://127.0.0.1:<port>/`.

**Assertions:**

- Wait for `[flt-semantics-identifier="finding-tile-<finding_id>"]` to attach (proves the bridge is forwarding Contract-4 findings).
- Read the DOM for the FindingsCount panel (which we'll add a stable `Semantics(identifier: 'findings-count-victim')` on as a *small Flutter-side change* — see Task 7b).
- Assert the rendered `victim` count is `>= 1` (proves EGS published `egs.state` with non-zero counts AND the bridge forwarded it).

**Task 7b (small Flutter side-change to enable the assertion):**

- Modify `frontend/flutter_dashboard/lib/widgets/findings_count_panel.dart` (find via grep — likely renders `findings_count_by_type`). Wrap each count with `Semantics(identifier: 'findings-count-<type>', label: '<type>: <n>', child: …)`.
- Add a Flutter widget test in `frontend/flutter_dashboard/test/findings_count_semantics_test.dart` mirroring the pattern in `test/standalone_mode_test.dart`: feed a forced `MissionState` with `findings_count_by_type.victim = 3`, assert `find.bySemanticsIdentifier('findings-count-victim'), findsOneWidget`.

Run:
```bash
uv run pytest frontend/ws_bridge/tests/test_e2e_playwright_egs_findings.py -v
cd frontend/flutter_dashboard && flutter test test/findings_count_semantics_test.dart
```

Commit: `test(egs+ui): playwright e2e for findings flowing through EGS to dashboard`.

---

### Task 8: MCP capture — live integration screenshot

**Files:**
- Append: `docs/runbooks/mcp-dom-verification.md` (new section "EGS findings count capture")
- Create: `docs_assets/dashboard-egs-state-counts.png`

**Steps** (added to runbook, executed by Ibrahim or Qasim with Playwright MCP):

1. Start system Redis: `redis-cli ping` should return `PONG`.
2. Start sim: `scripts/launch_swarm.sh single_drone_smoke --drones=drone1`.
3. Start EGS: `uv run python agents/egs_agent/main.py` (separate pane).
4. Start drone agent: `uv run python -m agents.drone_agent --drone-id drone1 --scenario single_drone_smoke`.
5. Start bridge: `uv run uvicorn frontend.ws_bridge.main:app --port 9090`.
6. Start Flutter static server (existing recipe in runbook).
7. Open Playwright MCP at `http://localhost:<flutter_port>/?ws=ws://localhost:9090/`.
8. Wait for the drone agent to emit at least one finding (`tail -F /tmp/gemma_guardian_logs/drone1.log | grep report_finding`).
9. Confirm `tail -F /tmp/gemma_guardian_logs/egs.log | grep "egs.findings accepted"` shows the EGS consumed it.
10. Take screenshot via MCP. Save to `docs_assets/dashboard-egs-state-counts.png`.
11. Verify the screenshot shows: header `connected`, drone1 plotted on the map inside the scenario-derived bbox, FindingsCount panel showing `victim: 1` (or whatever was reported), at least one FindingTile rendered.

**Acceptance:** screenshot committed; runbook section landed; one-line entry in `docs/sim-live-run-notes.md` dated 2026-05-07 referencing the file.

Commit: `docs(egs): add live findings-count capture to MCP runbook + screenshot`.

---

### Task 9: Doc updates

All landed in one commit at the end so the repo never sits in a half-documented state.

**Files:**
- Modify: `docs/STATUS.md` (Qasim row + risk register)
- Modify: `docs/06-edge-ground-station.md` (add "Scenario-derived initial state" subsection under State Schema)
- Modify: `docs/16-mocks-and-cuts.md` (clarify `zone_polygon` is now scenario-derived bbox, not hardcoded)
- Modify: `TODOS.md` (flip closed entries; preserve GATE 4 items as still open)

**STATUS.md Qasim row replacement:**

```markdown
### Qasim — EGS / Coordination

**Done:** EGS process scaffolded. Phase 4 command-translation path with finding allowlist + CI gate. **GATE 2 closure (2026-05-07):** scenario-derived initial state (`agents/egs_agent/scenario_state.py`) replaces hardcoded LA bbox; `findings_count_by_type` increments on real `drones.<id>.findings`; `recent_validation_events` consumes Contract 11 log; initial-replan trigger fires on first `agent_status="active"`. Live capture at `docs_assets/dashboard-egs-state-counts.png`. PRs: #4, #5, #<this>.

**Left (GATE 4 critical, Day 13 / May 15):** Replanning logic triggered by drone failure; multilingual command path producing real `preview_text_in_operator_language` via Gemma 4 E4B; standalone-mode tolerance when EGS goes offline; EGS-side subscriber for `egs.operator_actions`. The "wow moment" demo trigger (hallucination catch in survey-point assignment).
```

**STATUS.md risk register row:** flip the GATE 2 risk to ~~closed~~ with a note pointing at this PR.

**docs/06-edge-ground-station.md (Task 6 dedup window doc fix — folded in per eng-review):** under "## Task 6: Aggregated Finding Management", change "within 60 seconds" → "within 30 seconds" so the doc matches the locked validator at `agents/egs_agent/validation.py:20` (`DUPLICATE_WINDOW_S = 30.0`). One-line edit.

**docs/06-edge-ground-station.md (new subsection):** add under "## State Schema" before "## Implementation Notes":

```markdown
### Scenario-derived initial state

The initial `egs.state` is derived from the active scenario YAML at startup
by `agents/egs_agent/scenario_state.build_initial_egs_state`:

- `mission_id` ← `scenario.scenario_id`
- `zone_polygon` ← axis-aligned bbox of all drones[].waypoints, outset 50m
- `survey_points` ← one entry per scenario waypoint, `status="unassigned"`
- All other fields zeroed/empty per Contract 3.

This guarantees the dashboard's map panel renders a polygon that contains
the drones plotted from `drones.<id>.state`, and that survey assignment
operates on real waypoint IDs that the drone agent already knows.
```

**docs/16-mocks-and-cuts.md:** under the wildfire-segmentation entry, add:

```markdown
**Update 2026-05-07:** the predefined polygon is now derived from the
scenario YAML's waypoint extents (`scenario_state.build_initial_egs_state`),
not hardcoded in `agents/egs_agent/main.py`. The mock framing is unchanged
— we still don't run U-Net — but the polygon is at least guaranteed to
match the active scenario.
```

**TODOS.md:** flip closed entries:

- "EGS subscribes to real findings" → ✅ closed 2026-05-07 PR #<n>
- "Align zone_polygon with scenario YAML" → ✅ closed 2026-05-07 PR #<n>
- Leave open: replanning on drone failure, real multilingual preview, `egs.operator_actions` subscriber.

Commit: `docs: close GATE 2 EGS items + scenario-derived state subsection`.

---

## 4. Test plan summary

| Layer | File | Count | Run command |
|---|---|---|---|
| Unit (helper) | `agents/egs_agent/tests/test_scenario_state.py` | 5 | `uv run pytest agents/egs_agent/tests/test_scenario_state.py -v` |
| Unit (log tail) | `agents/egs_agent/tests/test_validation_log_tail.py` | 4 | `uv run pytest agents/egs_agent/tests/test_validation_log_tail.py -v` |
| Unit (coordinator) | `agents/egs_agent/tests/test_coordinator_initial_replan.py` | 3 | `uv run pytest agents/egs_agent/tests/test_coordinator_initial_replan.py -v` |
| Unit (coordinator delta) | extended `test_coordinator.py` | +2 | `uv run pytest agents/egs_agent/tests/test_coordinator.py -v` |
| Integration | `agents/egs_agent/tests/test_main_findings_count_increment.py` | 1 | `uv run pytest agents/egs_agent/tests/test_main_findings_count_increment.py -v` |
| Flutter widget | `frontend/flutter_dashboard/test/findings_count_semantics_test.dart` | 1 | `cd frontend/flutter_dashboard && flutter test test/findings_count_semantics_test.dart` |
| Playwright e2e | `frontend/ws_bridge/tests/test_e2e_playwright_egs_findings.py` | 1 | `uv run pytest frontend/ws_bridge/tests/test_e2e_playwright_egs_findings.py -v` |
| Live MCP capture | runbook step | (manual) | `docs/runbooks/mcp-dom-verification.md` "EGS findings count capture" section |

Full sweep before merging:

```bash
uv run pytest agents/egs_agent/tests/ frontend/ws_bridge/tests/ -q
cd frontend/flutter_dashboard && flutter test
```

Plus the Playwright e2e (kept separate because it needs Chromium + a free port) and the manual MCP capture (one-shot per shipping cycle).

---

## 5. Sequencing & risk

**Suggested commit order** (small, each green on its own):

1. Task 1 (helper + tests) — pure addition, no runtime change. Safe.
2. Task 2 (wire helper into main.py) — replaces hardcoded init. Reversible by reverting one diff.
3. Task 3 (initial replan trigger) — coordinator + main.py change + tests.
4. Task 4 (validation-log tail) — additive helper + graph node + tests.
5. Task 5 (findings observability log lines + tests).
6. Task 6 (integration test) — no production change.
7. Task 7 (Playwright e2e + Flutter semantics hooks) — small Flutter change + new e2e.
8. Task 8 (MCP capture + runbook).
9. Task 9 (docs).

**Risks:**

- **`recent_validation_events` schema gotcha** — events written by `ValidationEventLogger` must pass Contract 3's nested schema. If `tail()` returns a malformed event, `validate("egs_state", ...)` will fail downstream. Mitigation: Task 6's integration test asserts schema validity after a tick that calls `refresh_validation_events`; Task 4's `test_tail_skips_malformed_lines` covers the silent skip.
- **`assign_survey_points` LLM call on initial replan** — Task 3 makes the assignment fire for real on first telemetry. If the local Ollama Gemma 4 E4B is slow/unavailable, the EGS will retry 3× then fall back to round-robin (already implemented in `replanning.py:135-144`). The fallback is the safety net; we don't need to mock Ollama in the integration test (Task 6 sets `trigger_replan=False` to avoid the LLM call entirely; the unit tests mock `httpx.AsyncClient.post`).
- **Playwright e2e flake** — `test_e2e_playwright_dom_render.py` already proves the bridge → Flutter path works. The new e2e adds the EGS process. If the `dev_fake_producers --emit=findings` timing is faster than the EGS subscribe-and-process loop, the first finding may land before the EGS is ready. Mitigation: copy the `_wait_for_redis_subscriber` helper pattern from `test_e2e_phase3.py` (or add a 0.5s sleep after EGS boot) before publishing.
- **Schema-locked dedup window mismatch** — `docs/06` says 60s window, validator says 30s. Do not change either; this is documented in section 2.2 above. If a reviewer asks, point at this section.

---

## 6. What this plan does NOT do

These are explicitly GATE 4 (Day 13 / May 15) items per STATUS.md and stay deferred:

- **Replanning on drone-failure events** — still TODOS marker; unchanged here.
- **Real multilingual `preview_text_in_operator_language` via Gemma 4 E4B** — Phase 5+ stub stays in place.
- **EGS-side subscriber for `egs.operator_actions`** (operator-confirmed-dispatch path) — bridge-side stays as-is; EGS doesn't yet act on the dispatch confirmation.
- **The "wow-moment" hallucination-catch in survey-point assignment** — Approach 1 from `docs/10` stays GATE 4 critical.

These belong in a separate plan once GATE 2 lands.

---

## 7. Acceptance checklist (paste into PR description)

- [ ] `uv run pytest agents/egs_agent/tests/ -q` green (existing + 14+ new tests).
- [ ] `uv run pytest frontend/ws_bridge/tests/ -q` green.
- [ ] `cd frontend/flutter_dashboard && flutter test` green.
- [ ] `uv run pytest frontend/ws_bridge/tests/test_e2e_playwright_egs_findings.py` green.
- [ ] `docs_assets/dashboard-egs-state-counts.png` committed and referenced from the runbook.
- [ ] `docs/STATUS.md` Qasim row flipped to ✅ for GATE 2; risk register updated.
- [ ] `docs/06-edge-ground-station.md` "Scenario-derived initial state" subsection landed.
- [ ] `docs/16-mocks-and-cuts.md` updated.
- [ ] `TODOS.md` GATE 2 EGS entries closed; GATE 4 entries preserved.
- [ ] No changes to `shared/schemas/`, `shared/contracts/topics.yaml`, or `shared/VERSION` (contract version stays 1.0.0).
- [ ] `agents/egs_agent/main.py` no longer contains a hardcoded `[34.123, -118.568]` bbox (grep confirms).

---

## 8. Eng-review decision log (2026-05-07)

| # | Question | Choice | Rationale |
|---|---|---|---|
| Q1 | Task 4 (validation_log_tail) scope | Include now | Closes Contract 11 gap; ~30 min marginal cost; field is currently silently no-op'd |
| Q2 | refresh_validation_events cadence | Every 5th tick | Bounded I/O on long runs; <1s dashboard latency cost; ~5 lines |
| Q3 | tail() schema filtering | Filter through `validate("validation_event", ...)` | Closes critical-gap failure mode where a malformed event poisons every `egs.state` envelope |
| Q4 | Initial replan blocking | Fire-and-forget background task | Eliminates 5-15s coordinator stall on first-active; re-entrancy guard prevents stacking; ~20 lines |

Inline-fixed during review (no question, obvious):
- T-GAP-1 added: full-graph test asserting first-active fires the background-task replan and publishes to `drones.<id>.tasks`.
- T-GAP-2 added: single-drone-smoke degenerate-bbox test.
- T-GAP-3 added: malformed-YAML clean-error test.
- `_M_PER_DEG_LON` calibration comment in scenario_state.py.
- 60s→30s dedup-window doc fix in `docs/06-edge-ground-station.md` Task 6, folded into Task 9.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 5 issues found, 0 unresolved, 0 critical gaps after Q1-Q4 + 3 inline fixes |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — ready to implement. No CEO review needed (bug-fix-tier scope). No design review needed (single Flutter `Semantics()` hook is mechanical, covered by widget test).

