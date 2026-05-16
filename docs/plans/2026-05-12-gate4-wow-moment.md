# 2026-05-12 — GATE 4 "Wow Moment" implementation plan (rev 2)

> Owner: Ibrahim (steal from Qasim — pure-Flutter + scenario-tuning + EGS-side logging lanes).
> Storyboard target: `docs/21-demo-storyboard.md` Sub-beat 3c (0:55 – 1:05).
> Goal-date: usable by Day-14 Beat-5 capture session (2026-05-14).
> Rev 2 (2026-05-12 PM): incorporates `/plan-eng-review` findings 1A, 2B, 3C, 4A, 5A, 6B, 7A
> and the mandatory contract-version regression test. Original 3.5h estimate revised to ~5-6h.

## What the wow moment is

The Beat 3c camera moment, verbatim from the storyboard:

> First attempt: assignment includes 27 points (only 25 exist). VALIDATION FAILED in red.
> Corrective prompt visible: "You are hallucinating, creating more survey points than required..."
> Second attempt: 25 points, balanced. VALIDATION PASSED in green.

That is the technical-innovation moment for the whole video. It is the
clearest, single-frame proof that the Algorithm-1 validation loop from the
reference paper is doing real work, on a real Gemma 4 call, with no cloud.

## Audit findings that changed the plan

The original rev 1 assumed the backend was wired end-to-end. `/plan-eng-review`
proved it is not. Three load-bearing issues:

1. **EGS-side validation logging is missing.** `grep -rn "ValidationEventLogger" agents/egs_agent/*.py`
   returns one docstring reference. The drone side logs (`drone_agent/main.py:47`),
   the EGS side does not. `agents/egs_agent/replanning.py:91-97` retries silently.
   So `validation_events.jsonl` contains zero `ASSIGNMENT_TOTAL_MISMATCH` events,
   and `recent_validation_events` is empty for assignment events. Fix: **Issue 1A**.
2. **`recent_validation_events` drops `in_progress`.** `agents/egs_agent/validation_log_tail.py:25`
   explicitly skips non-terminal events because Contract 3's enum is
   `success_first_try | corrected_after_retry | failed_after_retries`. Even with
   Issue 1 fixed, the dashboard can never show a per-attempt FAIL chip via this
   stream. Fix: **Issue 2B** — new transient field, do not pollute the
   audit tail.
3. **Layout has no 5th slot.** `main.dart:201-225` is a hard-coded 2×2 grid.
   Fix: **Issue 3C** — banner-style render, mirroring `EgsLinkSeveredBanner`
   at `main.dart:162`.

Plus three smaller plan defects: wrong outcome enum (5A), missing eval gate
(7A), and unaddressed timing budget for a 10-second clip (4A).

## Unified design

```
ASCII flow — what the operator sees on screen
=============================================

  EGS replan starts (egs_state.replan_in_flight=true)
        │
        ▼
  ┌─────────────────────────────────────────────────────┐
  │ ValidationWowBanner  (mounted under EgsLinkSeveredBanner) │
  │                                                     │
  │  Attempt 1  [RED]   ASSIGNMENT_TOTAL_MISMATCH       │
  │           "Your assignments cover 27 points but     │
  │            25 are available. Reassign so every      │
  │            point is covered exactly once."          │
  │                                                     │
  │  Attempt 2  [GREEN] PASSED                          │
  │                                                     │
  └─────────────────────────────────────────────────────┘
        ▲
        │
   ┌────┴─────────┐
   │ data sources │
   └────┬─────────┘
        │
        ├─ egs_state.replan_in_flight_attempt_log  (NEW transient field)
        │     - List[ReplanAttempt] with corrective_text + counts
        │     - cleared 3s after replan_in_flight flips false
        │
        └─ EGSStateMessage envelope (Contract 3) — version bumped
```

Data path:

```
agents/egs_agent/replanning.py
  ├─ on each retry:
  │   ├─ ValidationEventLogger.log(..., outcome="in_progress")    ← Issue 1A
  │   └─ coordinator.append_attempt(ReplanAttempt(...))            ← Issue 2B
  └─ on success/failure:
      ├─ ValidationEventLogger.log(..., outcome="corrected_after_retry" or "failed_after_retries")
      └─ coordinator: schedule clear of attempt_log after 3s

agents/egs_agent/coordinator.py
  └─ egs_state["replan_in_flight_attempt_log"] = attempts        ← exposed in egs.state envelope

frontend/ws_bridge/aggregator.py — deep-copy pass-through (no change)

frontend/flutter_dashboard/lib/state/mission_state.dart
  └─ parse replan_in_flight_attempt_log → List<ReplanAttempt>

frontend/flutter_dashboard/lib/widgets/validation_wow_banner.dart (NEW)
  └─ render attempts: red chip for invalid, green for valid;
     corrective_text rendered verbatim from server payload (no Flutter-side string map)

frontend/flutter_dashboard/lib/main.dart
  └─ mount banner under EgsLinkSeveredBanner, hide when attempt_log empty
```

## Out of scope

- No changes to `_RecentValidationEvent` or the historical `recent_validation_events`
  tail. The wow-moment data is transient by design; Contract 11 audit logging
  stays a separate concern.
- No 2×3 grid relayout. Banner stays.
- No real-time per-attempt Redis channel. The existing `egs.state` cadence
  (1Hz) is sufficient for the camera.
- No validation event history view / audit page.
- No multilingual corrective prompts. English only on camera.
- No persisting wow_moment_v1.yaml as a regression scenario.

## Outcome → chip color (corrected from rev 1)

Source of truth: `shared/contracts/models.py:259` —
`FindingsOutcome = Literal["success_first_try", "corrected_after_retry", "failed_after_retries"]`.

For the **new** `ReplanAttempt.outcome` field:

| Outcome value             | Chip color | When                                    |
|---------------------------|-----------|------------------------------------------|
| `in_progress` (per-attempt fail) | **red**   | attempt finished, valid=False         |
| `in_progress` (per-attempt pass) | **amber** | attempt finished, valid=True, not last|
| `success_first_try`       | **green** | replan succeeded on attempt 1           |
| `corrected_after_retry`   | **green** | replan succeeded after corrections       |
| `failed_after_retries`    | **red**   | fell back to deterministic round-robin   |

The existing rev-1 "starts with `failure*` / `success*`" matcher was wrong;
discarded.

## Phases

### Phase 1 — Backend wiring (90 min)  ← was "audit"

Issues 1A + 2B. Pre-requisite for everything else.

**Implementation:**
- [ ] `agents/egs_agent/replanning.py`: inject a `ValidationEventLogger` and
      an attempt-log callback. After each branch in the retry loop, call
      `logger.log(agent_id="egs", layer="egs", function_or_command="assign_survey_points", attempt=N, valid=..., rule_id=..., outcome="in_progress", raw_call=canonical)`.
      On loop exit (success or fallback), log with the terminal outcome.
- [ ] `agents/egs_agent/coordinator.py`: hold a `List[ReplanAttempt]` in
      `EGSCoordinator`, expose via the egs_state snapshot. Clear via
      `asyncio.call_later(3.0, ...)` after `_replan_in_flight` flips false.
- [ ] `shared/contracts/models.py`: add `ReplanAttempt` Pydantic model +
      `replan_in_flight_attempt_log: List[ReplanAttempt] = Field(default_factory=list)`
      on `EGSStateMessage`. Fields:
      `timestamp, attempt_n, valid, rule_id?, corrective_text?, details: Dict[str, Any]`.
- [ ] `shared/schemas/egs_state.schema.json`: mirror.
- [ ] `shared/contracts/__init__.py`: bump `VERSION`.
- [ ] Regenerate `frontend/flutter_dashboard/lib/generated/contract_version.dart`.

**Tests (ship with the code, not after):**

1. `shared/tests/test_replan_attempt_model.py` (NEW) — Pydantic model unit:
    - [ ] accepts valid minimal shape (timestamp, attempt_n, valid)
    - [ ] accepts full shape with rule_id + corrective_text + details
    - [ ] rejects `attempt_n=0` (must be ≥1)
    - [ ] rejects malformed timestamp (existing pattern guard)
    - [ ] rejects extra fields (`_StrictModel` parent enforces)
2. `shared/tests/test_egs_state_schema_with_attempt_log.py` (NEW) — Contract 3 schema:
    - [ ] validates payload with empty `replan_in_flight_attempt_log`
    - [ ] validates payload with 3-attempt populated list
    - [ ] rejects payload where `replan_in_flight_attempt_log` is `None` (must be list)
    - [ ] backward-compatibility: validates an old envelope missing the field
      (default_factory should kick in)
3. `agents/egs_agent/tests/test_replanning_validation_logging.py` (NEW) — main behavior:
    - [ ] **3-attempt run, success on attempt 3:** asserts JSONL contains
      exactly 3 `outcome=in_progress` lines plus 1 `outcome=corrected_after_retry`,
      all with `agent_id="egs"`, `layer="egs"`, `function_or_command="assign_survey_points"`.
    - [ ] **1-attempt run, success first try:** asserts 1 line with
      `outcome=success_first_try`, `attempt=1`, `valid=True`.
    - [ ] **max retries exceeded, fallback:** asserts terminal line is
      `outcome=failed_after_retries`, and the deterministic round-robin
      fallback still returns a valid assignment.
    - [ ] **`raw_call` field populated** on every in_progress line so audit
      logs can reconstruct what the model actually emitted.
    - [ ] **corrective_text comes from `RULE_REGISTRY[rule_id].corrective_template`** —
      asserts the literal string `"Your assignments cover 27 points but 25
      are available."` lands on `ReplanAttempt.corrective_text` (using a
      mock LLM that emits 27 points for a 25-point input).
4. `agents/egs_agent/tests/test_coordinator_attempt_log_lifecycle.py` (NEW):
    - [ ] **populate-on-replan:** `EGSCoordinator` exposes `replan_in_flight_attempt_log`
      mid-replan, length matches attempts so far.
    - [ ] **clear-after-3s:** after `_replan_in_flight` flips false,
      monkeypatch `asyncio.call_later` (or use `time.sleep` with a shortened
      clear delay) — assert log clears.
    - [ ] **two replans back-to-back:** second replan's attempt_log does
      NOT contain entries from the first. Regression guard against the
      "stuck banner" failure mode in the Risk Register.
    - [ ] **clear-during-replan is safe:** if a new replan starts before
      the 3s clear fires, the pending clear is cancelled.
5. `frontend/ws_bridge/tests/test_aggregator_replan_attempt_log_passthrough.py` (NEW):
    - [ ] Inject an egs.state payload with 3-attempt log → assert
      `aggregator.snapshot()` preserves the list verbatim (deep-copy contract).
    - [ ] Inject empty log → assert preserved as empty list, not dropped.

**Acceptance:** all 5 test files green, plus `cat $GG_LOG_DIR/validation_events.jsonl`
after a forced ASSIGNMENT_TOTAL_MISMATCH shows ≥2 lines with `agent_id="egs"`.

### Phase 2 — Flutter banner (90 min)

Issue 3C + 6B. Mirror `EgsLinkSeveredBanner` (main.dart:162).

**Implementation:**
- [ ] `frontend/flutter_dashboard/lib/state/mission_state.dart`:
      add `List<ReplanAttempt> replanInFlightAttemptLog` field, parse from
      `egs.state.replan_in_flight_attempt_log`.
- [ ] `frontend/flutter_dashboard/lib/widgets/validation_wow_banner.dart` (NEW):
    - Stateless widget consuming `MissionState`.
    - Hidden when `replanInFlightAttemptLog` is empty.
    - When populated: full-width banner under `EgsLinkSeveredBanner`,
      rendering a row per attempt. Layout:
      `[chip N] [outcome chip — red/amber/green] [rule_id text] [corrective_text]`.
    - Use the **server-provided** `corrective_text`. No Flutter-side
      RuleID→string map (per Issue 6B, single source of truth).
    - Animated entry (fade+slide, 250ms) on each new attempt.
    - Stable Semantics: `'validation-wow-banner'`, `'validation-attempt-${n}'`,
      `'validation-attempt-${n}-outcome'`, `'validation-attempt-${n}-text'`.
- [ ] `frontend/flutter_dashboard/lib/main.dart:152-157`:
      add `ValidationWowBanner` to the Column children after
      `EgsLinkSeveredBanner`.

**Tests (ship with the widget):**

1. `frontend/flutter_dashboard/test/mission_state_replan_attempt_parse_test.dart` (NEW):
    - [ ] Parses 3-attempt list from a hand-crafted egs.state JSON.
    - [ ] Empty list defaults to empty (no nulls).
    - [ ] **Missing field handled gracefully** (legacy / pre-version-bump envelope).
    - [ ] Malformed entry (missing required `attempt_n`) → entry dropped,
      remaining entries preserved, no whole-list crash.
    - [ ] `notifyListeners()` fires when the field changes.
2. `frontend/flutter_dashboard/test/validation_wow_banner_test.dart` (NEW):
    - [ ] **Hidden state:** empty `replanInFlightAttemptLog` → `SizedBox.shrink()`,
      banner not in widget tree.
    - [ ] **1 invalid attempt:** red chip rendered with corrective_text
      verbatim. Asserts the Text widget contains the literal `"Your
      assignments cover 27 points but 25 are available"` substring.
    - [ ] **Invalid + valid sequence:** two rows, attempt 1 red, attempt 2
      green; both visible in the same frame.
    - [ ] **`failed_after_retries` terminal:** all attempts red, no green chip.
    - [ ] **`success_first_try`:** one row, green chip, no corrective_text shown.
    - [ ] **Semantics identifiers present:** `validation-wow-banner`,
      `validation-attempt-1`, `validation-attempt-1-outcome`,
      `validation-attempt-1-text` all findable via `find.bySemanticsLabel`
      or `find.byTooltip` (whichever pattern the existing
      `EgsLinkSeveredBanner` test uses for consistency).
    - [ ] **Animated entry:** uses `pumpAndSettle(Duration(milliseconds: 300))`
      to confirm fade-in completes; new attempt added mid-frame triggers
      a fresh fade.
    - [ ] **No rule_id, has corrective_text:** renders corrective text without
      a rule chip (defensive against partial server data).
3. `frontend/flutter_dashboard/test/validation_wow_banner_layout_regression_test.dart` (NEW):
    - [ ] Mount `ValidationWowBanner` alongside `EgsLinkSeveredBanner` and
      `_FourPanelGrid`. Assert no layout overflow at 1280×720 (capture
      resolution) and at 1920×1080 (judge-screen resolution).
    - [ ] Regression guard for the three existing reference screenshots:
      assert `_FourPanelGrid` height is unchanged when the banner is hidden.

**Acceptance:** all 3 widget test files green; manual eyeball pass against
a synth-WS fixture confirms both chips readable at 1080p from 3ft.

### Phase 3 — Trigger scenario + timing measurement (60 min)

Issue 4A + Issue 7A. Measure-then-decide.

**Phase 3a — Timing measurement (30 min).**
- [ ] Cold-load `gemma4:e4b` via `ollama run gemma4:e4b ""`. Confirm warm.
- [ ] Force 10 consecutive `assign_survey_points` calls via a small driver
      script (`scripts/measure_e4b_replan_latency.py`, NEW). Log p50 + p95
      of (a) single-attempt latency, (b) full retry-loop latency through
      one corrective re-prompt.
- [ ] Append measurements to this plan as a table.
- [ ] Decide capture strategy:
    - If p95 of 2-attempt run < 8s → single-take capture.
    - Else → jump-cut "FAILED... [cut] ...PASSED" or fall to Phase 3b
      replay mode.

**Phase 3b — Reliable trigger (30 min).** Run BOTH in parallel:
- [ ] **Natural trigger:** `sim/scenarios/wow_moment_v1.yaml` (NEW) with
      25 awkwardly-clustered survey points across 3 drones. Reuse waypoint
      structure from `disaster_zone_v1.yaml`.
- [ ] **Eval harness:** `ml/evaluation/eval_wow_moment_trigger.py` (NEW)
      runs `assign_survey_points` 20× against the wow scenario, counts
      `rule_id == "ASSIGNMENT_TOTAL_MISMATCH"` events. **Acceptance gate:
      ≥12/20 triggers (60%).** Below that, ship Phase 3c instead.

**Phase 3 tests (ship with the scenario and tooling):**

1. `sim/tests/test_wow_moment_scenario_loads.py` (NEW):
    - [ ] `sim/scenario.py` loads `wow_moment_v1.yaml` without raising.
    - [ ] **Exactly 25 survey points** across 3 drones (the load-bearing
      number for the storyboard).
    - [ ] All point ids unique.
    - [ ] Geometry validator passes (`area_m`, `origin`, base_image bounds).
2. `ml/evaluation/tests/test_eval_wow_moment_trigger_harness.py` (NEW):
    - [ ] Harness counts ASSIGNMENT_TOTAL_MISMATCH correctly given a
      mocked LLM that returns 27 points on N runs and 25 on M runs.
    - [ ] **Acceptance-gate logic:** harness exits 0 at ≥12/20, exits 1 below.
      CI catches a Phase-3c-required signal.
    - [ ] Output JSON contains per-run rule_ids so debug post-mortem is
      possible.
3. `scripts/tests/test_measure_e4b_replan_latency.py` (NEW) — the
   measurement script must itself be testable so a future capture-day
   re-run doesn't quietly regress:
    - [ ] Driver script with a stubbed `httpx` client returns deterministic
      latencies; p50/p95 calculations match expected values.
    - [ ] Script writes a markdown table snippet that can be appended to
      this plan; assert the snippet shape.
- [ ] **Phase 3c — Debug-injection fallback (only if eval fails):**
      add `--inject-overcount-once` CLI flag on `agents/egs_agent/main.py`.
      First `assign_survey_points` call mutates the raw model response to
      add 2 phantom point ids before validation. Document explicitly in
      writeup §4.3.
    - [ ] **3c test (only if shipped):**
      `agents/egs_agent/tests/test_inject_overcount_flag.py` (NEW):
        - flag off → no mutation; flag on → first call mutated, second call
          not; mutation adds exactly 2 phantom ids; phantom ids are
          deterministic so the test is stable.

**Acceptance:** all 3 (or 4, if 3c ships) test files green; eval-gate ≥12/20
or 3c shipped with disclosure.

### Phase 4 — Cross-cutting tests (60 min)

Phases 1–3 each ship their own unit/widget/scenario tests. Phase 4 is
*only* the cross-cutting tests that span layers, plus the mandatory
contract-version regression.

1. **Mandatory contract-version regression (Issue 8 — non-optional):**
      `shared/tests/test_contract_version_bump.py` (NEW or extend):
    - [ ] Asserts a deterministic hash of `EGSStateMessage.model_json_schema()`
      matches the current `VERSION` constant. Hash drift without VERSION
      bump → test fails. **CI blocker.**
    - [ ] Same check for `shared/schemas/egs_state.schema.json` so the
      JSON Schema and Pydantic model can't drift apart.
    - [ ] Snapshot-style: write expected hash into a checked-in fixture
      file so the next contract author has to actively re-bake it.
2. **Real-Redis EGS coordinator → bridge integration test:**
      `frontend/ws_bridge/tests/test_e2e_egs_replan_attempt_log_real_redis.py` (NEW),
      pattern matches `test_e2e_link_drop_replay.py`:
    - [ ] Spin a real `redis-server` via the existing test fixture.
    - [ ] Run `EGSCoordinator` against a mock LLM that returns 27 points
      then 25 points.
    - [ ] Subscribe to the bridge's WebSocket; assert envelopes arrive in
      sequence: empty log → [attempt 1 invalid] → [attempt 1 invalid,
      attempt 2 valid] → cleared (after 3s).
    - [ ] Asserts the FULL data path Phase 1 + Phase 2 unit tests didn't
      cover end-to-end.
3. **E2E synth-WS Playwright:**
      `frontend/ws_bridge/tests/test_e2e_playwright_validation_wow.py` (NEW),
      pattern matches `test_e2e_playwright_standalone_mode.py`:
    - [ ] Inject three envelopes via the synth-WS server —
      empty → [attempt 1 invalid + corrective_text] →
      [attempt 1 invalid, attempt 2 valid].
    - [ ] Page snapshot at each step; assert `validation-wow-banner`,
      `validation-attempt-1-outcome` (red), `validation-attempt-1-text`
      (contains "27 points but 25"), `validation-attempt-2-outcome` (green)
      all locatable via Playwright `getByLabel`/`getByRole`.
    - [ ] Final envelope after 3s clears the banner; assert it leaves the DOM.
    - [ ] **Visual-regression hook:** capture a screenshot at the
      mid-state (red+green visible together) so the capture day can diff
      against `docs_assets/dashboard-validation-wow-passed.png`.
4. **Real-stack smoke (no Playwright):**
      `scripts/check_wow_moment.sh` (NEW), mirrors `scripts/check_beat5.py`:
    - [ ] Launches the full stack against `wow_moment_v1` scenario.
    - [ ] Tails `validation_events.jsonl` for ≥1 `agent_id="egs"`
      `rule_id="ASSIGNMENT_TOTAL_MISMATCH"` line within 60s.
    - [ ] Snapshots the bridge's WebSocket; asserts at least one envelope
      carries a non-empty `replan_in_flight_attempt_log`.
    - [ ] Exits 0 = wow moment camera-ready; exits 1 = abort capture.

**Acceptance:** 4 test files / scripts green. The contract-version test in
particular is iron-rule mandatory; nothing ships if it's red.

### Phase 5 — Capture + storyboard update (30 min)

**Implementation:**
- [ ] Append "Beat 3c wow-moment capture path" to
      `docs/runbooks/mcp-dom-verification.md`, mirror Beat 5 section structure.
- [ ] Capture `docs_assets/dashboard-validation-wow-failed.png` (red state)
      and `docs_assets/dashboard-validation-wow-passed.png` (green state).
- [ ] Flip Sub-beat-3c row in `docs/21-demo-storyboard.md` Pre-Flight
      Checklist from "Qasim / Not yet shipped" to
      "Ibrahim / Dashboard banner ready; trigger ≥12/20 verified Day-N".
- [ ] Confirm `docs/22-writeup-draft.md` §4.3 still aligns. If Phase 3c
      debug injection shipped, append one paragraph of honest disclosure.

**Verification checks (gate the capture session):**

1. **Pre-capture gate via `scripts/check_wow_moment.sh`** (from Phase 4):
    - [ ] Runs green → capture is greenlit.
    - [ ] Runs red → abort, root-cause via Phase 1/2 unit tests, no
      capture session burns wall-clock.
2. **Asset-presence regression:**
      `docs_assets/tests/test_wow_moment_assets_present.py` (NEW or extend
      existing `docs_assets/tests/test_required_assets_present.py` if any):
    - [ ] `dashboard-validation-wow-failed.png` exists and is ≥100 KB
      (defensive against zero-byte writes).
    - [ ] `dashboard-validation-wow-passed.png` exists and is ≥100 KB.
    - [ ] Reference image dimensions match the capture resolution
      documented in the runbook.
3. **Storyboard row consistency:**
    - [ ] Lint check (existing `scripts/check_storyboard.py` if present,
      otherwise inline assertion in CI) that the Sub-beat-3c row
      mentions both an owner and a verification reference.
4. **Two-machine backup verification** (parallel to Beat 5 pattern):
    - [ ] Re-run Phase 4's `test_e2e_playwright_validation_wow.py` on
      Hazim's box if available. If only one machine: log this gap.
    - [ ] Save the Playwright trace bundle next to the captured assets
      so a hostile reviewer can replay the DOM rendering claim.

**Acceptance:** all verification checks green, both reference assets on
disk, storyboard checklist flipped.

## Parallelization

| Lane | Steps                                    | Modules touched                                  |
|------|------------------------------------------|--------------------------------------------------|
| A    | Phase 1 (Issues 1A, 2B)                  | agents/egs_agent/, shared/contracts/             |
| B    | Phase 3a timing measure                  | scripts/, sim/scenarios/                         |
| C    | Phase 2 (Issue 3C)                       | frontend/flutter_dashboard/  (depends on Lane A) |
| D    | Phase 3b eval (Issue 7A)                 | ml/evaluation/, sim/scenarios/ (depends on Lane A)|

Execution: launch A + B in parallel. When A merges, start C + D in parallel.
Then Phase 4 tests (any lane), then Phase 5 capture (after all merge).

**Conflict flag:** Lane A and Lane D both touch `agents/egs_agent/`. Coordinate
via a single shared branch or sequence D after A.

## Hardware

Same as the rest of FieldAgent on Apple Silicon. M1 16 GB sufficient with
the Phase G tuning already in `shared/config.yaml`:
`OLLAMA_NUM_PARALLEL=1`, kv-quant on, flash attention on, `KEEP_ALIVE=30m`.
No new dependencies. `ollama list` must show `gemma4:e4b` cached locally.

## Revised time estimate

- Phase 1: 90 min impl + 60 min tests = **150 min**  (was 15)
- Phase 2: 90 min impl + 60 min tests = **150 min**  (was 90)
- Phase 3: 60 min impl + 30 min tests = **90 min**   (was 30)
- Phase 4: 60 min  (cross-cutting tests + smoke runner)
- Phase 5: 30 min impl + 15 min verification = **45 min**  (was 30)
- **Total: ~8 hours** (was 3.5; CC-assisted compression of test-writing
  means realistic walltime is closer to 5–6 hours)

Splittable across two sittings: Lane A+B today (~3h including tests),
Lane C+D + Phase 4 cross-cutting tests tomorrow morning (~3h), Phase 5
capture in tomorrow afternoon's Beat-5 window.

## Test inventory (12 new files + 2 extensions)

Visibility check — what gets written:

| Phase | File                                                                   | Type        | Required? |
|-------|------------------------------------------------------------------------|-------------|-----------|
| 1     | `shared/tests/test_replan_attempt_model.py`                            | unit        | yes       |
| 1     | `shared/tests/test_egs_state_schema_with_attempt_log.py`               | schema      | yes       |
| 1     | `agents/egs_agent/tests/test_replanning_validation_logging.py`         | unit        | yes       |
| 1     | `agents/egs_agent/tests/test_coordinator_attempt_log_lifecycle.py`     | unit+async  | yes       |
| 1     | `frontend/ws_bridge/tests/test_aggregator_replan_attempt_log_passthrough.py` | unit  | yes       |
| 2     | `frontend/flutter_dashboard/test/mission_state_replan_attempt_parse_test.dart` | unit | yes  |
| 2     | `frontend/flutter_dashboard/test/validation_wow_banner_test.dart`      | widget      | yes       |
| 2     | `frontend/flutter_dashboard/test/validation_wow_banner_layout_regression_test.dart` | widget | yes |
| 3     | `sim/tests/test_wow_moment_scenario_loads.py`                          | unit        | yes       |
| 3     | `ml/evaluation/tests/test_eval_wow_moment_trigger_harness.py`          | unit        | yes       |
| 3     | `scripts/tests/test_measure_e4b_replan_latency.py`                     | unit        | yes       |
| 3     | `agents/egs_agent/tests/test_inject_overcount_flag.py`                 | unit        | only if 3c ships |
| 4     | `shared/tests/test_contract_version_bump.py` (NEW or extend)           | regression  | yes — IRON RULE |
| 4     | `frontend/ws_bridge/tests/test_e2e_egs_replan_attempt_log_real_redis.py` | integration | yes      |
| 4     | `frontend/ws_bridge/tests/test_e2e_playwright_validation_wow.py`       | E2E         | yes       |
| 4     | `scripts/check_wow_moment.sh`                                          | smoke gate  | yes       |
| 5     | `docs_assets/tests/test_wow_moment_assets_present.py`                  | regression  | yes       |

Coverage shape: each line of new production code in Phases 1+2+3 has at
least one unit test exercising it, plus the Phase 4 integration test
proving the layers connect, plus the Phase 4 E2E test proving the DOM
renders, plus the Phase 5 smoke runner gating capture day.

## Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Gemma E4B refuses to hallucinate over-count even on awkward geometry | medium | Eval gate (Phase 3b); Phase 3c debug injection fallback with writeup disclosure |
| 10-second clip cannot fit a 2-attempt real-time run | medium | Phase 3a measurement decides between single-take vs jump-cut |
| Contract version bump breaks an unrelated Playwright DOM test | low | Mandatory regression test in Phase 4 catches schema-mismatch before merge |
| `replan_in_flight_attempt_log` not cleared, banner persists between replans | low | 3s `asyncio.call_later` clear in coordinator (Phase 1) + Flutter test |
| Stepping on Qasim mid-stream | low | Phase 1 EGS changes touch the same file Qasim owns (replanning.py). Tell him at standup today, hand him the diff for review. Phase 2 + 5 are pure-Ibrahim lanes. |

## Done = ?

1. `docs_assets/dashboard-validation-wow-failed.png` and
   `dashboard-validation-wow-passed.png` exist on disk.
2. `ml/evaluation/eval_wow_moment_trigger.py` reports ≥12/20 triggers (or
   Phase 3c debug-injection shipped with disclosure).
3. `scripts/measure_e4b_replan_latency.py` p95 documented in this plan.
4. Playwright E2E `test_e2e_playwright_validation_wow.py` green.
5. Contract version regression test green; `contract_version.dart` regenerated.
6. Storyboard Pre-Flight Checklist row 3c marked green.
7. The 10-second clip can be filmed in a single uninterrupted take (or
   documented jump-cut strategy in capture runbook).

## Decisions captured (rev 1 → rev 2)

- **1A** chosen over 1B/1C — mirror drone-side `ValidationEventLogger` pattern.
- **2B** chosen over 2A/2C — new transient field, don't poison Contract 11 audit tail.
- **3C** chosen over 3A/3B — banner mirrors `EgsLinkSeveredBanner` pattern, zero grid relayout.
- **4A** chosen over 4B/4C — measure first, decide capture strategy from data.
- **5A** chosen — fixed wrong outcome-matcher table in rev 1.
- **6B** chosen over 6A/6C — server-provided `corrective_text` field on `ReplanAttempt`, single source of truth.
- **7A** chosen over 7B/7C — eval gate with ≥12/20 acceptance, Phase 3c kept as safety net.
- **Issue 8** mandatory — contract version regression test, no option.

## /review fixes applied 2026-05-12 (post-implementation pass)

After implementation, a `/review` pass surfaced three follow-ups. All three
applied + verified the same session:

1. **Playwright fixture rebuild detection (test-infra bug, P0 for capture day).**
   `frontend/ws_bridge/tests/conftest.py:_flutter_bundle_is_stale` previously
   compared `lib/**/*.dart` mtimes against `build/web/index.html`. index.html
   can be touched without a real JS recompile, so a stale `main.dart.js` was
   accepted as fresh and 3/4 Playwright tests failed on a clean re-run
   (banner widget code missing from compiled JS). Fixed: staleness reference
   switched to `build/web/main.dart.js` (the load-bearing compiled output).
   Verified by touching `lib/main.dart` and re-running Playwright — fixture
   auto-rebuilt (29 s → 175 s runtime), all 4 tests green.

2. **Replan fallback path log_sink (P1 UX gap).**
   `agents/egs_agent/replanning.py` deterministic-round-robin fallback path
   now calls `log_sink(...)` with `valid=False` and
   `corrective_text="Maximum retries exceeded — using deterministic
   round-robin fallback."` so the dashboard wow-banner shows an explicit
   terminal "FAILED" row instead of cutting off at the last invalid attempt.
   Mirrors the success-path terminal sink call. Existing
   `test_replanning_validation_logging.py` continues to pass.

3. **Cosmetic: asyncio API modernization.**
   `agents/egs_agent/coordinator.py:_schedule_replan_attempt_log_clear`
   replaced `asyncio.get_event_loop()` (deprecated since Python 3.10) with
   `asyncio.get_running_loop()`. Existing
   `test_coordinator_attempt_log_lifecycle.py` continues to pass.

Post-fix verification: full 69-test new-suite green, Playwright 4/4 green,
no regressions in GH-#32 retry-loop tests (`test_replanning.py`,
`test_coordinator_replan_hang.py`).

## Appendix: Eval Results (2026-05-14 / 2026-05-15)

### `eval_wow_moment_trigger.py` JSON

#### Run 1 — Ibrahim, M1 16GB (2026-05-14, partial)

Aborted after 2 runs due to M1 speed constraints. 0/2 triggers.

```json
{
  "runs": 2,
  "mismatches": 0,
  "fraction": 0.0,
  "threshold": 12,
  "per_run": [
    {
      "run": 0,
      "rule_ids": [],
      "had_mismatch": false
    },
    {
      "run": 1,
      "rule_ids": [],
      "had_mismatch": false
    }
  ],
  "passed": false
}
```

#### Run 2 — Qasim, RTX A2000 8GB (2026-05-15, clean 5-run)

Clean execution on CUDA box. Every run exhausted retries and fell through to deterministic fallback. The base model cannot produce valid survey-point assignments at all, so `ASSIGNMENT_TOTAL_MISMATCH` never fires. **0/5 triggers → acceptance gate FAILED → Phase 3c is REQUIRED.**

```json
{
  "runs": 5,
  "mismatches": 0,
  "fraction": 0.0,
  "threshold": 12,
  "per_run": [
    {"run": 0, "rule_ids": [], "had_mismatch": false},
    {"run": 1, "rule_ids": [], "had_mismatch": false},
    {"run": 2, "rule_ids": [], "had_mismatch": false},
    {"run": 3, "rule_ids": [], "had_mismatch": false},
    {"run": 4, "rule_ids": [], "had_mismatch": false}
  ],
  "passed": false
}
```

### `measure_e4b_replan_latency.py` Latency

#### Ibrahim, M1 16GB (2026-05-14, partial)

| Metric                              | p50 (s) | p95 (s) | N  |
|-------------------------------------|---------|---------|----|
| Single attempt                      | 127.30  | 139.64  | 10 |

#### Qasim, RTX A2000 8GB (2026-05-15, clean 10-iteration)

| Metric                              | p50 (s) | p95 (s) | N  |
|-------------------------------------|---------|---------|----|
| Single attempt                      | 129.03  | 143.05  | 10 |

**Capture Strategy Decision:** p95 ~143s on CUDA box, ~140s on M1. The 8-second camera-window budget is unachievable by ~18×. **Jump-cut** strategy is the only viable option.

### Phase 3c Decision: CONFIRMED

| Evidence | Result |
|---|---|
| Natural trigger rate (M1, 2 runs) | 0/2 (0%) |
| Natural trigger rate (CUDA, 5 runs) | 0/5 (0%) |
| Combined | **0/7 (0%)** — model cannot produce valid assignments |
| Root cause | E4B exhausts all retry attempts → deterministic fallback |
| Decision | **Ship Phase 3c `--inject-overcount-once`** (already implemented) with honest disclosure in WRITEUP.md §6.5 |
| Owner of disclosure edit | Ibrahim |
