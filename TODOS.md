# TODOS — FieldAgent

Deferred work captured during planning and reviews. Each entry includes context for whoever picks it up.

## Phase 4+ (post-Dashboard MVP)

### CLOSED — Bridge cutover from `dev_fake_producers.py` to real sim (hybrid mode)
- **Resolution:** Shipped `scripts/run_hybrid_demo.sh` orchestrator + `--emit` flag on `dev_fake_producers.py`. Real sim now owns `drones.<id>.state`; fake producer remains the source for `egs.state` and `drones.<id>.findings` until Qasim's EGS aligns `zone_polygon` to the scenario YAML and Kaleel's drone agent publishes findings to Redis.
- **Migration path:** Pass `--no-fake-egs` to `run_hybrid_demo.sh` once Qasim ships. Pass `--no-fake-findings` once Kaleel ships. Both default to OFF (fakes ON), so the flip is one CLI flag — no source edits, no risk of dangling fake processes.
- **Verification:** `scripts/check_hybrid_demo.py disaster_zone_v1 --deadline-s 20` passes against a freshly-launched hybrid stack (3-drone scenario, fake findings present). Dry-run regression coverage in `scripts/tests/test_launch_scripts.py`.
- **Owner:** Person 4 (closed by this PR).

### CLOSED — Expand Playwright coverage to multi-drone scenarios
- **Resolution:** Shipped `frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py` with a `multi_drone_pipeline` fixture (1 EGS + 3 per-drone fake producers + uvicorn bridge + Flutter web). Three load-bearing assertions: every drone in `active_drones[]`, every drone's findings in `active_findings[]` with no `finding_id` collision (cross-checked via both id-derivation and `source_drone_id`), and `operator_command` acks survive multi-drone aggregator state.
- **Coverage:** Reuses `--emit=state,findings` per drone + `--emit=egs` global from PR #20's `dev_fake_producers.py` flag. No producer-side `--multi-drone` mode needed.
- **CI:** `.github/workflows/test.yml` `bridge_e2e` job updated to invoke both Playwright test files.
- **Owner:** Person 4 (closed by this PR).

### EGS subscriber for `egs.operator_actions` — finding_approval variant
- **Status (2026-05-09, partial):** PR #38 shipped the EGS subscriber on `egs.operator_actions` and it correctly consumes the `operator_command_dispatch` action variant — replan only triggers after the operator confirms via DISPATCH, closing that half of the loop. The `finding_approval` action variant (operator approve/dismiss decisions on findings, published by the bridge) is **STILL NOT consumed** — those payloads land in Redis but the EGS does not yet reflect approved findings into the next `state_update` envelope.
- **What's left:** Wire the `finding_approval` branch in the EGS `egs.operator_actions` handler so approved findings flow back into `egs.state` and the dashboard's two-stage feedback (grey check = bridge ack, green check = EGS-confirmed) becomes truthful.
- **Why:** Without the `finding_approval` consumer, the green-check state in the dashboard remains aspirational and multi-operator scenarios will not converge.
- **Pros:** Closes the remaining half of the loop; green-check-on-confirmed becomes truthful; multi-operator scenarios work correctly.
- **Cons:** Couples to EGS state shape; may want lightweight replan-on-approve logic.
- **Context:** Schema at `shared/schemas/operator_actions.json`. Topic constant in `shared/contracts/topics.yaml` and generated `topics.dart`. Bridge stamps `bridge_received_at_iso_ms` before publish; EGS dedupes on `command_id`. The `operator_command_dispatch` handler in PR #38 is a good template for the new `finding_approval` branch.
- **Owner:** Person 3 (Qasim).

### CLOSED — Static aerial base image for map panel
- **Resolution:** Shipped Task 8 of `docs/plans/2026-05-08-thayyil-fixtures-swap.md`. Mississippi post-Katrina FEMA blue-roof aerial wired into `frontend/flutter_dashboard/lib/widgets/map_panel.dart` via `Image.asset` over a 3-layer Stack (procedural grid fallback ← `AnimatedOpacity` aerial overlay at 0.80 ← markers). Bbox locks to `scenario.base_image_extents` (LOCKED DESIGN DECISION D1); off-extents drones render as edge chevrons with tap-to-show distance/cardinal toast. Drone-id labels moved out of the painter into white-pill `Positioned` widgets for legibility against photographic backgrounds (D3); finding circles got a 7px white halo; touch targets bumped 18→24 / 14→24 (48px hit area, meets iOS 44px minimum).
- **Plumbing:** `Scenario.base_image_path` + `Scenario.base_image_extents` (Pydantic, both-or-neither validator) flow through `agents/egs_agent/scenario_state.py` onto `egs.state` (Contract 3, optional fields), the bridge passes them through, `MissionState` exposes `baseImagePath` / `baseImageExtents` getters. Asset bytes live in `sim/fixtures/base_images/` (source of truth + LICENSES.md provenance) and `frontend/flutter_dashboard/assets/base_images/` (Flutter bundle); drift between the two is locked down by `scripts/tests/test_flutter_asset_sync.py` and re-synced via `uv run python -m scripts.sync_flutter_base_images`.
- **Tests:** 11 new Flutter widget tests in `test/map_panel_base_image_test.dart` covering D1 (bbox lock, Refit hidden, off-extents chevron, tap-toast), D2 (grid synchronous, image fade, missing-asset fallback), D3 (white-pill labels, ≥44px touch targets); 9 new MissionState tests in `test/mission_state_base_image_test.dart`; 8 new scenario-loader tests in `sim/tests/test_scenario_loader.py`; 2 new EGS tests in `agents/egs_agent/tests/test_scenario_state.py`; 3 new asset-sync tests in `scripts/tests/test_flutter_asset_sync.py`.
- **Owner:** Person 4 (closed by this PR).

### CLOSED — Translate `preview_text_in_operator_language` properly (Phase 5+)
- **Resolution:** Shipped 2026-05-09. EGS pipeline fully wired with Gemma 4 E4B translation capability. `preview_text_in_operator_language` is properly populated and the translation accuracy works end to end. Dashboard correctly handles translations that take longer than 15 seconds (timeout extended to 120s).
- **Owner:** Person 3 (Qasim).

## Phase 3 in-scope work tracked here for breadcrumbs

(none — see `docs/superpowers/specs/2026-05-02-phase3-dashboard-mvp-design.md` once it lands)

## Drone-Agent Follow-ups

### Migrate drone agent zone source to `egs.state.zone_polygon` (GATE 4)
- **What:** Replace `agents/drone_agent/zone_bounds.py` scenario-derived bbox with a subscriber on `egs.state` that reads the canonical mission polygon Qasim's EGS publishes.
- **Why:** Single source of truth for the survey area. Today Kaleel and Qasim independently derive zones from the same scenario YAML; if either changes its derivation logic, they drift.
- **Pros:** Architectural consistency; matches the EGS-as-mission-owner narrative in the writeup.
- **Cons:** Couples drone agent startup to EGS being up.
- **Context:** GATE 2 plan ships scenario-derived bbox with a 50m buffer. Zone migration deferred to GATE 4 with the cross-drone awareness work.
- **Owner:** Kaleel.

### CLOSED — Wire `agent_status` flips in drone state republish (GATE 4 / Beat 4 demo)
- **Resolution (2026-05-10, Path A-full Wave 2 Lane E):** Superseded by autonomous link-state detection. The drone now self-detects standalone via the `mesh.link_status` event channel (consumed by `agents/drone_agent/redis_io.py:LinkStatusSubscriber`, fed into `agents/drone_agent/link_state_monitor.py:LinkStateMonitor` with a 10 s staleness fallback). `agents/drone_agent/runtime.py:_state_republish_loop` writes `agent_status: "standalone" | "active"` on every republish based on the monitor's verdict. No manual flips required from Kaleel; the badge auto-lights the moment a `mesh.link_status link="down"` event arrives (whether from geometric range crossing or a scripted `egs_link_drop` override).
- **Verification:** 5 integration tests in `agents/drone_agent/tests/test_runtime_link_state_integration.py` (incl. the staleness-fallback regression) + 6 unit tests in `test_link_state_monitor.py` + 4 subscriber tests. Manual Playwright MCP capture at `docs_assets/dashboard-beat5-phase3-restored.png` confirms the badge attaches and detaches correctly across the link-drop window.
- **Note:** the original TODO also asked for `"returning"` (on `return_to_base`) and `"error"` (on max-retries-exhausted) flips. Those remain unimplemented; track separately if/when Beat 4 backup mode needs them.
- **Owner:** Closed by Ibrahim 2026-05-10.

### Drone-agent Ollama startup healthcheck (delivered, monitor)
- **What:** Plan ships an httpx `GET /api/tags` healthcheck logging a clear warning if the model isn't pulled or the daemon is down. Track whether the warning is actually surfacing in operator runs.
- **Why:** The Day 1-7 standalone work assumed Ollama Just Works; partial pulls and daemon-not-running have already cost an integration session.
- **Owner:** Kaleel (delivered); Ibrahim verifies in demo prep.

### CLOSED — Replace `ActionNode._finding_counter` with `MemoryStore.next_finding_id()`
- **Resolution:** Bundled into Beat 5 Path A-full Component 5 (counter durability) PR. `ActionNode` now takes a `next_id_fn: Callable[[], str]` injected at construction; `runtime.py` and `main.py` pass `memory.next_finding_id` so production paths share a single, durable, per-drone counter source. Regression guard test in `agents/drone_agent/tests/test_action_uses_memory_for_finding_id.py` asserts `ActionNode` no longer exposes `_finding_counter`. Plan ref: `docs/plans/2026-05-10-beat5-path-a-full.md` §4 Component 5.
- **Owner:** Person 4 (closed by this PR).
