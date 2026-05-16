# TODOS — FieldAgent

Deferred work captured during planning and reviews. Each entry includes context for whoever picks it up.

## Submission Follow-ups

### Writeup §7: collapse Fine-Tuning section after GATE 3 decision
- **What:** `docs/22-writeup-draft.md` §7 currently ships with both 7.A (gate passed — full Unsloth LoRA narrative) and 7.B (gate failed — honest-failure narrative). After the GATE 3 acceptance test (3/3 on `placeholder_victim_01.jpg`) returns a decision, delete the non-applicable variant + the conditional banner above §7.A, and drop the real adapter eval numbers (binary acc 76.75%, parse_rate 1.0, per-source C2A 99% / AIDER 82% / SARD 42%, victim F1 0.76) into the section. This is the only mandatory section-collapse left before submission.
- **Why:** Doc cannot ship with both variants. The conditional shape is a holdover from authoring the writeup before GATE 3 was decided.
- **Pros:** Mechanical edit once the decision is in — one delete + the variant header re-titled to `## 7. Fine-Tuning` (no `A`/`B`).
- **Cons:** none — pure cleanup.
- **Context:** Caught by `/review` of `25b2411`. Project-name decision ("FieldAgent" alone for Kaggle) made in same review. Surrounding submission artifacts (README, Kaggle form, writeup) all reviewed clean except this single deferred item.
- **Owner:** Ibrahim (frontend/writeup), unblocked by the GATE 3 acceptance-test result.

## Demo Capture Follow-ups

### GATE 4 wow moment Phase 5 — live eval + capture
- **What:** Implementation shipped 2026-05-12 in commit `3b86d9a` (storyboard Sub-beat 3c). Phase 5 is the human-in-the-loop close-out: (1) `uv run python ml/evaluation/eval_wow_moment_trigger.py --runs 20` on the demo box; paste pass/fail + per-run rule_ids into the plan. (2) `uv run python scripts/measure_e4b_replan_latency.py`; paste p50/p95 into the plan to decide single-take vs jump-cut capture. (3) `bash scripts/check_wow_moment.sh` immediately before the capture session — exit 0 greenlights, exit 1 aborts. (4) Capture `docs_assets/dashboard-validation-wow-{failed,passed}.png`. (5) If eval reports <12/20 triggers, ship Phase 3c debug-injection fallback (`--inject-overcount-once` flag on `agents/egs_agent/main.py`) with one-paragraph writeup §4.3 disclosure.
- **Why:** Phase 1–4 (code + tests + iron-rule contract regression) is done; Phase 5 is the demo-day verification + asset capture that the storyboard depends on. Without live numbers in the plan, we can't decide the capture cadence.
- **Pros:** Closes the storyboard's load-bearing technical-innovation moment.
- **Cons:** Burns ~30–60 min of demo-box time. Slight risk that Gemma 4 E4B doesn't naturally over-count, triggering Phase 3c.
- **Context:** Plan: `docs/plans/2026-05-12-gate4-wow-moment.md`. Backend ships per-attempt validation events on `validation_events.jsonl` AND a transient `replan_in_flight_attempt_log` on the EGS state envelope. Dashboard banner mounts under `EgsLinkSeveredBanner` at `main.dart:156` and renders red→green chips with server-provided corrective text. Phase 4 cross-cutting tests + Playwright E2E green; reference screenshot at `/tmp/gg_wow_moment_capture/wow_moment_passed.png` (59 KB).
- **Partial progress (2026-05-12 evening, Ibrahim):** ran an attempted close-out on M1 16 GB but the demo box can't carry `gemma4:e4b` at usable speed — every `assign_survey_points` call took 1–10 min, Ollama runner kept getting swapped under memory pressure. (1) Eval: aborted both a 20-run pass (48 min) and an 8-run pass (47 min) before either could print JSON; observational evidence at the time was ≥ 5 terminal `failed after retries` events out of 8 attempted runs (= 62.5 % rule-trigger lower bound), but **no clean `per_run.rule_ids` JSON was collected.** (2) Latency: only 2 single-attempt measurements landed (421 s, 555 s) before aborting — enough to decide jump-cut capture, but not a real p50/p95. (3) `scripts/check_wow_moment.sh --timeout 240` was exercised and FAILED on this run (E4B produced one invalid-but-non-overcount assignment) — the stochastic-trigger risk realized. (4) Both reference PNGs were captured deterministically via the synth-WS Playwright path and are on disk: `docs_assets/dashboard-validation-wow-failed.png` (56 KB, 1665×720) and `docs_assets/dashboard-validation-wow-passed.png` (59 KB, 1665×737). Detail log in `docs/plans/2026-05-12-gate4-wow-moment.md` "Phase 5 close-out execution" section.
- **Completed (2026-05-15, Qasim — RTX A2000 8GB CUDA box):** (1) Eval: `eval_wow_moment_trigger.py --runs 5` → 0/5 ASSIGNMENT_TOTAL_MISMATCH triggers (every run exhausted retries → deterministic fallback; model cannot produce valid assignments, let alone over-count). Combined with Ibrahim's M1 partial: 0/7 total. Acceptance gate (≥12/20) **FAILED** → Phase 3c debug-injection fallback **REQUIRED**. (2) Latency: `measure_e4b_replan_latency.py --iterations 10` → p50=129.03s, p95=143.05s. Confirms jump-cut capture strategy (p95 is 18× over 8s budget). (3) Phase 3c `--inject-overcount-once` already implemented by Ibrahim (commit `3b86d9a`): wired through `main.py` → `coordinator.py` → `replanning.py` with tests in `test_inject_overcount_flag.py`. (4) Reference PNGs on disk (no recapture needed). (5) Both eval JSON and latency table pasted into `docs/plans/2026-05-12-gate4-wow-moment.md` appendix. **Remaining:** Ibrahim to add one-paragraph honest disclosure to WRITEUP.md §6.5.
- **Owner:** ~~Qasim~~ **CLOSED.** Disclosure edit → Ibrahim.

## ML / Fine-Tuning Follow-ups

### ~~GATE 3 acceptance test — `report_finding(type='victim')` 3/3 on the wow-moment frame~~ ✅ CLOSED
- **Result:** **PASS — 3/3 `finding_type: victim`** on `placeholder_victim_01.jpg`, valid JSON envelopes. Completed 2026-05-15 by Qasim on RTX A2000 8GB (CUDA box).
- **Fixes required for local inference:** The bundled `qasim_inference.py` needed two patches to run on the CUDA box: (1) **ClippableLinear unwrap** — vanilla PEFT doesn't support `Gemma4ClippableLinear` (a Gemma 4 custom module); unwrapping 232 layers to their inner `nn.Linear` before PEFT injection resolved the `ValueError`. (2) **DoRA magnitude-vector key rename** — Unsloth saves DoRA keys as `...lora_magnitude_vector.default` but vanilla PEFT expects `...lora_magnitude_vector.default.weight`; renaming in a temp copy before `PeftModel.from_pretrained` fixed the UNEXPECTED/MISSING key mismatch. Base model loaded in fp16 (not 4-bit) to fit in 8GB VRAM.
- **Context:** Adapter artifacts at `kaggle_work_c2a/adapter/` (Kaggle cache symlinks): `adapter_model.safetensors` (~120 MB), `qasim_inference.py`, `prompts.py`, `chat_template.jinja`, `eval_summary.json`. Adapter loads via PEFT on top of `unsloth/gemma-4-E2B-it`. GGUF path is dead (Unsloth #2290 vision capability loss), so PEFT/HF inference is the route.
- **Owner:** Qasim (completed).

### ~~Wire C2A adapter into drone agent runtime~~ ✅ CLOSED
- **Result:** **Route (b) — PEFT/HF inference path** implemented 2026-05-15 by Qasim. Route (a) Ollama Modelfile is dead (Unsloth #2290 vision capability loss confirmed during GATE 3).
- **Implementation:** New `agents/drone_agent/c2a_inference.py` module: loads base model (4-bit), applies GATE 3 fixes (ClippableLinear unwrap + DoRA key rename), loads PEFT adapter, exposes `analyze_frame()` → `report_finding` dict. Wired into `DroneAgent.step()` as a fast-path before Ollama reasoning. CLI flag `--c2a-adapter-path` (default `$C2A_ADAPTER_PATH` or `kaggle_work_c2a/adapter/`). Graceful fallback: adapter load failure → warning + Ollama-only mode (demo never crashes).
- **Version-agnostic:** Swapping v3 → v8/v9 is a path/tag change, no code change.
- **Tests:** `agents/drone_agent/tests/test_c2a_inference.py` — parser, translator, path resolution, schema compliance.
- **Context:** Per `docs/05-per-drone-agent.md` + `docs/12-fine-tuning-plan.md` §"Workflow regardless of path" step 5.
- **Owner:** Qasim (completed).

### `command_translator.py:70` — sibling `180.0` httpx timeout literal
- **What:** Hazim's GH #32 fix (commit `d86a7d9`) hoisted `replanning.py`'s per-attempt timeout from inline `180.0` → module constant `EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S = 30.0`. The same literal exists at `agents/egs_agent/command_translator.py:70` in the operator-command-translation path (`httpx.AsyncClient().post(..., timeout=180.0)`). Hazim's commit acknowledges it but intentionally left it: that path has no outer `wait_for` guard and is not on the resilience-scenario critical path.
- **Why:** Defense-in-depth + DRY. If a future change adds an outer guard on the operator-command path (mirroring the replan-task lifecycle pattern), the same bug class as GH #32 would re-appear. Hoisting now keeps the project consistent and lets any future invariant-test cover both paths.
- **Pros:** ~5 LOC change. Either import `EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S` from `replanning.py` (creates module coupling) OR define a parallel `COMMAND_TRANSLATOR_HTTPX_TIMEOUT_S` constant (cleaner, but introduces drift risk).
- **Cons:** Behavior change. If operator-command translation genuinely needs >30s on a slow box, dropping the timeout will start producing failures. Worth measuring before committing to a value.
- **Context:** Surfaced by `/review` of Hazim's PR #48 (2026-05-13). Hazim's commit message explicitly flagged this as Qasim's lane.
- **Owner:** Qasim (EGS).

## Post-Submission

### Multi-finding-type LoRA adapter
- **What:** The active C2A-trained adapter (`kaggle_work_c2a/`) is purpose-built for **victim detection only** — binary `finding_type: victim | none` schema. FieldAgent's full perception spec lists 5 finding types (victim, fire, smoke, damaged_structure, blocked_route); the non-victim types currently rely on base Gemma 4 E2B at runtime. Post-submission, train a multi-class adapter that emits the full `report_finding(type=...)` enum.
- **Why:** Demo only needs victims (the wow-moment). Other finding types work via base Gemma well enough for non-load-bearing scenes. Multi-class training would dilute the signal and risk losing the GATE 3 win.
- **Pros:** Unified adapter for all 5 finding types; richer demo capability for fire/smoke/blocked_route scenarios.
- **Cons:** Need diverse training data per finding type (C2A doesn't cover fire/smoke detection directly). Estimated 2-3 days of dataset work (C2A + AIDER + xBD merge) + 1 day training.
- **Context:** Surfaced 2026-05-14 during the C2A pivot decision (user explicitly chose to focus narrow on victim detection for the hackathon). Active C2A scaffold: `kaggle_work_c2a/`. xBD belt-and-suspenders adapter: `kaggle_work/`. Both produce LoRA adapters; unify post-submission via further training or adapter-merge techniques.
- **Owner:** TBD post-submission.
