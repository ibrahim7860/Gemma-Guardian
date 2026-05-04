# TODOS — FieldAgent

Deferred work captured during planning and reviews. Each entry includes context for whoever picks it up.

## Phase 4+ (post-Dashboard MVP)

### Expand Playwright coverage to multi-drone scenarios (Day 8+)
- **What:** Today's `bridge_e2e` Playwright job covers single-drone flows only — the pipeline fixture starts one `dev_fake_producers.py` instance for `drone99`. Once Person 5's multi-drone scenario YAML lands (Day 8: 2 drones, Day 10: 3 drones), expand `test_e2e_playwright.py` to cover: (a) dashboard renders one drone status card per drone, (b) findings from both drones populate the findings panel without collision, (c) language-aware translation works regardless of which drone published the finding.
- **Why:** Multi-drone is the headline demo story ("a swarm coordinates"). Today's tests would silently pass even if the dashboard rendered drone1 over drone2 or dropped one drone's findings. Real demo regression risk.
- **Pros:** Locks the multi-drone UI contract that the Day 12 integration session depends on. Catches "the second drone disappeared from the panel" before judges see it.
- **Cons:** Requires extending `pipeline` fixture to spawn N producers OR using `--multi-drone` mode on the producer. Test runtime grows ~1.5x per added drone.
- **Context:** `test_e2e_playwright.py` is post-#9 (4 inbound + 5 outbound network + 4 UI = 13 active + 1 SKIP). The `_capture_app_outbound_frames` helper from #9 is reusable. Producer launch is at `frontend/ws_bridge/tests/test_e2e_playwright.py` line ~242 (`producer_proc = subprocess.Popen([...])`).
- **Depends on:** Person 5's multi-drone scenario landing in `sim/scenarios/disaster_zone_v1.yaml`.
- **Owner:** Person 4.

### Migrate bridge tests off `httpx-ws` private API (Phase 5+)
- **What:** `frontend/ws_bridge/tests/conftest.py`'s `app_and_client`
  fixture pokes `transport.exit_stack = None` to break a circular ref at
  shutdown. This reaches into private API; `httpx-ws` 0.8.0 already
  changed `ASGIWebSocketTransport`'s internals (we pin `<0.8` in
  `pyproject.toml`'s `[project.optional-dependencies] dev` extra).
  Migrate to the public `aconnect_ws` lifecycle
  pattern when the public API supports our use case.
- **Why:** The pin will rot. Future security/perf releases of httpx-ws
  will land behind 0.8, and we'll be stuck.
- **Pros:** Removes the version pin; tests use only public API.
- **Cons:** May require restructuring how the fixture exposes the WS
  client to tests; non-trivial diff across all test_main_*.py files.
- **Context:** Surfaced during Task 5 of chore/bridge-test-harness-cleanup
  (this PR). The `transport.exit_stack = None` workaround was inherited
  from the original 5 fixture copies; it now lives in conftest.py.
- **Owner:** Person 4.

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

### ~~Map marker tap/hover interactivity~~ (closed in feat/bridge-shutdown-and-map-interactivity)
**CLOSED** — `MissionState` exposes `selectFinding`/`selectDrone`/
`clearSelection`. `MapPanel` wraps each marker in a `GestureDetector`
sized to a forgiving hit-radius (drone 18px, finding 14px); stack
order puts drone hit-boxes on top of co-located findings. Findings
and Drone Status panels render a blue highlight on the selected row.
Original entry retained below for historical context.

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

### ~~Bridge lifespan teardown ordering (Phase 5+)~~ (closed in feat/bridge-shutdown-and-map-interactivity)
**CLOSED** — `RedisSubscriber.stop()` was split into
`signal_stop()` + `close()`. `frontend/ws_bridge/main.py` lifespan
now signals stop, cancels all three tasks (including subscribe_task
per eng-review 1B), awaits all three, THEN calls
`subscriber.close()` (which calls `pubsub.aclose()`). New regression
test at `frontend/ws_bridge/tests/test_main_lifespan_teardown.py`
asserts the ordering empirically. Original entry retained below for
historical context.

- **What:** Reorder `frontend/ws_bridge/main.py` lifespan teardown so `_stopping=True` is set on the subscriber and tasks are awaited BEFORE `subscriber.stop()` calls `aclose()` on the pubsub. Today the cancel-then-stop-then-await sequence allows `subscribe_task` to be mid-`pubsub.get_message()` when `aclose()` runs.
- **Why:** Surfaced by the Phase 4 adversarial review (finding #6). Functional impact today is noisy stderr on every shutdown; could become a real CI flake if `RuntimeError: Event loop is closed` traces start failing test runs.
- **Pros:** Clean shutdown logs; resilient to future broadcaster additions.
- **Cons:** Touches the lifespan ordering that Phase 3 was carefully fixed to behave a specific way. Test surface is thin (lifespan tests already exist; need to verify they catch the change).
- **Context:** Phase 3 added the `cancel-before-await` pattern; Phase 4 extends it to three tasks (emit, subscribe, translation_broadcaster). The fix is to also move `pubsub.aclose()` AFTER all task awaits.
- **Owner:** Person 4.

### Translate `preview_text_in_operator_language` properly (Phase 5+)
- **What:** The Phase 4 stub EGS emits identical English text in both `preview_text` and `preview_text_in_operator_language`. Person 3's real Gemma 4 E4B EGS will produce a localized translation in the operator's response language (per §11 of `docs/11-prompt-templates.md`).
- **Why:** The "Reply in:" dropdown in the dashboard becomes meaningful only when the EGS actually translates. Today the dropdown is wired and validated end-to-end but the local preview rendering shows the same English string twice.
- **Pros:** Headline demo moment ("Gemma 4 speaks Spanish natively") becomes legible to the judge.
- **Cons:** Couples to Person 3's prompt engineering and language detection.
- **Context:** Schema and wire path already permit distinct strings. The Flutter `_Preview` widget already renders both lines (collapses to one if equal). Stub at `scripts/dev_command_translator.py` documents this gap.
- **Owner:** Person 3.

### ~~Bridge full-suite asyncio test pollution~~ (closed in chore/bridge-test-harness-cleanup)
**CLOSED** — fixed by `pytest.ini` setting `asyncio_mode = auto` and
`asyncio_default_fixture_loop_scope = function`, plus the conftest.py
extraction (single fakeredis fixture binds to the running loop). CI
now runs the full bridge suite in one pytest invocation. Confirmed
on Linux+Python 3.11 in CI run #25287073503. Original entry retained
below for historical context.

- **What:** `PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/` reports 20 failures on `main` AND on the Phase 4 branch, but every failing test PASSES when run in isolation (`python3 -m pytest frontend/ws_bridge/tests/test_subscriber.py` etc). The failure is event-loop / fakeredis state pollution across test files when pytest collects them in one run.
- **Why:** Surfaced during Phase 4 Task 6 review when I tried to verify a clean baseline. CI will look broken if anyone runs the full bridge suite as one job. Individual-file runs hide the issue. Phase 4's new tests use `httpx.AsyncClient + pytest_asyncio` (the test harness convention added for Tasks 7–10) which sidesteps the pollution, but the legacy Phase 2/3 tests still collide with each other.
- **Pros:** Restores trust in `pytest -q frontend/ws_bridge/tests/` as a single command.
- **Cons:** Touches multiple test files; the right fix is probably to add a `pytest.ini` `asyncio_mode = "auto"` plus per-test-file fakeredis fixtures with explicit teardown. Could be 1-2 hours of fiddling.
- **Context:** Affected files: `test_subscriber.py`, `test_redis_publisher.py`, `test_outbound_publish.py`. Python 3.9.5, pytest-8.4.2, pytest-asyncio 1.2.0. Pattern matches https://github.com/pytest-dev/pytest-asyncio/issues/660 (loop-scope mismatch between fakeredis and pytest-asyncio strict mode).
- **Owner:** Person 4.

### Repo-wide $ref convention pass (Phase 5+)
- **What:** Decide on a single `$ref` style for `shared/schemas/` — currently every schema uses relative refs (`_common.json#/$defs/...`). Either keep relative as the formal convention and document it, OR convert to absolute URIs (`https://github.com/ibrahim7860/Gemma-Guardian/shared/schemas/v1/_common.json#/$defs/...`) across every schema in one coordinated PR.
- **Why:** Surfaced by the Phase 4 Task 2 code review. Phase 4 originally tried to use absolute URIs in two new schemas (per adversarial finding #3 — concern that relative refs resolve by URI-base coincidence). Code review correctly noted that mixing styles in one directory is worse than the bug it tried to prevent. Phase 4 reverted to relative refs to match the existing convention. The forward-looking concern about $id moves still applies — it just applies uniformly to every schema, not just Phase 4's.
- **Pros:** Consistency. Easier to refactor `$id` bases later (search-and-replace works without missing schemas).
- **Cons:** Touches every schema in `shared/schemas/`. CI burden if any test depends on a specific $ref shape.
- **Context:** Reverted in commit `<phase4-revert-sha>`. The Phase 4 spec §4.3 documents the deferral rationale.
- **Owner:** Person 4 or whoever picks up shared/contracts work.

### ~~Extract bridge WS test helpers to `conftest.py`~~ (closed in chore/bridge-test-harness-cleanup)
**CLOSED** — `frontend/ws_bridge/tests/conftest.py` hosts `fake_client`
and `app_and_client`; `frontend/ws_bridge/tests/_helpers.py` hosts the
`drain_until` async helper. Five test files migrated. ~270 lines of
duplication removed. Original entry retained below for historical
context.

- **What:** `_drain_until`, `app_and_client`, and `fake_client` are duplicated across `frontend/ws_bridge/tests/test_main_operator_command_publish.py`, `test_main_operator_command_dispatch.py`, `test_main_command_translation_forward.py`, `test_main_finding_id_allowlist.py`, and (after the May 3 follow-up lands) `test_main_error_paths.py`. Hoist them into `frontend/ws_bridge/tests/conftest.py` (fixtures) plus a small helper module for the drain function.
- **Why:** Surfaced by the May 3 plan-eng-review issue 2A. Each new bridge test file pays the duplication tax. `_drain_until` has already drifted slightly between files (different `max_frames` defaults). DRY violation flagged repeatedly across reviews.
- **Pros:** Kills ~60 lines of duplication. Future bridge tests start lighter. Single source of truth for the harness convention added in Phase 4.
- **Cons:** Touches 4 existing test files. Risk of interacting with the documented full-suite asyncio pollution if `conftest.py` introduces shared fixture state across files. Test in isolation per file before committing.
- **Context:** Phase 4 standardised on `httpx.AsyncClient + pytest_asyncio + httpx-ws + fakeredis`. Best landed in the same PR as the asyncio pollution fix above so the whole bridge test surface gets one coordinated cleanup.
- **Depends on:** Should bundle with "Bridge full-suite asyncio test pollution" above.
- **Owner:** Person 4.

### Move `ValidationEventLogger.log` off the subscriber dispatch path (Phase 5+)
- **What:** `frontend/ws_bridge/redis_subscriber.py:_log_validation_failure` calls `self._validation_logger.log(...)` synchronously inside `_handle_message`. The logger does sync disk I/O (`open(..., "a")`).
- **Why:** Surfaced by the Phase 4 adversarial review (finding #7). A misbehaving EGS spamming malformed translations or findings could stall the subscriber's Redis drain on disk I/O latency, especially on slow disks or when the validation log is being rotated.
- **Pros:** Subscriber drain stays fast and predictable under any upstream noise.
- **Cons:** Adds an `asyncio.Queue` + writer task (mirrors the Phase 4 translation_queue pattern). Crash-recovery: queued events lost on bridge crash — acceptable for a debug log, document as such.
- **Context:** Logger lives in `shared/contracts/logging.py`. Either wrap each `.log()` call in `asyncio.get_running_loop().run_in_executor(None, ...)` or build a dedicated async writer. The latter is cleaner if other call sites also start hitting hot paths.
- **Owner:** Person 4 (bridge changes) + minimal coordination with shared/contracts owners.

## Phase 3 in-scope work tracked here for breadcrumbs

(none — see `docs/superpowers/specs/2026-05-02-phase3-dashboard-mvp-design.md` once it lands)
