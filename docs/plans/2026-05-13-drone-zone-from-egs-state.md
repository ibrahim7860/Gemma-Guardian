# 2026-05-13 — Migrate drone agent zone source to `egs.state.zone_polygon`

**Owner:** Ibrahim (lane-stolen from Kaleel — TODOS.md:92-98).
**Status:** Drafted 2026-05-13.
**TODO closed by this plan:** "Migrate drone agent zone source to `egs.state.zone_polygon` (GATE 4)".

## 1. Why now

Today every drone agent derives its survey bbox at boot from its own waypoints in the scenario YAML (`agents/drone_agent/zone_bounds.py:derive_zone_bounds_from_scenario`). The EGS independently derives a *mission-wide* polygon from the same YAML (`agents/egs_agent/scenario_state.py:_bbox_polygon`) and publishes it on `egs.state.zone_polygon`. Two derivations, one input — if either drifts (e.g., Qasim's `replanning.assign_survey_points` reshapes zones for GATE 4, or someone toggles the buffer), the validator and the dashboard diverge.

The architecture decision documented in `docs/05-per-drone-agent.md:263` and `docs/06-edge-ground-station.md:187` already calls for this migration. GATE 4 is the trigger.

## 2. Semantics change (intentional)

| Today (per-drone) | After (mission-wide) |
|---|---|
| Each drone's zone = bbox of its OWN home + waypoints + 50m | Every drone's zone = bbox of ALL drones' waypoints + 50m |
| `GPS_OUTSIDE_ZONE` fires for findings outside one drone's slice | Fires only for findings outside the mission-wide zone |
| Source: scenario YAML, at boot | Source: `egs.state.zone_polygon`, live |

This is a deliberate loosening. With GATE 4's dynamic survey-point reassignment, a drone may legitimately operate anywhere in the mission zone. The per-drone slice was a GATE 2 conservatism.

## 3. Approach — bootstrap from scenario, live-update from EGS

To avoid coupling drone startup to EGS being up (the TODO calls this out as the migration's only material cost), we bootstrap from the scenario YAML using EGS's *mission-wide* semantics, then overwrite on first `egs.state`.

### 3.1 New module: `agents/drone_agent/zone_provider.py`

```python
class ZoneProvider:
    """Mutable holder for the active mission zone bbox.

    Bootstrapped from the scenario YAML at construction (mirrors EGS's
    _bbox_polygon semantics: bbox of ALL drones' waypoints + 50m). Overwritten
    on every egs.state message that carries a valid zone_polygon.
    """

    def __init__(self, scenario: Scenario, buffer_m: float = 50.0): ...
    def current(self) -> dict: ...                       # {lat_min, lat_max, lon_min, lon_max}
    def update_from_polygon(self, polygon: list[list[float]]) -> None: ...
```

`ValidationNode` and `state_translator.translate_drone_state` keep receiving a `dict` (no change to their call sites once the provider's `current()` is wired in).

### 3.2 New subscriber: `EgsStateSubscriber` in `redis_io.py`

Mirrors `LinkStatusSubscriber` exactly. Subscribes to `egs.state`, validates against the `egs_state` JSON schema, extracts `zone_polygon`, calls `zone_provider.update_from_polygon(...)`. Drops malformed payloads, logs once on success per session.

### 3.3 Shared mission-zone helpers (DRY fix per eng-review A1)

Plan-eng-review A1: bootstrapping the drone agent from a *mirrored* `_bbox_polygon` would duplicate EGS code that already produces the canonical polygon. Single-source-of-truth resolution: extract `_bbox_polygon` from `agents/egs_agent/scenario_state.py:24-39` into a new module both EGS and the drone agent import.

- New module: `shared/contracts/zones.py`
  - `mission_zone_polygon(scenario: Scenario, buffer_m: float = 50.0) -> list[list[float]]` — exact `_bbox_polygon` semantics, moved verbatim.
  - `polygon_to_bbox(polygon: list[list[float]]) -> dict` — used by `ZoneProvider.update_from_polygon`. Returns `{lat_min, lat_max, lon_min, lon_max}`.
  - `mission_zone_bbox(scenario: Scenario, buffer_m: float = 50.0) -> dict` — convenience: `polygon_to_bbox(mission_zone_polygon(scenario))`. Used by `ZoneProvider` bootstrap.
- `agents/egs_agent/scenario_state.py` — replace local `_bbox_polygon` with `from shared.contracts.zones import mission_zone_polygon`. Keep `ZONE_BUFFER_M` constant local to EGS (it's the EGS-policy buffer) and pass it explicitly.
- `agents/drone_agent/zone_provider.py` — imports `mission_zone_bbox` and `polygon_to_bbox` from the shared module. No local re-derivation.

After this change, the 50m buffer policy lives in EGS (`scenario_state.py:11`) and is the *only* place that decides buffer width. The drone agent bootstrap calls with the same constant (also imported from `agents.egs_agent.scenario_state` or re-exposed via `shared.contracts.zones`) so the two cannot drift.

`derive_zone_bounds_from_scenario` in `zone_bounds.py` is no longer needed by production code. Test fate is decided in §4.2 below (per eng-review Q1).

### 3.4 Polygon → bbox conversion

Lives in `shared/contracts/zones.py:polygon_to_bbox` (see §3.3). `ZoneProvider.update_from_polygon` calls it. Correct for rectangular polygons EGS currently emits; bbox-of-polygon is a strict superset, so when `replan_mission` eventually emits non-rectangular polygons, validation stays *safe* (no false `GPS_OUTSIDE_ZONE`) but loose. New TODO captured in §10 for the eventual ray-casting migration.

## 4. Touch list

### 4.1 New files

- `shared/contracts/zones.py` (~40 LOC) — `mission_zone_polygon`, `mission_zone_bbox`, `polygon_to_bbox`. Source of truth for both EGS and drone agent.
- `shared/tests/test_zones.py` (~80 LOC, 6 tests) — bbox correctness, polygon shape (CCW closed), buffer math, polygon→bbox correctness.
- `agents/drone_agent/zone_provider.py` (~40 LOC)
- `agents/drone_agent/tests/test_zone_provider.py` (~120 LOC, 8–10 tests)
- `agents/drone_agent/tests/test_egs_state_subscriber.py` (~140 LOC, 6–8 tests, fakeredis-driven, same shape as `test_link_status_subscriber.py`)

### 4.2 Edited files

- `agents/drone_agent/__main__.py:103-105` — replace `derive_zone_bounds_from_scenario(...)` call with `ZoneProvider(scenario)`; pass to runtime.
- `agents/drone_agent/runtime.py` — accept `zone_provider: ZoneProvider` (typed instance, not a `Callable` — per eng-review A2 — matches `LinkStateMonitor` injection pattern at `runtime.py:126-131`); spin up `EgsStateSubscriber`; thread provider into `StateSubscriber`.
- `agents/drone_agent/redis_io.py` — `StateSubscriber.__init__` takes `zone_provider: ZoneProvider` (typed) instead of `zone_bounds: dict`. Calls `zone_provider.current()` per state message. New `EgsStateSubscriber` class mirrors `LinkStatusSubscriber` verbatim.
- `agents/drone_agent/state_translator.py` — no signature change (still takes a `dict` — runtime calls provider once before passing in).
- `agents/drone_agent/validation.py:128-132` — corrective prompt reworded (per eng-review Q3): "your assigned zone bounds" → "the mission zone bounds" so the retry-loop prompt Gemma reads is accurate post-migration.
- `agents/drone_agent/zone_bounds.py` — **DELETED** (eng-review Q1 resolution: delete; no production callers remain).
- `agents/egs_agent/scenario_state.py:24-39` — replace local `_bbox_polygon` with `from shared.contracts.zones import mission_zone_polygon`. Pass `ZONE_BUFFER_M` explicitly.
- `agents/drone_agent/tests/test_runtime_e2e.py`, `test_runtime_buffer_integration.py`, `test_runtime_link_state_integration.py`, `test_agent_state_publish.py`, `test_state_subscriber.py` — update fixtures to construct `ZoneProvider(scenario)` instead of static bbox dicts (mechanical, ~5-10 lines per test file).
- `agents/drone_agent/tests/test_zone_bounds.py` — DELETED (the function it tests is gone; the new helper is covered by `shared/tests/test_zones.py`).


### 4.3 Docs

- `docs/05-per-drone-agent.md:263` — update the "GATE 4 will migrate" sentence to past tense.
- `docs/06-edge-ground-station.md` — note that drone agents consume `zone_polygon` (single-direction flow now real, not aspirational).
- `TODOS.md:92-98` — close the "Migrate drone agent zone source" entry with the resolution paragraph (same style as the closed entries above it).

## 5. Test plan

### 5.1 `test_zone_provider.py`

- `test_bootstrap_returns_mission_wide_bbox` — provider built from `disaster_zone_v1` scenario; assert bbox encloses all drones' waypoints and matches EGS's `_bbox_polygon` corner extraction.
- `test_update_from_rectangular_polygon` — feed a 5-point CCW polygon; assert `current()` returns matching bbox.
- `test_update_from_non_rectangular_polygon` — feed an L-shaped polygon; assert bbox is the enclosing bbox (correct loose behavior).
- `test_update_overrides_bootstrap` — bootstrap, then update with a different polygon; assert `current()` reflects the update.
- `test_polygon_with_fewer_than_three_points_rejected` — malformed input doesn't mutate state.
- `test_empty_polygon_rejected` — same.

### 5.2 `test_egs_state_subscriber.py`

Pattern copied verbatim from `test_link_status_subscriber.py`:

- `test_valid_egs_state_updates_zone_provider` — publish a schema-valid `egs.state`; assert provider's `current()` reflects the new bbox within 1s.
- `test_schema_invalid_dropped` — publish missing `zone_polygon`; assert provider unchanged.
- `test_malformed_json_dropped` — publish non-JSON; assert provider unchanged + warning logged.
- `test_subsequent_updates_overwrite` — two valid messages with different polygons; assert provider holds the latest.
- `test_stop_unsubscribes_cleanly` — basic lifecycle.

### 5.3 Integration regression

`test_runtime_e2e.py::test_zone_updates_propagate_through_validation`:
1. Boot runtime with bootstrap zone.
2. Publish an `egs.state` with a shrunken `zone_polygon`.
3. Publish a `drones.<id>.state` whose position falls outside the new (but inside the old) bbox.
4. Drive an agent step that would produce a finding at that GPS.
5. Assert `validation_events.jsonl` records `GPS_OUTSIDE_ZONE`.

### 5.4 Startup-race coverage (per eng-review T1)

`test_runtime_e2e.py::test_validation_uses_bootstrap_zone_before_first_egs_state`:
1. Boot runtime against an empty Redis (no `egs.state` published).
2. Drive an agent step.
3. Assert `_within_zone` evaluates against the bootstrap mission-wide bbox (computed via `shared.contracts.zones.mission_zone_bbox`), not undefined.
4. Then publish `egs.state` with a shrunken polygon and assert the provider updates within the next state-republish tick.

### 5.5 Semantics-change regression (per eng-review T2, iron rule)

`test_validation.py::test_finding_inside_mission_zone_outside_old_per_drone_slice_is_valid`:
1. Construct a `disaster_zone_v1` scenario.
2. Compute (a) the mission-wide bbox via `shared.contracts.zones.mission_zone_bbox` and (b) the OLD per-drone bbox via the pre-migration logic (inline the math in the test, since the function is deleted).
3. Find a lat/lon that lies inside (a) but outside (b) — e.g., on the territory of a peer drone.
4. Build a `PerceptionBundle` with `zone_bounds = (a)`, GPS = the chosen point.
5. Assert `ValidationNode._validate_report_finding(...)` returns `valid=True` (no `GPS_OUTSIDE_ZONE`).

This test exists specifically to pin the intentional semantics change. A future code-reader who tries to "restore" per-drone scoping will trip this test and read the docstring explaining why.

## 6. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Drone boots before EGS publishes first `egs.state` | High at fresh-start; ~always at demo time | Bootstrap from scenario YAML using EGS-matching semantics. First valid `egs.state` overwrites (typically <1s after EGS spawn). |
| EGS publishes a malformed `zone_polygon` mid-run | Low — schema-validated upstream | Subscriber drops the message, provider keeps last-known-good. Logged. |
| `replan_mission` emits a non-rectangular polygon | Out of scope today; possible GATE 4+ | Bbox-of-polygon is a strict superset, so it remains *safe* (no false GPS_OUTSIDE_ZONE). Future work: point-in-polygon. |
| Per-drone validator regression | Medium — semantics intentionally change | Documented in `docs/05-per-drone-agent.md`. The architectural improvement IS the regression. |
| Test-fixture churn breaks unrelated drone-agent tests | Medium — 5 test files touched | Each touch is mechanical (`ZoneProvider(scenario)` instead of dict). Run full suite locally before PR. |

## 7. Estimate

- Code: ~3.5 hours (subscriber + provider + threading + `shared/contracts/zones.py` extraction + EGS edit).
- Tests: ~2.5 hours (new tests + fixture updates across 5 existing test files + 2 new semantics-pinning tests from eng-review T1/T2).
- Docs + PR + /review pass: ~1 hour.
- **Total: ~7 hours, M1-friendly throughout.**

## 8. Out of scope

- True point-in-polygon containment in `ValidationNode._within_zone`. Tracked as new TODO in §10.
- Updating the reasoning prompt to render the polygon instead of the bbox (`reasoning.py:100` currently `json.dumps(zone_bounds)`). The bbox JSON shape stays exactly the same, so the prompt is unaffected.
- Migrating `egs.state` consumption to the bridge or dashboard. Out of this lane.
- Event-driven `ZoneProvider.add_listener(...)` (eng-review A3). YAGNI today; no consumer needs change-events.

## 10. New TODOs to capture

- **Drone-agent: migrate `ValidationNode._within_zone` to point-in-polygon (ray-casting).** Why: when `replan_mission` emits non-rectangular polygons, bbox-of-polygon is loose (false negatives are impossible; false positives become possible). Pros: tighter validation, correct semantics for arbitrary mission shapes. Cons: ~30 LOC + shapely dep OR hand-rolled ray-cast. Context: today's `_bbox_polygon` only emits rectangles, so bbox-of-polygon is exact. The day Qasim's `replan_mission` produces a non-rectangle, this becomes load-bearing. Owner: open. Add to TODOS.md "Drone-Agent Follow-ups" on land.

## 9. Comms

Before starting: ping Kaleel on Slack — "Picking up the zone-polygon migration TODO since you're heads-down on GATE 3. Won't land before your fine-tune signal; will tag you on the PR."

After landing: standup line + TODOS.md close-out paragraph in the same style as the GH #32 / Phase G entries on STATUS.md.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 8 issues, 0 critical gaps, all resolved |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**Eng review summary (2026-05-13):** 1 architecture decision (A1 — bootstrap DRY), 2 code-quality applied (Q1 delete `zone_bounds.py`, Q3 reword corrective prompt), 2 test gaps closed (T1 startup-race, T2 semantics-pinning regression). A2 (typed instance instead of `Callable`) and 1 new TODO captured (§10 point-in-polygon migration) applied to plan. A3 (event listener) deferred as YAGNI.

**UNRESOLVED:** 0.
**VERDICT:** ENG CLEARED — ready to implement. Run `/ship` when done.

