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

### ~~Bridge finding_id allowlist for `egs.operator_actions`~~ (closed in Phase 4)
**CLOSED Phase 4** — guard lives in `frontend/ws_bridge/main.py` finding_approval branch via `aggregator.has_finding()`. Original entry retained below for historical context.

- **What:** When the bridge receives a `finding_approval`, cross-check the inbound `finding_id` against the aggregator's known-finding set before publishing to Redis. Reject unknown finding_ids with `unknown_finding_id` echo.
- **Why:** Today the bridge republishes any well-formed finding_id verbatim. A buggy or malicious WS client can send fabricated finding_ids that get persisted on `egs.operator_actions`, polluting the EGS view of operator decision history.
- **Pros:** Tighter integrity on the operator-decision audit trail.
- **Cons:** Couples the inbound handler to aggregator internal state. Aggregator currently keeps findings in an `OrderedDict` keyed by finding_id; adding a `has_finding(id)` accessor is the right shape.
- **Context:** Surfaced by the Phase 3 adversarial review. Bridge integrity is fine while there's no EGS subscriber yet (Phase 4 work). This becomes load-bearing when Phase 4 EGS subscribes and writes audit records.
- **Depends on:** Could land before Phase 4 EGS, but practically belongs in the same PR as the EGS subscriber.
- **Owner:** Person 4 (bridge changes) and Person 3 (EGS coordination).

### ~~Validation event ticker on drone status panel~~ (closed in Phase 4)
**CLOSED Phase 4** — ticker line lives in `frontend/flutter_dashboard/lib/widgets/drone_status_panel.dart`, driven by `egs_state.recent_validation_events`. Original entry retained below for historical context.

- **What:** Show recent validation failures per drone on the status card (count + last-event timestamp).
- **Why:** Demo storytelling — "Gemma 4 self-corrects, you can see it." Day-10 work in the roadmap.
- **Context:** `state_update.validation_events` already exists in the schema; bridge emits, dashboard ignores it. Needs a small panel addition.
- **Owner:** Person 4 (Day 10).

### Bridge lifespan teardown ordering (Phase 5+)
- **What:** Reorder `frontend/ws_bridge/main.py` lifespan teardown so `_stopping=True` is set on the subscriber and tasks are awaited BEFORE `subscriber.stop()` calls `aclose()` on the pubsub. Today the cancel-then-stop-then-await sequence allows `subscribe_task` to be mid-`pubsub.get_message()` when `aclose()` runs.
- **Why:** Surfaced by the Phase 4 adversarial review (finding #6). Functional impact today is noisy stderr on every shutdown; could become a real CI flake if `RuntimeError: Event loop is closed` traces start failing test runs.
- **Pros:** Clean shutdown logs; resilient to future broadcaster additions.
- **Cons:** Touches the lifespan ordering that Phase 3 was carefully fixed to behave a specific way. Test surface is thin (lifespan tests already exist; need to verify they catch the change).
- **Context:** Phase 3 added the `cancel-before-await` pattern; Phase 4 extends it to three tasks (emit, subscribe, translation_broadcaster). The fix is to also move `pubsub.aclose()` AFTER all task awaits.
- **Owner:** Person 4.

### Repo-wide $ref convention pass (Phase 5+)
- **What:** Decide on a single `$ref` style for `shared/schemas/` — currently every schema uses relative refs (`_common.json#/$defs/...`). Either keep relative as the formal convention and document it, OR convert to absolute URIs (`https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/_common.json#/$defs/...`) across every schema in one coordinated PR.
- **Why:** Surfaced by the Phase 4 Task 2 code review. Phase 4 originally tried to use absolute URIs in two new schemas (per adversarial finding #3 — concern that relative refs resolve by URI-base coincidence). Code review correctly noted that mixing styles in one directory is worse than the bug it tried to prevent. Phase 4 reverted to relative refs to match the existing convention. The forward-looking concern about $id moves still applies — it just applies uniformly to every schema, not just Phase 4's.
- **Pros:** Consistency. Easier to refactor `$id` bases later (search-and-replace works without missing schemas).
- **Cons:** Touches every schema in `shared/schemas/`. CI burden if any test depends on a specific $ref shape.
- **Context:** Reverted in commit `<phase4-revert-sha>`. The Phase 4 spec §4.3 documents the deferral rationale.
- **Owner:** Person 4 or whoever picks up shared/contracts work.

### Move `ValidationEventLogger.log` off the subscriber dispatch path (Phase 5+)
- **What:** `frontend/ws_bridge/redis_subscriber.py:_log_validation_failure` calls `self._validation_logger.log(...)` synchronously inside `_handle_message`. The logger does sync disk I/O (`open(..., "a")`).
- **Why:** Surfaced by the Phase 4 adversarial review (finding #7). A misbehaving EGS spamming malformed translations or findings could stall the subscriber's Redis drain on disk I/O latency, especially on slow disks or when the validation log is being rotated.
- **Pros:** Subscriber drain stays fast and predictable under any upstream noise.
- **Cons:** Adds an `asyncio.Queue` + writer task (mirrors the Phase 4 translation_queue pattern). Crash-recovery: queued events lost on bridge crash — acceptable for a debug log, document as such.
- **Context:** Logger lives in `shared/contracts/logging.py`. Either wrap each `.log()` call in `asyncio.get_running_loop().run_in_executor(None, ...)` or build a dedicated async writer. The latter is cleaner if other call sites also start hitting hot paths.
- **Owner:** Person 4 (bridge changes) + minimal coordination with shared/contracts owners.

## Phase 3 in-scope work tracked here for breadcrumbs

(none — see `docs/superpowers/specs/2026-05-02-phase3-dashboard-mvp-design.md` once it lands)
