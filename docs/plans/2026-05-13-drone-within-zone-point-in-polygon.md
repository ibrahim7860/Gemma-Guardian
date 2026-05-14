# Plan — Drone-agent `_within_zone` migration to point-in-polygon

**Date:** 2026-05-13
**Owner:** Ibrahim
**Closes:** TODOS.md "Drone-agent: migrate `ValidationNode._within_zone` to point-in-polygon (ray-casting)"
**Prereq:** Closed by the same-day zone-from-egs-state migration (`docs/plans/2026-05-13-drone-zone-from-egs-state.md`). The polygon already arrives intact via `egs.state.zone_polygon`; today's migration is the *consumer* side.

## 1. Goal

Stop compressing the mission zone polygon to its enclosing bbox before `ValidationNode._within_zone` checks it. After this change, `GPS_OUTSIDE_ZONE` fires correctly for findings inside the bbox-of-polygon but outside the actual polygon shape.

## 2. Why

`ZoneProvider.update_from_polygon` currently runs `polygon_to_bbox(polygon)` and stores a 4-corner bbox. For rectangular polygons (today's only kind) this is exact. For non-rectangular polygons (L-shapes, operator-drawn carve-outs, fire-spread exclusions), the bbox is a strict superset, so the validator allows findings outside the operator's actual zone. That's a known loosening called out in `shared/contracts/zones.py:polygon_to_bbox` docstring and the zone-from-egs-state plan §3.4.

Trigger: the first non-rectangular `zone_polygon` EGS emits. Today, no caller produces one (EGS's `mission_zone_polygon` always emits rectangles). Doing this now means the day Qasim's `replan_mission` shapes zones, validation tightens automatically rather than silently regressing.

## 3. What changes (3 production files, 2 test files)

### 3.1 `agents/drone_agent/zone_provider.py`
- Internal state: `self._polygon: list[list[float]]` (was: `self._bbox: dict`).
- Bootstrap: `mission_zone_polygon(scenario, buffer_m)` (was: `mission_zone_bbox(...)`).
- `current()` returns `{"polygon": [[lat, lon], ...]}` (was: `{"lat_min": ..., "lat_max": ...}`).
- `update_from_polygon(polygon)` validates shape via `polygon_to_bbox` (reuse the existing point-shape checks), then stores `polygon` (not the bbox).

**Why the dict-wrapper shape:** `_within_zone` already dispatches on `"polygon" in bounds`. Wrapping keeps the dispatcher untouched and means callers that build `DroneState` directly with `zone_bounds={"polygon": [...]}` keep working. Bbox-shaped dicts (`{"lat_min": ...}`) remain a valid input to `_within_zone` so existing unit tests don't churn.

### 3.2 `agents/drone_agent/validation.py`
- `_point_in_polygon` ray-casting body unchanged (it's already correct).
- Replace the vertex-only tolerance loop with **edge-distance tolerance**: a point is considered inside if either ray-casting says inside OR perpendicular distance to any edge ≤ `tolerance_m`. New helper `_min_edge_distance_m(lat, lon, polygon) -> float` using equirectangular projection (consistent with `_haversine_m`'s scale at ~34°N).
- Reason: vertex-only tolerance (current behavior) misses points just outside an edge midpoint, which would cause GPS_OUTSIDE_ZONE false positives at the 50m fudge boundary. The bbox path uses an outset rectangle; the polygon path should match.

### 3.3 `agents/drone_agent/state_translator.py`
- No code change. It already accepts `zone_bounds: dict` and stores it verbatim on `DroneState`. The new dict shape `{"polygon": [...]}` flows through transparently.

### 3.4 `shared/contracts/zones.py`
- No code change. `polygon_to_bbox` stays — it's still used by EGS for non-polygon callers and by `ZoneProvider.update_from_polygon`'s shape-validation step.

### 3.5 `agents/drone_agent/reasoning.py`
- No code change. `render_user_message` already does `json.dumps(bundle.state.zone_bounds, indent=2)` — the polygon shape renders as JSON automatically. Prompt template `shared/prompts/drone_agent_user_template.md` keeps its `{zone_bounds_json}` placeholder.
- Side benefit: Gemma now sees the actual polygon (5 [lat,lon] pairs) instead of the 4-key bbox dict. The corrective prompt in `validation.py:130` already says "the mission zone bounds are {json.dumps(bundle.state.zone_bounds)}" so retries get the same polygon text.

## 4. Files NOT changed (and why)

- `shared/contracts/zones.py` — `polygon_to_bbox` retained for `ZoneProvider`'s shape-validation step (cheap reuse of its rejection logic).
- `agents/egs_agent/*` — EGS continues to emit polygons via `mission_zone_polygon`. Untouched.
- `agents/drone_agent/redis_io.py:EgsStateSubscriber` — still calls `update_from_polygon(polygon)`; the method's signature is unchanged.
- `shared/prompts/drone_agent_user_template.md` — `{zone_bounds_json}` placeholder unchanged.
- `agents/drone_agent/perception.py` — `DroneState.zone_bounds: dict` type unchanged.

## 5. Testing strategy

### 5.1 `agents/drone_agent/tests/test_zone_provider.py` (UPDATE existing, ~5 of 9 tests change shape)
- `test_bootstrap_returns_mission_wide_polygon` (RENAME from `_bbox`): assert `current() == {"polygon": mission_zone_polygon(scenario)}`.
- `test_bootstrap_encloses_every_drones_waypoints`: assert every waypoint is inside the polygon via `_point_in_polygon` (call the validator helper to avoid duplicating math).
- `test_update_from_rectangular_polygon`: assert `current() == {"polygon": new_poly}`.
- `test_update_from_non_rectangular_polygon_preserved_verbatim` (REPLACES the bbox-of-L test): assert L-shape stored verbatim, NOT bbox-compressed. **Iron-rule pin** for this migration's intent.
- `test_update_overrides_bootstrap`: assert polygon overwrite works.
- `test_update_rejects_polygon_with_fewer_than_three_points` / `_empty` / `_malformed_point`: unchanged behavior, polygon preserved on reject.
- `test_current_returns_defensive_copy`: shallow-copy of polygon list; mutating a returned point doesn't affect the next `current()` call. **Important**: needs a deeper copy than the bbox version had because polygons are lists-of-lists.

### 5.2 `agents/drone_agent/tests/test_validation.py` (ADD 3 new tests)

**T3 — iron-rule regression for the tightening:**
```python
def test_finding_inside_bbox_but_outside_l_polygon_is_rejected():
    """Pins the intentional tightening of the 2026-05-13 PIP migration.
    Before: GPS_OUTSIDE_ZONE did not fire for findings inside polygon_to_bbox
    but outside the actual polygon shape. After: it does.
    """
```
L-shape `[(0,0),(0,2),(1,2),(1,1),(2,1),(2,0),(0,0)]`. Point `(1.5, 1.5)` is inside the [0..2]×[0..2] bbox but outside the L's body. Assert `failure_reason == RuleID.GPS_OUTSIDE_ZONE`. Note this test uses a synthetic small-numerics polygon, so the 50m → ~4.5e-4 deg tolerance is far smaller than the 0.5-unit margin — no tolerance pollution.

**T4 — edge-distance tolerance works:**
A point ~30m outside a rectangle edge passes validation (within the 50m GPS_ZONE_TOLERANCE_M). A point ~80m outside the edge fails. Uses real lat/lon spacing around (34, -118).

**T5 — polygon shape passes validation for inside points:**
`zone_bounds={"polygon": mission_zone_polygon(scenario)}`. Finding at the mission centroid passes.

### 5.3 Existing tests — sweep impact

**Unchanged (bbox-shaped `zone_bounds` still accepted by `_within_zone`):**
- `test_validation.py::test_gps_outside_zone` (uses bbox shape) — keep
- `test_validation.py::test_severity_confidence_mismatch` (zone path not exercised) — keep
- `test_validation.py::test_visual_description_too_short` etc. — keep
- T1 `test_validation_uses_bootstrap_zone_before_first_egs_state` — needs update: bootstrap now returns `{"polygon": ...}`, so the test's `bootstrap["lat_min"]` keys break. Rewrite to derive centroid from polygon vertices.
- T2 `test_finding_inside_mission_zone_outside_old_per_drone_slice_is_valid` — uses `ZoneProvider.current()` shape. Same fix as T1.

**Test files that hand-build `zone_bounds=` dicts:**
- `test_state_subscriber.py` — uses ZoneProvider in fixtures. Verify shape change propagates without code touch.
- `test_runtime_*.py` — same.
- `test_state_translator.py` — passes `zone_bounds=` dict. Add a polygon-shaped case if not present; existing bbox case stays.
- `sim/manual_pilot.py` — uses `mission_zone_bbox`. Switch to `mission_zone_polygon` + wrap in `{"polygon": ...}` so manual_pilot's validator path uses the same shape as production.
- `sim/tests/test_manual_pilot.py` — update assertions to polygon shape.

### 5.4 Cross-cutting (no new files)

Run full repo test sweep (`uv run pytest agents/ shared/tests/ sim/tests/`). Acceptance: ≥354 passing (the baseline after the zone-from-egs-state migration). No new failures attributable to this change.

## 6. Risks & open questions

| Risk | Mitigation |
|---|---|
| Defensive-copy regression: `dict(self._polygon_dict)` is a shallow copy; consumer mutates a point and corrupts state. | New helper `_copy_polygon(p)` deep-copies the list-of-lists. Locked by `test_current_returns_defensive_copy`. |
| Edge-distance helper introduces a math bug. | Property test: a point exactly on an edge has distance 0; a point at the vertex has distance 0; a point perpendicular to an edge midpoint at distance d has computed distance ≈ d (±1%). |
| `_within_zone` ambiguity if both `polygon` and `lat_min` keys present. | Dispatcher already checks `polygon` first (line 221 of validation.py), so polygon wins. Document this in the function docstring. |
| EGS test that asserts the OLD bbox semantics (none found in audit). | If grep surfaces one during implementation, update or call out. |
| Performance: ray-casting + edge-distance is O(n_vertices). For our 5-vertex polygons this is ~30 ops, negligible. | No mitigation needed. |

## 7. Out-of-scope (deliberately)

- Switching to `shapely`. Adds a heavy dep for ~40 LOC of math we already have. Defer until ≥1 caller needs Minkowski / buffering / convex-hull primitives.
- Rendering the polygon as a human-readable shape ("a 5-sided polygon centered at...") in the corrective prompt. Today's `json.dumps` is fine.
- Updating EGS's `mission_zone_polygon` to emit non-rectangles. That's Qasim's `replan_mission` future work; this plan just makes the consumer ready.

## 8. Acceptance

1. `uv run pytest agents/drone_agent/tests/test_zone_provider.py` green.
2. `uv run pytest agents/drone_agent/tests/test_validation.py` green incl. T3/T4/T5.
3. Full sweep: `uv run pytest agents/ shared/tests/ sim/tests/` ≥354 passing.
4. `uv run python -m agents.drone_agent --drone-id drone1 --scenario disaster_zone_v1` boots without crashing on the new polygon shape (smoke test; no live Ollama required since the validator runs before reasoning).
5. `git grep -n "polygon_to_bbox" agents/drone_agent/` shows only the shape-validation call inside `update_from_polygon` — no remaining production uses on the drone side.
6. TODOS.md "Drone-agent: migrate `ValidationNode._within_zone` to point-in-polygon" CLOSED with a resolution block citing this plan + commit.
