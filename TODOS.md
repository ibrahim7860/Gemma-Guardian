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

### CLOSED — EGS subscriber for `egs.operator_actions` — finding_approval variant
- **Resolution (2026-05-11):** Shipped the `finding_approval` branch in `coordinator.process_actions()`. Three Gate 4 items closed in one PR:
  1. **finding_approval consumer:** `process_actions` now handles `kind: "finding_approval"` actions — maps `approve`→`"approved"`, `dismiss`→`"dismissed"` into `egs_state.approved_findings` (new Contract 3 field). Deduplicates on `command_id` (same pattern as `operator_command_dispatch`). Dashboard green-check is now truthful.
  2. **drone_failure scripted event replan:** `main.py` subscribes to `sim.scripted_events`; on `drone_failure`, injects synthetic offline telemetry so the existing `active→offline` replan trigger fires immediately. Gate 4 criterion: "EGS replanning successfully reassigns survey points after scripted drone failure event."
  3. **Standalone-mode EGS tolerance:** `process_telemetry` now triggers replan on `active→standalone` transition so survey points get redistributed to reachable drones. `replanning.assign_survey_points` already only considers `status=="active"` drones, so standalone drones are excluded from new assignments.
- **Schema:** `shared/schemas/egs_state.json` — added `approved_findings` (object, values: `"approved"|"dismissed"`). Pydantic mirror in `shared/contracts/models.py:EGSStateMessage`. Initialized as `{}` in `scenario_state.py:build_initial_egs_state()`.
- **Tests:** 12 new tests in `agents/egs_agent/tests/test_finding_approval.py` covering approve, dismiss, dedup, malformed payload, no-replan, mixed batch, schema validation, standalone transition replan, standalone-to-active no-replan, drone_failure replan, standalone exclusion from assignments, empty dict validation. Full regression: 720 passed (1 pre-existing drone_agent failure unrelated).
- **Frontend/bridge half (Day 11 evening, 2026-05-11, PR #47):** Closed by Ibrahim. Bridge aggregator stamps `operator_status` onto findings from the new map; dashboard promotion loop extended (dismiss arm + dropped `cur != null` precondition for the reconnect case); Contract 3 prose + `07-operator-interface.md` updated; parametrized Playwright e2e covers approve+dismiss in <3s each on a real EGS coordinator subprocess. Scope expanded with user approval to absorb two PR #45 drive-bys: TTL-bounded `_seen_approval_command_ids` (deque+set, 5-min TTL mirroring `_seen_finding_ids`) and FIFO-capped `approved_findings` (`MAX_APPROVED_FINDINGS = 1000`). 5 new EGS unit tests + 6 bridge stamp tests + 2 Flutter reconnect tests. CI all-green. Plan: `docs/superpowers/plans/2026-05-11-finding-approval-egs-consumer.md`.
- **Owner:** Person 3 (Qasim) — EGS backend; Person 4 (Ibrahim) — bridge + dashboard + docs + bounds follow-up. Closed 2026-05-11.

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

## Submission Follow-ups

### Writeup §7: collapse Fine-Tuning section after GATE 3 decision
- **What:** `docs/22-writeup-draft.md` §7 currently ships with both 7.A (gate passed — full Unsloth LoRA narrative) and 7.B (gate failed — honest-failure narrative). After Kaleel signals GATE 3 GO/NO-GO (Day 12 / 2026-05-12), delete the non-applicable variant + the conditional banner above §7.A. This is the only mandatory section-collapse left before submission.
- **Why:** Doc cannot ship with both variants. The conditional shape is a holdover from authoring the writeup before GATE 3 was decided.
- **Pros:** Mechanical edit once the decision is in — one delete + the variant header re-titled to `## 7. Fine-Tuning` (no `A`/`B`).
- **Cons:** none — pure cleanup.
- **Context:** Caught by `/review` of `25b2411`. Project-name decision ("FieldAgent" alone for Kaggle) made in same review. Surrounding submission artifacts (README, Kaggle form, writeup) all reviewed clean except this single deferred item.
- **Owner:** Ibrahim (frontend/writeup), unblocked by Kaleel's GATE 3 signal.

## Demo Capture Follow-ups

### GATE 4 wow moment Phase 5 — live eval + capture
- **What:** Implementation shipped 2026-05-12 in commit `3b86d9a` (storyboard Sub-beat 3c). Phase 5 is the human-in-the-loop close-out: (1) `uv run python ml/evaluation/eval_wow_moment_trigger.py --runs 20` on the demo box; paste pass/fail + per-run rule_ids into the plan. (2) `uv run python scripts/measure_e4b_replan_latency.py`; paste p50/p95 into the plan to decide single-take vs jump-cut capture. (3) `bash scripts/check_wow_moment.sh` immediately before the capture session — exit 0 greenlights, exit 1 aborts. (4) Capture `docs_assets/dashboard-validation-wow-{failed,passed}.png`. (5) If eval reports <12/20 triggers, ship Phase 3c debug-injection fallback (`--inject-overcount-once` flag on `agents/egs_agent/main.py`) with one-paragraph writeup §4.3 disclosure.
- **Why:** Phase 1–4 (code + tests + iron-rule contract regression) is done; Phase 5 is the demo-day verification + asset capture that the storyboard depends on. Without live numbers in the plan, we can't decide the capture cadence.
- **Pros:** Closes the storyboard's load-bearing technical-innovation moment.
- **Cons:** Burns ~30–60 min of demo-box time. Slight risk that Gemma 4 E4B doesn't naturally over-count, triggering Phase 3c.
- **Context:** Plan: `docs/plans/2026-05-12-gate4-wow-moment.md`. Backend ships per-attempt validation events on `validation_events.jsonl` AND a transient `replan_in_flight_attempt_log` on the EGS state envelope. Dashboard banner mounts under `EgsLinkSeveredBanner` at `main.dart:156` and renders red→green chips with server-provided corrective text. Phase 4 cross-cutting tests + Playwright E2E green; reference screenshot at `/tmp/gg_wow_moment_capture/wow_moment_passed.png` (59 KB).
- **Partial progress (2026-05-12 evening, Ibrahim):** ran an attempted close-out on M1 16 GB but the demo box can't carry `gemma4:e4b` at usable speed — every `assign_survey_points` call took 1–10 min, Ollama runner kept getting swapped under memory pressure. (1) Eval: aborted both a 20-run pass (48 min) and an 8-run pass (47 min) before either could print JSON; observational evidence at the time was ≥ 5 terminal `failed after retries` events out of 8 attempted runs (= 62.5 % rule-trigger lower bound), but **no clean `per_run.rule_ids` JSON was collected.** (2) Latency: only 2 single-attempt measurements landed (421 s, 555 s) before aborting — enough to decide jump-cut capture, but not a real p50/p95. (3) `scripts/check_wow_moment.sh --timeout 240` was exercised and FAILED on this run (E4B produced one invalid-but-non-overcount assignment) — the stochastic-trigger risk realized. (4) Both reference PNGs were captured deterministically via the synth-WS Playwright path and are on disk: `docs_assets/dashboard-validation-wow-failed.png` (56 KB, 1665×720) and `docs_assets/dashboard-validation-wow-passed.png` (59 KB, 1665×737). Detail log in `docs/plans/2026-05-12-gate4-wow-moment.md` "Phase 5 close-out execution" section.
- **Remaining for owner:** rerun steps (1) and (2) on a workstation with a free CUDA GPU (≥ 12 GB VRAM, same path as the GATE 3 fine-tune box) so the plan gets the clean JSON report and real p50/p95 numbers. Then rerun step (3) on the demo box immediately before the capture session — if it fails again, ship the Phase 3c `--inject-overcount-once` flag with the writeup §4.3 disclosure. PNGs already on disk; no recapture needed unless the dashboard UI changes.
- **Owner:** Qasim (reassigned 2026-05-12 — needs CUDA box Ibrahim doesn't have).

### Drone3-specific `report_finding` reliability check
- **What:** Day-11 pre-flight: run the full `resilience_v1` stack three times in a row and assert that `validation_events.jsonl` contains at least one `report_finding` for drone3 within the standalone window t∈[120,180] on every run. Acceptance: 3/3 hits. Owner runs this before scheduling the Day 12 capture session.
- **Why:** STATUS.md verifies live Gemma `report_finding` on drone1 (FEMA Katrina image, 5× runs 2026-05-06). drone3 has a different waypoint track in `sim/scenarios/resilience_v1.yaml` and a different frame mapping. If drone3's path doesn't pass over a frame that triggers a victim/damage finding, A2 fails every Beat 5 take. The capture plan (`docs/plans/2026-05-12-beat5-video-capture.md` prereq #10) calls this out and provides the mock-Ollama fallback, but the proactive Day-11 check is what avoids burning a capture afternoon on a broken assumption.
- **Pros:** Surfaces the failure mode 24 hours before capture, leaving time to re-tune drone3's frame mapping or accept the mock fallback. Cheap (3 runs × 4 min = 12 min wall clock).
- **Cons:** Adds a 30 min slot to Day 11. None of the team's other Day 11 work blocks on it.
- **Context:** Capture plan prereq #10 in `docs/plans/2026-05-12-beat5-video-capture.md` is the canonical reference for the procedure. If 2/3 hits → re-tune `resilience_v1.yaml` frame mapping. If ≤1/3 → fall back to `scripts/ollama_mock_server.py` (and note this in the writeup as "deterministic take for repeatability"). Validation log lives at `$GG_LOG_DIR/validation_events.jsonl` per `agents/drone_agent/runtime.py`.
- **Owner:** Ibrahim (Person 4) — re-reassigned 2026-05-12 back to Ibrahim after a bounded experiment disproved the hardware-floor assumption. M1 16GB *can* host the 3-drone live-Gemma stack with the right Ollama tuning (`NUM_PARALLEL=1`, `KV_CACHE_TYPE=q8_0`, `FLASH_ATTENTION=1`, `KEEP_ALIVE=30m`, pre-warm) plus an agent httpx timeout bump (120→240s via new `DRONE_AGENT_OLLAMA_TIMEOUT_S` env override). Run 1 of the 3× check produced 11 validation events with zero timeouts across all drones (drone3 included). Plan + full execution log: `docs/plans/2026-05-12-drone3-reliability-capture.md`. Launch script: `scripts/run_drone3_reliability.sh`.
- **Status:** 0/3 PASS on the literal "≥1 `report_finding` from drone3 in t∈[120,180]" criterion. The failure mode is **perception-quality, not hardware**: `placeholder_victim_01.jpg` (and `placeholder_debris_01.jpg`) are aerial shots of destroyed structures, not visibly identifiable victims, and the agent system prompt explicitly biases toward `continue_mission` when uncertain. Gemma 4 E2B (base, no LoRA) reads the frames and reasonably chooses `continue_mission`. The hardware path is proven; the perception path is now the floor.
- **Recommendation:** treat this TODO as **investigated, not unblocked**. Three forward paths: (a) soften acceptance to ≥1/3 (Run 1 already qualifies under a "drone3 completes a perception cycle in the standalone window" reading); (b) gate on GATE 3 LoRA outcome (today); (c) use `scripts/ollama_mock_server.py` for Beat 5 capture as already planned in `docs/plans/2026-05-12-beat5-video-capture.md` prereq #10. Closing depends on standup discussion.

### CLOSED — Convert `test_e2e_phase3.py::test_e2e_reconnect_after_bridge_restart` from stub to live test
- **Resolution (2026-05-11, commit `6b4558e`):** Closed via the unit-level test `test_aggregator_finding_approval_stamp.py::test_snapshot_uses_seed_envelope_state_before_first_egs_update` rather than converting the e2e stub. The unit test pins the actual regression class this TODO was filed against — the aggregator's `snapshot()` correctly handles the post-restart window where its `_egs` bucket holds the seed envelope state and findings come in before the first `egs.state` publish arrives. ~10 lines, runs in 0.1s in the existing `ws_bridge` CI job, zero subprocess flake surface.
- **What the unit test does NOT catch (and why we accepted that):** the actual subprocess kill+restart lifecycle (testing OS process behavior, not our code), Flutter's WS reconnect handler (separate concern, exercised by every other e2e), and timing races during port reuse. None of these are this TODO's bug class — they are infrastructure concerns covered implicitly by the bridge starting up cleanly in every other e2e fixture.
- **Trade-off:** ~30s of `bridge_e2e` CI flake surface and ~30 min of fixture work avoided. The cost-benefit for landing the full integration test 7 days before submission was negative; the unit test catches the regression we cared about.
- **Stub left in place:** `test_e2e_phase3.py:274` still contains the original `pytest.skip(...)`. Re-opening it is post-submission if anyone wants the integration-flavor coverage.
- **Owner:** Person 4 (Ibrahim), closed 2026-05-11.

## Mesh Simulator Follow-ups

### CLOSED — Derive EGS lat/lon from active scenario YAML
- **Resolution (2026-05-11):** Shipped per `docs/plans/2026-05-11-mesh-sim-scenario-derived-egs.md`. `agents/mesh_simulator/main.py` accepts `--scenario <name>` and reads `origin.lat/.lon` via the new shared `sim/scenario.py:resolve_scenario_path()` helper (also adopted by `sim/list_drones.py` — DRY). Precedence: explicit `--egs-lat/--egs-lon` wins with a stderr `WARN`; else scenario origin; else **exit 2** with a clear stderr `ERROR` so the silent-zero-findings bug class (PR #41/#42/#43) cannot recur.
- **Callers migrated to `--scenario`:** `scripts/launch_swarm.sh`, `scripts/run_beat5_capture.sh`, `frontend/ws_bridge/tests/test_e2e_playwright_dom_render.py`, `test_e2e_playwright_real_drone_findings.py`. The 4 synthetic-position e2e tests (`test_e2e_phase3`, `test_e2e_playwright`, `test_e2e_playwright_multi_drone`, `test_e2e_playwright_egs_findings`) keep explicit flags because their positions don't match any real scenario.
- **Tests:** 5 new CLI tests in `agents/mesh_simulator/tests/test_cli_scenario.py` (scenario-by-id, scenario-by-path, unknown-id error, explicit-override WARN, no-flags ERROR + exit 2). Regression guard rewritten as `test_shell_launcher_passes_egs_config_to_mesh_simulator` — parametrized over `scripts/*.sh` that launch the mesh sim, asserts EITHER `--scenario` OR both `--egs-lat/--egs-lon` on every invocation. Picks up future launchers automatically. Two Playwright e2e tests migrated and green (DOM-render + real-drone-findings).
- **Owner:** Closed by Ibrahim 2026-05-11.

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

### CLOSED — Drone-agent Ollama startup healthcheck (delivered, monitor)
- **Resolution (2026-05-11):** Verified live. Daemon-unreachable branch surfaces `[drone_agent] WARNING: ollama healthcheck failed at http://localhost:11434: ` within ~3 s in both the direct boot path (`python -m agents.drone_agent`) and the operator launch path (replicates `scripts/launch_swarm.sh:165` line — `python -m agents.drone_agent ... | tee $LOG_DIR/<drone>.log`). The WARNING reaches the per-drone log file; `flush=True` survives the tee pipeline. Empty exception suffix observed (`httpx.ConnectTimeout` serializes to `""`); WARNING + endpoint remain operator-readable, message-quality polish not pursued. Model-absent and happy-path branches not live-tested on this host (Ollama daemon unresponsive); both remain covered by unit tests at `agents/drone_agent/tests/test_main_ollama_healthcheck.py` (3/3 passing). Call-order invariant (healthcheck awaited before Redis construction) locked by new regression guard `agents/drone_agent/tests/test_main_run_order.py`.
- **Evidence:** `/tmp/healthcheck_unreachable.log` (direct boot), `/tmp/healthcheck_launch_test/drone1.log` (operator path replica). Regenerate via plan `docs/superpowers/plans/2026-05-11-ollama-healthcheck-verification.md`.
- **Owner:** Closed by Ibrahim 2026-05-11.

### CLOSED — Replace `ActionNode._finding_counter` with `MemoryStore.next_finding_id()`
- **Resolution:** Bundled into Beat 5 Path A-full Component 5 (counter durability) PR. `ActionNode` now takes a `next_id_fn: Callable[[], str]` injected at construction; `runtime.py` and `main.py` pass `memory.next_finding_id` so production paths share a single, durable, per-drone counter source. Regression guard test in `agents/drone_agent/tests/test_action_uses_memory_for_finding_id.py` asserts `ActionNode` no longer exposes `_finding_counter`. Plan ref: `docs/plans/2026-05-10-beat5-path-a-full.md` §4 Component 5.
- **Owner:** Person 4 (closed by this PR).
