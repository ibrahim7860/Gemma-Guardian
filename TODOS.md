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
