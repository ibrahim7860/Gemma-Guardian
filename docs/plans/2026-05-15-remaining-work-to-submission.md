# Remaining Work to Submission — Fri 5/15 → Mon 5/18

**Drafted:** 2026-05-15 (Fri, GATE 4 day)
**Submission deadline:** Mon May 18, 23:59 UTC (target submit 18:00 UTC = 1 PM CDT, with buffer)
**Time remaining:** ~3.5 days (Fri afternoon + Sat + Sun + Mon)
**Owner of this doc:** Ibrahim — strike items as they ship, log surprises inline.

Sources cross-referenced: `TODOS.md`, `docs/STATUS.md`, `docs/17-feasibility-and-gates.md`, `docs/19-day-by-day-plan.md`, `docs/21-demo-storyboard.md`, `docs/22-writeup-draft.md`, `WRITEUP.md`, `README.md`, `docs/23-submission-checklist.md`, `docs/12-fine-tuning-plan.md`, and 13 open files under `docs/plans/`.

---

## Three things to flag up front

- [x] **GATE 4 wow-moment Phase 5 is on Qasim's plate** — reassigned 2026-05-12 (`TODOS.md` L25, `STATUS.md` L48) because M1 can't carry E4B at usable speed.
- [x] **Kaggle Model is now public** with a published variation (v3 `Transformers/lora-c2a-bf16`). Notebook also public.
- [x] **`WRITEUP.md` §6 rewritten 2026-05-15** to C2A victim-detection narrative (Kaggle Model + notebook links, v11 numbers, Unsloth #2290 disclosure). SUBMIT-DAY HTML comment stripped. Sits at lines 78-88. Numbers refreshed 2026-05-15 PM to published v11 (`kaggle_out_c2a/adapter/eval_summary.json`): binary 77.25%, F1 0.78 (precision 0.79 / recall 0.77), C2A 97.2% / AIDER 77.5% / SARD 55%.
- [x] **C2 + C3 fully assigned to Qasim 2026-05-15 (PM update):** Route probe AND adapter wiring AND PR are all Qasim. Reason: he runs the full demo on CUDA, his inner dev loop is <1 min/iteration (vs 10-30s/inference on M1), and he's already touching the integrated drone agent for the GATE 3 retest. Co-locating writer + debugger eliminates PR roundtrip and removes M1 workaround tax (env-aware device_map, slow inference loop, fp16 quirks). Kaleel still reviews the PR (drone agent code is his domain). Ibrahim provides handoff package: pointers to `kaggle_out_c2a/adapter/qasim_inference.py` (reference inference flow) and `kaggle_out_c2a/adapter/prompts.py` (parser handles SARD low-confidence quirks). Ibrahim's freed Fri/Sat-AM time pulls writeup G1-G4 forward to Friday + dashboard polish + idle-pocket pull-forward.
- [x] **Track E moved 2026-05-15:** Captures (E1-E4) split — Beats 1-4 begin Sat PM after code complete, Beat 5 Sun. Sat morning = finish all code (PR merges, sweeps, cold-run); Sat afternoon = filming starts.
- [x] **Schedule shape (corrected 2026-05-15):** Fri = today, code sprint. Sat AM = code complete. Sat PM = filming begins. Sun = film + edit + docs. Mon = submit by 18:00 UTC (6 hr before deadline).
- [x] **Wow-moment P0 regression caught + fixed 2026-05-15 PM (commit `3db1ab4`):** Qasim's `24f533b "replanning fix attempt"` had left the injection + validation + return block indented inside the `else:` branch when he added the Phase 3c LLM-bypass shortcut — the shortcut path infinite-looped on `asyncio.sleep(2.0)` because no validation ran. Would have deadlocked Beat 3c capture. Discovered during C7 verification (test hung at 30s timeout, reproduced solo). Dedented the block + gated the shortcut to attempt 1 only (so attempt 2 runs real E4B per WRITEUP.md §6.5). 104/104 egs_agent tests green. Full addendum: `docs/plans/2026-05-12-gate4-wow-moment.md` "Addendum: Phase 3c regression catch + fix".
- [x] **Qasim shipped Buckets 1-3 Fri evening 2026-05-15:** C1 + C2 + C3 + C4 + C5 closed in 5 commits (`f81c3d6`, `4f1a837`, `f421f4f`, `962fc28`, `435c7e5`). **C1** standalone 3/3 victim ✅. **C3** in-process integration via `agents/drone_agent/c2a_inference.py` (293 LOC, route (b) PEFT/HF, ClippableLinear unwrap + DoRA key rename baked in) + fast-path in `DroneAgent.step()` + `--c2a-adapter-path` CLI flag + graceful fallback + 19 new tests + 3/3 integrated victim acceptance on RTX A2000 ✅. **C4** 0/5 wow-moment triggers (combined 0/7) → Phase 3c REQUIRED. **C5** p50=129s p95=143s → jump-cut confirmed. **C6** flag already shipped (`3b86d9a`); only `WRITEUP.md` §6.5 honest disclosure paragraph remains (Ibrahim). Code-complete sprint effectively finished Fri evening — Sat AM collapses to dress rehearsal + cleanup tracks (J3/J4/J5/K1).
- [x] **J5 Ibrahim lanes swept 2026-05-16 AM (parallel subagent dispatch):** `agents/drone_agent/` clean baseline, no edits. `frontend/ws_bridge/` 3 substantive Python changes (5× `print` → `logger`, 1× `print(sys.stderr)` → `_LOG.warning` + drop unused `import sys`, hardcoded `/Users/appleuser/...flutter` → `FLUTTER_BIN` env var). `frontend/flutter_dashboard/lib/**` `dart format` reflow on 7 files (no logic change). 92/92 ws_bridge tests green incl. real flutter-build fixture, `flutter analyze` clean, ~50 substantive LOC. Black not run repo-wide (no `pyproject.toml` config, Hazim's sim/ also skipped; project-wide call, not a J5 one). **Post-freeze backlog:** `agents/drone_agent/redis_io.py:222,355` `await pubsub.close()` → `aclose()` (redis-py 5.0.1+ deprecation, 76 warnings/run, non-blocking, defer to post-submission).

---

## TODAY — Friday May 15 (GATE 4 day, code sprint)

### Track A — Ibrahim — Kaggle artifact + handoff (~1-2 hr)
- [x] **A1.** Upload C2A adapter as Kaggle Model variation (`Transformers/lora-c2a-bf16/3`)
- [x] **A2.** Flip Model visibility to Public
- [x] **A3.** Flip Notebook visibility to Public
- [x] **A4.** Verify C2A dataset citation visible on the public notebook (`rgbnihal/c2a-dataset`)
- [x] **A5.** Send Qasim the handoff message (drafted in conversation — buckets 1-5)
- [x] **A6.** Update `docs/STATUS.md` L11 + Kaleel's section L34 + Risk Register row to reflect GATE 3 GO + eval numbers

### Track B — All hands — GATE 4 vote (~15 min)
**Single-machine run on Qasim's CUDA box** (the demo box — C2A adapter is in-process PEFT/HF and needs CUDA; E4B latency was measured there; integrated GATE 3 3/3 passed there). Architecture is localhost-only (Redis `:6379`, WS bridge `:9090`, Ollama `:11434`) — no cross-machine networking exists in the codebase. The other three join via screen share (Zoom/Meet/Discord) and observe different surfaces of the same run.

- [x] **B1.** ~~Run GATE 4 evaluation~~ → **FAIL (hardware-constrained).** Qasim ran both 3-drone and 2-drone configs on RTX A2000 8GB (2026-05-16). 8GB VRAM can't hold `gemma4:e2b` + `gemma4:e4b` simultaneously — Ollama model-swaps cause `ReadTimeout` on every replan attempt. Code paths correct (events fire, replan triggers), but no inference completes. No team member has ≥16GB VRAM hardware.
- [x] **B2.** Decision recorded in `docs/decisions.md` — **DROP TO 2-DRONE configuration.** Demo uses `scripts/ollama_mock_server.py` for deterministic capture takes.
- [x] **B3.** ~~If FAIL → drop to 2 drones~~ → **Actioned.** 2-drone config adopted. Storyboard update: "drone 1 surveys west, drone 2 surveys east, drone 1 fails, drone 2 takes over." Writeup frames scaling as future work.

### Track C — STATUS: Buckets 1-3 closed Fri evening by Qasim. C6-disclosure (Ibrahim) + C7/C8 (Kaleel) remain.
**Status as of 2026-05-15 PM:** Qasim cleared C1-C5 + C6-flag in 5 commits Fri evening. The C3 PR didn't need a Kaleel review roundtrip because the integrated 3/3 acceptance passed. Remaining: a one-paragraph writeup disclosure (Ibrahim) and Kaleel's two small parallel items if he hasn't started them.

- [x] **C1.** [Qasim] GATE 3 acceptance test: `qasim_inference.py` on `placeholder_victim_01.jpg` 3× — **PASSED 3/3 `finding_type: victim`** (2026-05-15, RTX A2000 8GB). Required two inference-time fixes: ClippableLinear unwrap + DoRA key rename. `TODOS.md` entry closed.
- [x] **C2.** ~~Route (a) vs (b) decision~~ → **Route (b) PEFT/HF chosen** (commit `962fc28`). Qasim skipped the explicit Ollama Modelfile probe because Unsloth #2290 vision regression is known-dead; went straight to known-good PEFT/HF. **Consequence: no Ollama special-prize claim available** (must drop from writeup — see G4-late).
- [x] **C3.** ~~Wire C2A adapter into drone agent runtime~~ → Done (commit `962fc28`, Qasim). Chose **in-process** (not sidecar): new module `agents/drone_agent/c2a_inference.py` (293 LOC). Wired into `DroneAgent.step()` as fast-path before Ollama call; on victim detection + validation pass, short-circuits Ollama. CLI flag `--c2a-adapter-path` (defaults to `$C2A_ADAPTER_PATH` env or `kaggle_work_c2a/adapter/`). Two non-trivial PEFT/Unsloth fixes baked in (ClippableLinear unwrap of 232 layers + DoRA `lora_magnitude_vector.default` → `.default.weight` key rename).
  - [x] Default-to-base fallback on adapter-load failure ✅ (`c2a=None` → Ollama-only mode, no crash)
  - [x] Parser reuses `kaggle_out_c2a/adapter/prompts.py:parse_model_output` semantics ✅
  - [x] 19 new unit tests in `test_c2a_inference.py` (pure-Python, M1-runnable, no CUDA) ✅
  - [x] **Integrated GATE 3 acceptance through drone agent: 3/3 victim** ✅ (Qasim, RTX A2000)
  - [N/A] PR review: Qasim shipped direct to main. Acceptance proved it works; Kaleel can post-review for cleanup if desired (not blocking).
- [x] **C4.** ~~GATE 4 wow-moment Phase 5~~ → `eval_wow_moment_trigger.py --runs 5` → **0/5 ASSIGNMENT_TOTAL_MISMATCH triggers** on RTX A2000 (commit `435c7e5`). Combined with Ibrahim M1 partial: **0/7 total**. Acceptance gate (≥12/20) **FAILED** → Phase 3c `--inject-overcount-once` is REQUIRED. Eval JSON pasted to `docs/plans/2026-05-12-gate4-wow-moment.md` appendix.
- [x] **C5.** ~~`scripts/measure_e4b_replan_latency.py`~~ → p50=129.03s, p95=143.05s on RTX A2000 (commit `435c7e5`). p95 is ~18× over the 8s camera budget → jump-cut capture confirmed as the only viable strategy. Latency table pasted to wow-moment plan appendix.
- [x] **C6-flag.** ~~`--inject-overcount-once` flag on EGS coordinator~~ → already shipped by Ibrahim in commit `3b86d9a` (wired `main.py` → `coordinator.py` → `replanning.py` with `test_inject_overcount_flag.py`).
- [ ] **C6-disclosure.** [Ibrahim] **NEW remaining item:** add one-paragraph honest disclosure to `WRITEUP.md` §6.5 explaining the Phase 3c injection. The base model can't naturally over-count (0/7 trigger rate on E4B exhausting retries), so the demo deliberately injects one over-count once to demonstrate the validation-and-retry loop. Honest framing per Qasim's bucket-3 ask.
- [x] **C7.** ~~`command_translator.py:70` 180s timeout hoist~~ → Done 2026-05-15 PM (Ibrahim). New constant `COMMAND_TRANSLATOR_HTTPX_PER_ATTEMPT_TIMEOUT_S = 180.0` in `agents/egs_agent/command_translator.py` line 15 with sibling-reference comment; call site at line 82 uses it. 3/3 new tests pass in `agents/egs_agent/tests/test_command_translator_timeout.py`. Plan: `docs/plans/2026-05-15-c7-c8-ibrahim-cleanup.md` §C7.
- [x] **C8.** ~~G5 §7 rewrite + J2 `ml/README.md` + J6 `docs/12-fine-tuning-plan.md` addendum~~ → Done 2026-05-15 PM (Ibrahim). J6: 75-line "What We Shipped" canonical section + Historical xBD divider in `docs/12-fine-tuning-plan.md`. G5: 180-line C2A narrative replaces old xBD §7 in `docs/22-writeup-draft.md`. J2: new 115-line `ml/README.md` respecting content boundary with top-level README. Cross-doc number consistency verified (77.25 / 0.78 / 97.2 / 77.5 / 55) across 4 docs. All 19 relative links resolve. Plan: `docs/plans/2026-05-15-c7-c8-ibrahim-cleanup.md` §C8.

### Track D — Ibrahim — Background retrain (own wall time)
- [x] **D1.** ~~Let v8 smoke test finish~~ → Ran v10 smoke (varied-labels fix, 30 steps, ~15 min, green: loss 3.456→0.382). Kicked off v11 full run (300 steps, ~49 min on T4). Eval: 77.25% binary / 0.78 F1 / 55% SARD (+13pp vs v9). Published as Kaggle Model `lora-c2a-bf16/3` PUBLIC.
- [x] **D2.** Schema confirmed stable: `to_chat_example` at `kaggle_work_c2a/gemma4-victim-vision-lora.py:262-278` emits `{finding_type, confidence, visual_evidence}`. v11 `parse_rate_ok: 1.0` on n=400 eval. Adapter swap is version-agnostic across v9/v10/v11.

### Track D2 — Ibrahim — Pull-forward into freed Fri time (~4-5 hr afternoon/evening)
With C3 handed to Qasim, Ibrahim's Fri afternoon + Sat AM are free. Pull writeup + cleanup work forward so Sat PM is filming-only.
- [x] **D2.1.** ~~Refresh `WRITEUP.md` §6 with published v11 numbers~~ → Done 2026-05-15 PM. `WRITEUP.md:86` now reads: binary 77.25% / F1 0.78 (precision 0.79, recall 0.77) / C2A 97.2% / AIDER 77.5% / SARD 55%.
- [x] **D2.2.** ~~Write `WRITEUP.md` §6.5 disclosure~~ → Shipped in commit `3db1ab4` (2026-05-15 PM). `WRITEUP.md:90` "Wow-Moment Disclosure: Deterministic Hallucination Seed" reads cleanly with the validation/retry-is-real, only-seed-is-deterministic framing.
- [x] **D2.3.** ~~Strip SUBMIT-DAY HTML comment~~ → Done. `grep -n "SUBMIT-DAY\|<!--" WRITEUP.md` returns zero hits.
- [x] **D2.4.** ~~Strip Ollama special-prize claim~~ → Done. `grep -in "special.prize\|ollama prize\|prize claim" WRITEUP.md` returns zero hits. The intentional base-Gemma-Ollama narrative remains at `WRITEUP.md:52` and `WRITEUP.md:88` per the plan ("Ollama-deployment narrative for the *base* Gemma 4 tags still stands; only the adapter-via-Ollama claim is dead").
- [x] **D2.5.** ~~Word-count check (≤1,500)~~ → Trim landed 2026-05-16 AM (Sat). `wc -w WRITEUP.md` = **1495** (cut 237 words from 1732). All 10 `##` section headers preserved. Cuts: adjectives/hedges, repeated transitions, one §4 platform-list elaboration, redundant §1 scaffolding. Load-bearing preserved: §6 numbers (77.25/0.78/0.79/0.77/1.0/97.2/77.5/55), both Kaggle links, Unsloth #2290 link, full §6.5 disclosure (validator/re-prompt/seed framing + p95 numbers), §7 "no drone … has ever flown" verbatim, mocks-and-cuts pointer.
- [x] **D2.6.** ~~Draft `README.md` skeleton (J1 prep)~~ → Done. `README.md:11-16` Submission Links block landed with `[TODO: insert YouTube URL after upload]` placeholder for Sun-evening swap.
- [x] **D2.7.** ~~Pre-stage Kaggle Writeup body for Thayyil~~ → Done. `docs/submission/kaggle_writeup_body.md` (118 lines) mirrors WRITEUP.md sections + 2-3 sentence pitch + Links block.
- [ ] **D2.8.** Dashboard polish if anything from H1 dress rehearsal shakes loose (Sat AM).

---

## SATURDAY — May 16 (Code Complete AM, Filming Starts PM)

**Theme:** Morning = land every line of code. Afternoon = start filming. The code freeze is at Saturday noon (or whenever AM block ends). After freeze, only docs/text/video work.

**Status update 2026-05-15 PM:** Code-complete sprint largely already happened Fri evening via Qasim's 5 commits. Sat AM block collapses to: dress rehearsal, J3/J4/J5/K1 cleanup, drone3 reliability against the now-integrated path, C6 writeup disclosure (Ibrahim), Kaleel's C7/C8 if outstanding.

### Saturday AM — Cleanup + dress rehearsal block (target: noon CDT)

#### Track F — Hazim + Qasim — Integration validation (~1-2 hr — most work pre-done)
- [x] **F1.** ~~drone3 reliability on integrated path~~ → **BLOCKED by same 8GB VRAM constraint as B1.** Qasim's A2000 8GB confirmed same wall as Hazim's 3060 Ti 8GB (2026-05-16). Multi-drone integrated C2A path cannot be validated on any available hardware. Single-drone integrated 3/3 already proven (commit `962fc28`). Deferred to post-submission per `TODOS.md` Post-Submission §"Multi-drone integrated C2A path on 8 GB-class GPUs".
- [x] **F2.** ~~Integration PR review/merge~~ → Qasim shipped direct to main (`962fc28`) since the 3/3 integrated acceptance proved it. Kaleel can do an optional post-merge cleanup review if desired (non-blocking).
- [x] **F3.** Adapter locked at v3.

#### Track J-AM — Code cleanup (each owner sweeps own lane, ~1-2 hr)
- [x] **J3.** [Hazim] `scripts/pull_models.sh` works for Gemma 4 e2b+e4b (pull, `--build-tagged`, `--dry-run` all verified 2026-05-15). Adapter-pull step is route-(a)-conditional ("Ollama prize requirement IF route (a) shipped") and remains deferred to Qasim's C2 outcome.
- [x] **J4.** [Hazim] `scripts/setup.sh` shipped 2026-05-15 (hard `uv` check + soft warns for redis-cli/ollama/tmux + `uv sync --all-extras` default + `--extras=` role-scoped path + `--pull-models` chain + `--dry-run` + `--help` + exit-2 on bad args). Closes checklist L65 / L97. `scripts/run_full_demo.sh --dry-run` no-longer-hangs fix shipped same commit (was unconditional `tail -F` after launch_swarm exited; now early-exits with "dry-run complete" marker). 5 new tests in `scripts/tests/test_launch_scripts.py`; 43/43 launch-script tests + 409/409 Hazim-lane tests green.
- [x] **J5.** [Each owner] Code-quality sweep on own lane: no commented-out blocks, no `print` debug, no hardcoded home paths, no secrets, Black-formatted Python, dartfmt Flutter. **All four lanes closed 2026-05-16.**
  - [x] **Hazim sim/ swept 2026-05-15, clean** (no pdb/breakpoint, no TODO:/FIXME: strings, no hardcoded home paths, sim/ print statements are all legitimate CLI/REPL output).
  - [x] **Ibrahim agents/drone_agent/ + frontend/ swept 2026-05-16, clean** (parallel subagent dispatch). `agents/drone_agent/`: no edits needed — 9 `print()` calls all legit (CLI entrypoints / `StdoutPublisher` whose job is to print / test utilities), no commented-out blocks, no hardcoded paths, no secrets, 157/157 tests green. Flagged for post-freeze: `redis_io.py:222,355` `await pubsub.close()` triggers redis-py 5.0.1+ deprecation (one-liner each to swap to `aclose()`). `frontend/ws_bridge/`: 5× `print()` → `logger.error/warning` in `main.py` async loops, 1× `print(sys.stderr)` → `_LOG.warning` in `redis_subscriber.py` (dropped unused `import sys`), hardcoded `/Users/appleuser/CS Work/flutter/bin/flutter` fallback in `tests/conftest.py` → `FLUTTER_BIN` env var. `frontend/flutter_dashboard/lib/**`: `dart format` pass on 7 files (whitespace/reflow only, 0 logic changes verified). Black skipped repo-wide — no formatter config in `pyproject.toml`, Hazim's sim/ precedent did not run black either; project-wide decision, not a J5 call. Verification: 92/92 ws_bridge tests green (85 unit + 7 fixture incl. real flutter build), `flutter analyze` clean. ~50 substantive LOC diff total.
  - [x] **Qasim agents/egs_agent/ swept 2026-05-16 (Ibrahim-driven via subagent), clean.** Directory was already largely clean (no `print()` in prod, no `sys.stderr`, uses `logging` throughout). 9 files touched, all pure unused-import removals: prod — `command_translator.py` + `replanning.py` drop unused `typing.List`; tests — `test_command_translator.py`, `test_command_translator_timeout.py`, `test_coordinator_attempt_log_lifecycle.py`, `test_coordinator_initial_replan.py`, `test_replanning_validation_logging.py`, `test_scenario_state.py`, `test_validation_log_tail.py` drop unused `pytest` / `Path` / `json` / `MagicMock` / `List` (verified via grep — zero remaining refs per file; `pytest.ini` has `asyncio_mode = auto` so async tests don't need `import pytest` in scope). No formatter pass, no logic changes, no renames. 104/104 egs_agent tests green before and after. Net −11 LOC.
  - [x] **Kaleel ml/ swept 2026-05-16 (Ibrahim-driven via subagent), clean.** Almost nothing to remove — `ml/` is mostly CLI scripts where `print()` is the correct stdout interface (do **not** convert to logging). One change: `ml/evaluation/eval_adapter.py` drops unused `defaultdict` from `from collections import Counter, defaultdict` (Counter still used line 50). 6/6 ml tests green before and after. Net 0 LOC delta (1 insertion / 1 deletion).

#### Track K-AM — Reproduction cold-run (so bugs surface before freeze)
- [x] **K1.** ~~cold-tests reproduction docs from fresh Linux/WSL2 machine per `docs/sim-reproduction.md`~~ → Done 2026-05-16 by Hazim on RTX 3060 Ti 8 GB / WSL2 Ubuntu 24.04 (commit `6d2f71e`, PR #51). 3 findings surfaced, all sim-lane: (1) cold testers weren't pointed at `scripts/setup.sh` (J4 shipped 5/15 but never linked) — fixed §2; (2) `scripts/run_full_demo.sh` umbrella over `launch_swarm.sh` wasn't named despite README + checklist + 10 other docs pointing at it — fixed §4; (3) `scripts/run_drone3_reliability.sh` teardown left 3 zombie drone_agent procs because mid-import torch/peft procs ignore SIGTERM — fixed via `pkill -KILL`. 4th finding (multi-drone-C2A on 8 GB VRAM) escalated to F1 reassignment + post-submission TODO (see F1 above + `TODOS.md` Post-Submission).
- [x] **K3-AM.** ~~Fix any rough edges K1 surfaces — owner of the broken script fixes (Hazim sim, Ibrahim agents/frontend, Qasim EGS, Kaleel ml). Must land before noon freeze.~~ → All 3 K1 sim-lane findings fixed inline by Hazim in commit `6d2f71e` (PR #51 merged 2026-05-16 14:20 CDT, before noon-CDT-freeze grace ran out — landed slightly post-noon but cleanup-only, no semantics changed). No other-owner-lane fixes needed.

#### Track H — Hazim leads, all hands — Saturday dress rehearsal
- [ ] **H1.** Full demo run, identify everything still rough (`19-day-by-day-plan.md` L132). Hazim convenes and confirms sim-stack readiness per his Simulation Lead role (`docs/18-team-roles.md` L160). **This is the last code-touch checkpoint before freeze.**

### 🔒 CODE FREEZE — Saturday noon CDT 🔒
**After this point, no code edits.** Only docs, writeup text, video edit, and submission prep.

### Saturday PM — Filming starts + writeup major pass

#### Track E-Sat — Ibrahim (capture) + Hazim (sim) — Beats 1-4 captures (~3 hr)
- [ ] **E1.** Beats 1-4 captures (Beat 1 NASA SVS Eaton Fire / Beat 2 paper + arch diagram / Beat 4 multilingual + EGS sever). These don't require the integrated adapter path, so we can knock them out first.
- [ ] **E2.** Backup raw `.mov`/`.mp4` files + `$DEMO_DIR` artifacts to second machine — **Thayyil** verifies backup integrity per take

#### Track G — Writeup cleanup (most pulled to Fri via Track D2; residue only)
**G1-G4 moved to Fri (Track D2.2-D2.3) now that Ibrahim has freed Fri afternoon.** What remains on Sat:
- [x] **G4-late.** [Ibrahim] **Done 2026-05-16 AM.** `WRITEUP.md` already clean per D2.4 (`grep -in "special.prize\|ollama prize\|prize claim"` returns 0 hits; base-Ollama narrative preserved at lines 20, 52, 88, 100). `docs/kaggle-submission-draft.md:131` Ollama bullet flipped from **CLAIM** → **NOT CLAIMED** with decision-record rationale (route (b) PEFT/HF + Unsloth #2290 + adapter weakens base-only story); rubric language preserved for record-keeping. `docs/submission/kaggle_writeup_body.md` already clean (no hits). The other 7 docs that grep matches (plans/checklists/feasibility/context/long-form drafts) are historical/informational, not submission-facing — left as-is.
  - **Adjacent: Unsloth bullet xBD → C2A pivot brought current.** While editing §7 noticed sibling Unsloth bullet at line 133 still referenced "xBD post-disaster building damage classification fits this" + GATE 3-conditional outcomes. Rewrote to GATE 3 PASS state with C2A victim-detection narrative + v11 numbers (77.25 / 0.78 / 0.79 / 0.77 / 97.2 / 77.5 / 55 / parse_rate 1.0) + public Kaggle Model + notebook links + Unsloth #2290 honesty caveat + SARD-bounds-claim caveat. Numbers verified consistent with `WRITEUP.md` §6 via cross-grep. Avoids form-vs-writeup discrepancy on submission day.
- [x] **G5.** ~~Update `docs/22-writeup-draft.md` §7 — collapse to GO variant, drop §7.B + conditional banner, re-title to `## 7. Fine-Tuning`.~~ → Done 2026-05-15 PM by Ibrahim as part of C8 pull-forward (see line 62). Verified 2026-05-16: title is `## 7. Fine-Tuning` at line 388, no §7.B, no conditional banner, §§7.1-7.8 = C2A victim-detection narrative. Kaleel's bandwidth went to C3 review instead.

---

## SUNDAY — May 17 (Beat 5 capture + Video lock + Final docs)

**Day shape:** Morning = Beat 5 + wow-moment captures (the integration-dependent ones). Afternoon = video edit to picture-lock. Evening = upload + final writeup pass + non-code cleanup. **No code edits — freeze held from Sat noon.**

### Sunday AM — Captures that need the integrated adapter (~3 hr)
- [ ] **E3.** Beat 5 capture: `scripts/run_beat5_capture.sh` repeatedly + `scripts/check_beat5.py` A1-A6 PASS per take. ≥2-4 backup takes. **Hazim** keeps Redis + sim processes alive between takes; **Ibrahim** captures.
- [ ] **E4.** Wow-moment capture: `scripts/check_wow_moment.sh` before each take; if live trigger fails twice → use deterministic synth-WS PNGs (`docs_assets/dashboard-validation-wow-{failed,passed}.png`)
- [ ] **E5.** [Thayyil] Backup verification for Sun captures + final consolidation of all takes

### Sunday PM — Video lock (~6-8 hr)

#### Track I — Ibrahim (edit) + Thayyil (upload) — Video to picture-lock
- [ ] **I1.** [Ibrahim] Edit in DaVinci Resolve. 1:45 target / 3:00 Kaggle cap. Pacing: B1 0:10 + B2 0:15 + B3 0:40 + B4 0:15 + B5 0:25
- [ ] **I2.** [Ibrahim] Captions throughout + "Software simulation" disclosure caption
- [ ] **I3.** [Ibrahim] Verify mandatory visual elements (`21-demo-storyboard.md` L217-228):
  - [ ] Real sim footage
  - [ ] Dashboard rendering live state
  - [ ] Gemma 4's structured output visible
  - [ ] Validation correction event visible
  - [ ] Multilingual command moment
  - [ ] Offline-proof terminal (`ollama list` + WAN DOWN)
  - [ ] Reference paper citation on screen
  - [ ] GitHub URL at end
- [ ] **I4.** [Ibrahim] Export 1080p MP4 H.264. Forbidden-elements check (no fake screens, no unmeasured perf claims)
- [ ] **I5.** [Thayyil] Upload to YouTube unlisted. Verify publicly viewable without login (incognito test)
- [ ] **I6.** [Thayyil] Backup upload to Vimeo or second YouTube account

### Sunday evening — Non-code cleanup + final writeup (~2-3 hr, all hands)

#### Track J-Sun — Docs/text cleanup only (NO CODE)
- [ ] **J1.** [Ibrahim] `README.md` final pass: add video URL (from I5), Kaggle Model URL, finalize Quick Start
- [x] **J2.** ~~Write `ml/README.md` linking to public Kaggle Model (Unsloth prize requirement).~~ → Done 2026-05-15 PM by Ibrahim as part of C8 pull-forward (see line 62). New 115-line `ml/README.md` respecting content boundary with top-level README. Kaleel's bandwidth went to C3 review instead.
- [x] **J6.** ~~`docs/12-fine-tuning-plan.md` — beef up 2026-05-14 addendum to make C2A canonical, not just a pivot footnote.~~ → Done 2026-05-15 PM by Ibrahim as part of C8 pull-forward (see line 62). 75-line "What We Shipped" canonical section + Historical xBD divider added. Kaleel's bandwidth went to C3 review instead.
- [x] **J7.** ~~`docs/STATUS.md` full sweep — stale GATE 3 references, Kaleel's "Left" → Done, risk register.~~ → Done 2026-05-16 PM (Ibrahim-driven, pre-empted from Sat-Sun queue). Edits: header Day 15→16; `Today` rewrote for Sat AM context + freeze; new `GATE 4 status: PENDING` line distinguishing today's vote from Mon submission lock; `Days remaining` 3→~2.5; Hazim got Sat AM left-items (F1/K1/H1/K3-AM); Kaleel dropped stale "Day 13 / May 15" date, added J5 ml/ + J2 + J6 closure notes, peer-broadcast + cross-drone awareness marked DESCOPED post-submission; Qasim got J5 egs_agent closure + Sat AM keyboard-driver role; Ibrahim got J5 own-lane closure (drone_agent + frontend) + J7 stale-checkbox sweep noted + remaining left-items broken into Sat AM / Sat PM / Sun phases; Thayyil's past-tense "Days 10-13" replaced with concrete day-by-day Sat/Sun/Mon obligations; risk register got 5 new active rows (wow-moment Phase 5 / code-freeze breach / Qasim CUDA-box / YouTube flag / K1 surprises). One historical-date normalization. Net +33 LOC; file 141 lines total.

#### Track K-Sun — Reproduction validation
- [ ] **K2.** [Thayyil] backup tester pass — confirms a non-author can reproduce from clean state. **If K2 surfaces a code bug, it goes on the post-submission punch list — code is frozen.**

#### Track L — Final writeup pass

**L-pre-flight (2026-05-16 PM, Ibrahim-driven via parallel subagent dispatch):** Pre-passes of L1 / L2 / M1 done early to surface any issues 2 days before deadline. **L1 pre-pass:** WRITEUP.md is 1495 words ✓ (≤1500), 10/10 sections present ✓, all canonical numbers consistent (77.25 / 0.78 / 0.79 / 0.77 / 1.0 / 97.2 / 77.5 / 55) ✓, zero TBDs/placeholders/HTML-comments ✓, zero AI-vocab creep ✓. 4 optional polish suggestions logged (L9 long sentence split, L88 "softening"→"narrowing", L92 §6.5 paragraph break, L96 reword) + ~12 em dashes flagged for CLAUDE.md voice-rule consideration — all user's-call, none blocking. **L2 pre-pass:** Kaggle Writeup-vs-notebook requirement is UNCLEAR per `docs/23-submission-checklist.md` L190 ("verify against live Kaggle competition page") — Thayyil still needs to confirm against the live hackathon page. Pre-staged `docs/submission/kaggle_writeup_body.md` audit: 1880 words, all canonical numbers present, mirrors WRITEUP.md sections ✓; one TODO cleared today (L114 GitHub URL — verified resolving in M1, wrapper removed); one TODO remains by design (L115 demo video URL, Sun upload). Body is READY-AFTER-VIDEO-URL-FILLED. **M1 pre-flight:** All 4 submission-facing URLs verified HTTP 200 via curl: GitHub (`ibrahim7860/Gemma-Guardian`), Kaggle Model base, Kaggle Model variation `Transformers/lora-c2a-bf16/3`, Kaggle Notebook (training kernel). Adjacent URLs also verified: Unsloth #2290, arXiv 2601.14437, Kaggle hackathon landing, C2A dataset `rgbnihal/c2a-dataset`. Notebook was 404 on first check; Ibrahim flipped to public mid-session, re-verified 200. None of L1 / L2 / M1 itself is checked off — these stay as Sun/Mon gates per their owners.

- [x] **L1.** ~~Final read-aloud of `WRITEUP.md`. Word count ≤1,500. Tables populated, no `TBD`.~~ → Done 2026-05-16 PM (Ibrahim-driven via subagent, pulled forward from Sun). All 3 spec criteria met: word count **1495** (≤1500 ✓), zero TBDs / placeholders / HTML-comments ✓, no markdown tables in the file so no holes possible ✓. Additional verified: 10/10 `##` section headers present, all canonical numbers consistent (77.25 / 0.78 / 0.79 / 0.77 / 1.0 / 97.2 / 77.5 / 55), zero AI-vocab creep (delve / comprehensive / robust / multifaceted / pivotal / tapestry — all zero hits), all cross-references resolve. 4 optional polish suggestions logged (L9 long-sentence split, L88 "softening"→"narrowing", L92 §6.5 paragraph break, L96 reword) + ~12 em dashes flagged for CLAUDE.md voice-rule consideration — all user-editorial-call, none blocking, not in L1 spec. If no edits land between now and submission, this pre-pass IS the final read-aloud. M2 (Mon final author pass) remains a separate gate.
- [ ] **L2.** [Thayyil] Verify Kaggle Writeup / notebook submission requirement (`23-submission-checklist.md` L190). If yes: publish Kaggle Writeup mirroring `WRITEUP.md` (Ibrahim provides final text).
- [x] **L3.** ~~Draft Kaggle submission form fields as text file (one-line desc ≤140 chars, track, URLs, prize claims, team names) — Ibrahim approves before save.~~ → Drafted 2026-05-16 PM (Ibrahim-driven via subagent, pre-empted from Sun queue). File at `docs/submission/kaggle_form_fields.md`. One-liner crafted at exactly 140 chars: *"On-device Gemma 4 turns a drone swarm into an offline disaster-response coordinator — every brain local, every decision survives the blackout."* 124-char backup also included in file. All URLs grabbed from `README.md` "Submission Links" block (verified resolving 200 via M1 pre-flight — see L-pre-flight note below). Demo video URL marked `[TBV — fill Mon AM after Sun YouTube upload]`. Prize claims: Unsloth CLAIMED (GO), Ollama NOT CLAIMED per G4-late. Team last names pulled from `WRITEUP.md` byline (flag in file: verify spelling with each teammate). Ibrahim reviews before Mon submission.

---

## MONDAY — May 18 (SUBMISSION DAY, GATE 5) — deadline 23:59 UTC

### Morning (9 AM CDT) — Thayyil owns checklist, Ibrahim spot-checks
- [ ] **M1.** [Thayyil] Verify all video + repo + Kaggle Model links work from incognito browsers
- [ ] **M2.** [Ibrahim] Read writeup one more time (final author pass)
- [ ] **M3.** [Thayyil] Commit anything outstanding to main; confirm with each owner before pushing on their behalf
- [ ] **M4.** [Thayyil] Tag release `v1.0-submission` (Ibrahim approves the SHA)
- [ ] **M5.** [Thayyil + Hazim] Verify backup of repo + assets on ≥2 separate machines

### Midday (11 AM – 1 PM CDT) — Thayyil fills form, Ibrahim double-checks
- [ ] **N1.** [Thayyil] Fill out Kaggle submission form (`23-submission-checklist.md` L175-190)
  - [ ] Project name: "FieldAgent"
  - [ ] One-line description (≤140 chars)
  - [ ] Track: Global Resilience (primary)
  - [ ] GitHub URL
  - [ ] Demo video URL
  - [ ] Long description excerpt
  - [ ] Special prize claim: Unsloth (GO)
  - [ ] Special prize claim: Ollama (only if route (a) shipped)
  - [ ] Team member names
  - [ ] Rules acknowledgement
- [ ] **N2.** [Ibrahim] Double-checks every field per submission-checklist requirement L189
- [ ] **N3.** [Thayyil submits, Ibrahim confirms] **Submit by 18:00 UTC = 1 PM CDT** (buffer: ~6 hr before 23:59 UTC deadline)
- [ ] **N4.** [Thayyil] Verify submission appears on Kaggle
- [ ] **N5.** [Thayyil] Save submission confirmation email
- [ ] **N6.** [Thayyil] Make repo public if private (coordinate with Ibrahim on timing)
- [ ] **N7.** [Thayyil] Post confirmation to team channel

### Evening (post-submission)
- [ ] **O1.** Celebrate — all hands
- [ ] **O2.** [Hazim + Thayyil] Backup repo to private storage in case Kaggle/GitHub goes down

### Within 1 week (deferred)
- [ ] **P1.** [Ibrahim] Write `docs/RETRO.md` — what worked, what didn't (project lead retro)

---

## Critical Path (the chain that can ship-block)

```
FRI 5/15 (today) — code sprint:
  Ibrahim ─► C0 handoff package for Qasim (~30 min, top priority)
            ─► D2.2-D2.4 writeup §6 refresh + G2-G4 + README skeleton (pulled forward from Sat PM)
            ─► D2.5 pre-stage Kaggle Writeup body for Thayyil
  Qasim   ─► C1 standalone acceptance ─► C2 route probe ─► C3 wire adapter (sidecar + drone integration) ─► PR (Kaleel reviews Sat AM)
            (parallel background: C4 wow-moment, C5 e4b latency)
  Kaleel  ─► C7 timeout hoist ─► pull-forward G5/J2/J6 drafts
  Hazim   ─► pre-stage J3 pull_models.sh / J4 setup scripts
  Thayyil ─► pre-stage L3 form-fields draft / J7 STATUS.md sweep
  All hands ─► B1-B3 GATE 4 vote (Thayyil scribes)

SAT 5/16 — Code Complete AM, Filming PM:
  AM (target noon CDT freeze):
    Kaleel  ─► reviews Qasim's C3 PR (Ibrahim secondary if available)
    Kaleel/Ibrahim ─► F2 merge once approved
    Qasim   ─► integrated GATE 3 retest (CUDA) — same person who shipped it
    Hazim   ─► F1 drone3 reliability / J3 pull_models / J4 setup scripts / K1 cold-run
    Each    ─► J5 code-quality sweep on own lane
    All     ─► H1 dress rehearsal (last code-touch checkpoint)
  🔒 CODE FREEZE — Sat noon CDT 🔒
  PM:
    Ibrahim+Hazim ─► E1 Beats 1-4 captures (~3 hr)
    Ibrahim       ─► G4-late route reconciliation if needed (writeup mostly done Fri)
    Kaleel        ─► G5 §7 collapse
    Thayyil       ─► E2 backup verification per take

SUN 5/17 — Beat 5 + Video Lock:
  AM: Ibrahim+Hazim ─► E3 Beat 5 / E4 wow-moment captures
  PM: Ibrahim       ─► I1-I4 video edit
      Thayyil       ─► I5-I6 YouTube + Vimeo upload (after I4)
  Evening:
    Ibrahim ─► L1 final read / J1 README (uses I5 URL)
    Kaleel  ─► J2 ml/README / J6 fine-tuning plan addendum
    Thayyil ─► K2 backup tester / J7 STATUS.md / L2 publish Kaggle Writeup / L3 form draft

MON 5/18 — SUBMIT (deadline 23:59 UTC = 6:59 PM CDT):
  9 AM CDT  ─► Thayyil M1-M5 morning verification (Ibrahim spot-checks)
  Midday    ─► Thayyil fills N1, Ibrahim N2 double-checks
  1 PM CDT  ─► Thayyil submits N3 (18:00 UTC, ~6 hr buffer)
  Afternoon ─► N4-N7 verify + post / O2 backup repo
```

---

## Risk Watch

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Qasim's CUDA box has scheduling conflicts | Medium | High | Pre-book CUDA box for Fri-Sat |
| Route (a) Ollama dead (Unsloth #2290) | Known | Medium | Route (b) PEFT/HF; document deviation |
| GATE 3 acceptance fails through integrated path | Low | High | Default-to-base fallback toggle |
| Wow-moment Phase 5 eval <12/20 triggers | Realized once on M1 | Medium | `--inject-overcount-once` + §6.5 disclosure |
| ~~v8/v9 retrain doesn't finish in time~~ | CLOSED 2026-05-15 | — | v11 (`lora-c2a-bf16/3`) shipped + public. No further retrain in scope. |
| Code freeze (Sat noon CDT) breached | High historically | Catastrophic | Hard freeze rule per `17-feasibility-and-gates.md` L132-145. Any code change after Sat noon requires Ibrahim approval AND H1 re-run. |
| C3 PR not landed by Sat noon | Medium | High | Qasim drafts PR Fri evening on CUDA box; Kaleel reviews Sat AM; merge by 11 AM CDT. If Qasim slips, Ibrahim can take over from C0 handoff package on M1 (slower inner loop but viable). |
| Qasim overloaded (C1+C2+C3+C4+C5 same day) | Medium | High | C4/C5 are background-able while C3 codes. Ibrahim's C0 handoff package gives Qasim a head start. If overload manifests, drop C4 to Sat AM (still inside code-complete window). |
| YouTube upload flagged | Low | High | Backup upload to Vimeo |
| Hazim's cold-run (K1) surfaces broken setup script | Medium | Medium | Run K1 Sat AM (pre-freeze); fixes still allowed before noon |

---

## Irreducible Minimums (per `17-feasibility-and-gates.md` L187-197)

Even under extreme pressure, these do NOT get cut:
- Real Gemma 4 inference doing real work (no mocking the LLM itself)
- The validation-and-retry loop (visible in the demo)
- The offline / on-device claim demonstrated (terminal showing no internet)
- ≥1 working drone agent loop on Redis with real Gemma 4 driving decisions
- A submission by May 18, 23:59 UTC

Everything else is negotiable.
