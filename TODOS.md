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

### Translate `preview_text_in_operator_language` properly (Phase 5+)
- **What:** The Phase 4 stub EGS emits identical English text in both `preview_text` and `preview_text_in_operator_language`. Person 3's real Gemma 4 E4B EGS will produce a localized translation in the operator's response language (per §11 of `docs/11-prompt-templates.md`).
- **Why:** The "Reply in:" dropdown in the dashboard becomes meaningful only when the EGS actually translates. Today the dropdown is wired and validated end-to-end but the local preview rendering shows the same English string twice.
- **Pros:** Headline demo moment ("Gemma 4 speaks Spanish natively") becomes legible to the judge.
- **Cons:** Couples to Person 3's prompt engineering and language detection.
- **Context:** Schema and wire path already permit distinct strings. The Flutter `_Preview` widget already renders both lines (collapses to one if equal). Stub at `scripts/dev_command_translator.py` documents this gap.
- **Owner:** Person 3.

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

### Wire `agent_status` flips in drone state republish (GATE 4 / Beat 4 demo)
- **What:** Have the drone runtime flip `agent_status` to `"returning"` on `return_to_base`, `"standalone"` on lost-EGS-link, `"error"` on max-retries-exhausted. Today the republish copies whatever the sim emitted (`"active"` or `"offline"`).
- **Why:** Storyboard Beat 4's STANDALONE MODE UI in the dashboard depends on a non-`active` `agent_status` to render the badge. Without this, the resilience demo falls back to Backup Beat 4.
- **Owner:** Kaleel (with Ibrahim consuming on the dashboard side).

### Drone-agent Ollama startup healthcheck (delivered, monitor)
- **What:** Plan ships an httpx `GET /api/tags` healthcheck logging a clear warning if the model isn't pulled or the daemon is down. Track whether the warning is actually surfacing in operator runs.
- **Why:** The Day 1-7 standalone work assumed Ollama Just Works; partial pulls and daemon-not-running have already cost an integration session.
- **Owner:** Kaleel (delivered); Ibrahim verifies in demo prep.

### Replace `ActionNode._finding_counter` with `MemoryStore.next_finding_id()`
- **What:** `MemoryStore.next_finding_id()` already exists with the canonical `f_drone\d+_\d+` format. The action node maintains its own parallel counter — drift risk if either changes.
- **Why:** DRY. Pre-existing technical debt; surfaced during the Redis wiring plan but out of scope for that PR.
- **Owner:** Kaleel.
