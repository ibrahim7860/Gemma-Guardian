# TODOS — FieldAgent

Deferred work captured during planning and reviews. Each entry includes context for whoever picks it up.

## Phase 4+ (post-Dashboard MVP)

### EGS subscriber for `egs.operator_actions`
- **What:** EGS-side subscriber that consumes `egs.operator_actions` Redis channel (operator approve/dismiss decisions on findings) and reflects approved findings into the next `state_update` envelope.
- **Why:** Phase 3 ships the bridge → Redis publish path with a typed schema. Without an EGS subscriber, operator decisions land in Redis but never propagate back to the dashboard as confirmed state. Phase 3 visual UI uses two-stage feedback (grey check = bridge ack, green check = EGS-confirmed) precisely so this is forward-compatible.
- **Pros:** Closes the loop; green-check-on-confirmed becomes truthful, not aspirational; multi-operator scenarios work correctly.
- **Cons:** Couples to EGS state shape, needs replan logic on approve.
- **Context:** Schema at `shared/schemas/operator_actions.json` (added in Phase 3). Topic constant in `shared/contracts/topics.yaml` and generated `topics.dart`. Bridge stamps `bridge_received_at_iso_ms` on the payload before publish; EGS dedupes on `command_id`.
- **Depends on:** Phase 3 merge.
- **Owner:** Person 3 (EGS).

### Static aerial base image for map panel
- **What:** Replace procedural grid background in `frontend/flutter_dashboard/lib/widgets/map_panel.dart` with a static aerial JPEG/PNG, projected onto the locked bbox.
- **Why:** Demo polish. Procedural grid is functional but lower-fidelity than the docs/07-operator-interface.md hero shot. Judges respond to recognizable geography.
- **Pros:** Demo storytelling improvement. No new dependencies (just an asset and a `Image.asset` call).
- **Cons:** Coupling between scenario YAML and Flutter assets. Need `base_image_path` field in `disaster_zone_v1.yaml` plus a bbox so projection aligns.
- **Context:** Scenario YAML lives in `sim/scenarios/`. Frame library curated by Person 5. Map projection in Phase 3 uses equirectangular with cos(midLat) longitude correction.
- **Depends on:** Person 5's scenario fixture work (xBD or public aerial source).
- **Owner:** Person 5 with handoff to Person 4 for asset wiring.

### Map marker tap/hover interactivity
- **What:** Click a finding marker on map → highlight corresponding row in Findings panel. Click a drone marker → highlight Drone Status row.
- **Why:** Operator UX expectation. Phase 3 ships read-only markers because hit-testing in CustomPaint adds work that doesn't pay off until the operator workflow gets richer.
- **Pros:** More useful dashboard.
- **Cons:** CustomPaint hit-testing is fiddly; better with `Stack<Positioned>` per marker. May warrant a refactor.
- **Context:** Map panel uses pure CustomPaint with `_DroneMarker` and `_FindingMarker` private widgets passed projection coordinates.
- **Owner:** Person 4 (later phase if time).

### Validation event ticker on drone status panel
- **What:** Show recent validation failures per drone on the status card (count + last-event timestamp).
- **Why:** Demo storytelling — "Gemma 4 self-corrects, you can see it." Day-10 work in the roadmap.
- **Context:** `state_update.validation_events` already exists in the schema; bridge emits, dashboard ignores it. Needs a small panel addition.
- **Owner:** Person 4 (Day 10).

## Phase 3 in-scope work tracked here for breadcrumbs

(none — see `docs/superpowers/specs/2026-05-02-phase3-dashboard-mvp-design.md` once it lands)
