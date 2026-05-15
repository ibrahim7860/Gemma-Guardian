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
- [ ] **B1.** Run GATE 4 evaluation per `docs/17-feasibility-and-gates.md` L105-130 (5 multi-drone criteria)
  - Hazim runs the 3-drone sim scenario; Qasim confirms EGS replanning; Ibrahim confirms dashboard reflects state; Thayyil scribes
- [ ] **B2.** Record PASS/FAIL decision in `docs/decisions.md` (per L178-185) — **Thayyil** writes up the decision
- [ ] **B3.** If FAIL → drop to 2 drones, update storyboard — Ibrahim arbitrates, Hazim updates scenario YAML

### Track C — Qasim owns CUDA + adapter integration; Kaleel reviews + parallel work; Ibrahim handoff support — 4-6 hr
**Split:** Qasim owns the full CUDA lane plus adapter wiring (single ownership — fast inner loop, no PR roundtrip). Kaleel reviews PR + ships small parallel tasks. Ibrahim ships the handoff package early today so Qasim can start C3 immediately, then pivots to writeup pull-forward.

- [ ] **C1.** [Qasim] GATE 3 acceptance test: `qasim_inference.py` on `placeholder_victim_01.jpg` 3× — need 3/3 `finding_type: victim` (`TODOS.md` L29-33). CUDA-bound, standalone script.
- [ ] **C2.** [Qasim] Route (a) vs (b) decision — runs right after C1 passes. 30-min Ollama Modelfile `ADAPTER` probe on CUDA box (`FROM gemma4:e2b` + `ADAPTER /path/to/adapter`, `ollama create`, vision smoke against `placeholder_victim_01.jpg`). Hard 1-hr cap before falling back to route (b) PEFT/HF. Route decision feeds C3 (his own next task).
- [ ] **C3.** [Qasim] Wire C2A adapter into drone agent runtime per chosen route (`TODOS.md` L35-39)
  - [ ] Sidecar HTTP server at `agents/vision_classifier/` wrapping `qasim_inference.py` logic (PEFT/HF route) — POST /classify, env-aware device_map (cuda first). New `vision` extra in `pyproject.toml` for FastAPI + torch + transformers + peft.
  - [ ] Drone agent integration in `agents/drone_agent/reasoning.py`: optional `VisionClassifierClient` pre-step before Ollama call. Result appended to user prompt as classifier hint. If classifier unreachable or 5xx → graceful skip (default-to-base fallback).
  - [ ] Parser handles SARD-style low-confidence outputs gracefully (eval shows 55% accuracy on that source) — reuse `kaggle_out_c2a/adapter/prompts.py:parse_model_output` verbatim.
  - [ ] Unit tests for sidecar server (mocked model in CI) + drone agent integration (mocked classifier).
  - [ ] Re-run GATE 3 acceptance **through integrated drone agent** (not standalone script) on CUDA box. **This is also Qasim — same person who shipped the integration retests it.**
- [ ] **C4.** [Qasim] GATE 4 wow-moment Phase 5: `ml/evaluation/eval_wow_moment_trigger.py --runs 20` — paste results to `docs/plans/2026-05-12-gate4-wow-moment.md`. Independent of C3 — runs on EGS+E4B path. Can run as background task while C3 codes.
- [ ] **C5.** [Qasim] `scripts/measure_e4b_replan_latency.py` — paste p50/p95. Background-able.
- [ ] **C6.** [Qasim] If C4 reports <12/20 triggers → ship `--inject-overcount-once` flag on `agents/egs_agent/main.py` + writeup §6.5 disclosure
- [ ] **C7.** [Kaleel] `command_translator.py:70` 180s timeout hoist (`TODOS.md` L41-47) — small code change, not CUDA-bound, parallel to C3
- [ ] **C8.** [Kaleel] Pull-forward parallel work while waiting to review C3: G5 §7 collapse + J2 ml/README.md + J6 fine-tuning plan addendum. All independent.

### Track D — Ibrahim — Background retrain (own wall time)
- [x] **D1.** ~~Let v8 smoke test finish~~ → Ran v10 smoke (varied-labels fix, 30 steps, ~15 min, green: loss 3.456→0.382). Kicked off v11 full run (300 steps, ~49 min on T4). Eval: 77.25% binary / 0.78 F1 / 55% SARD (+13pp vs v9). Published as Kaggle Model `lora-c2a-bf16/3` PUBLIC.
- [x] **D2.** Schema confirmed stable: `to_chat_example` at `kaggle_work_c2a/gemma4-victim-vision-lora.py:262-278` emits `{finding_type, confidence, visual_evidence}`. v11 `parse_rate_ok: 1.0` on n=400 eval. Adapter swap is version-agnostic across v9/v10/v11.

### Track D2 — Ibrahim — Pull-forward into freed Fri time (~4-5 hr afternoon/evening)
With C3 handed to Qasim, Ibrahim's Fri afternoon + Sat AM are free. Pull writeup + cleanup work forward so Sat PM is filming-only.
- [x] **D2.1.** ~~Refresh `WRITEUP.md` §6 with published v11 numbers~~ → Done 2026-05-15 PM. `WRITEUP.md:86` now reads: binary 77.25% / F1 0.78 (precision 0.79, recall 0.77) / C2A 97.2% / AIDER 77.5% / SARD 55%.
- [ ] **D2.2.** Pull G2-G4 forward: strip SUBMIT-DAY HTML comment at `WRITEUP.md:80`, word-count check (≤1,500), route (b) Ollama prize-line cleanup if applicable.
- [ ] **D2.3.** Draft `README.md` skeleton (J1 prep) with placeholder for video URL — Sun evening just swaps the URL in.
- [ ] **D2.4.** Pre-stage Kaggle Writeup body for Thayyil (L2 dependency) — gives him a clean text to publish Sun.
- [ ] **D2.5.** Dashboard polish if anything from H1 dress rehearsal shakes loose (Sat AM).
- [ ] **D2.6.** Be available Sat AM for PR review

---

## SATURDAY — May 16 (Code Complete AM, Filming Starts PM)

**Theme:** Morning = land every line of code. Afternoon = start filming. The code freeze is at Saturday noon (or whenever AM block ends). After freeze, only docs/text/video work.

### Saturday AM — Code Complete block (target: noon CDT)

#### Track F — Hazim + Qasim + Ibrahim — Integration validation (~2-3 hr)
- [ ] **F1.** [Hazim] drone3 reliability on integrated path: `scripts/run_drone3_reliability.sh` 3× — need 3/3 hits. Hazim owns the sim script + run; Qasim confirms findings flow through EGS.
- [ ] **F2.** Integration PR merged — **Kaleel** reviews Qasim's C3 PR (drone agent code is Kaleel's domain). Ibrahim secondary-reviews if available. Once approved, either Ibrahim or Kaleel merges. Qasim then runs the integrated acceptance retest on CUDA (same person who shipped it).
- [ ] **F3.** Adapter is locked at v3 — no retrain decision needed (see "Three things to flag up front" — v11 is shipped and public).

#### Track J-AM — Code cleanup (each owner sweeps own lane, ~1-2 hr)
- [ ] **J3.** [Hazim] `scripts/pull_models.sh` works for both Gemma 4 tags + adapter (Ollama prize requirement IF route (a) shipped)
- [ ] **J4.** [Hazim] `scripts/setup.sh` + `scripts/run_full_demo.sh` end-to-end works
- [ ] **J5.** [Each owner] Code-quality sweep on own lane: no commented-out blocks, no `print` debug, no hardcoded home paths, no secrets, Black-formatted Python, dartfmt Flutter. Hazim sim/, Ibrahim agents/drone_agent/ + frontend/, Qasim agents/egs_agent/, Kaleel ml/

#### Track K-AM — Reproduction cold-run (so bugs surface before freeze)
- [ ] **K1.** [Hazim] cold-tests reproduction docs from fresh Linux/WSL2 machine per `docs/sim-reproduction.md`
- [ ] **K3-AM.** Fix any rough edges K1 surfaces — owner of the broken script fixes (Hazim sim, Ibrahim agents/frontend, Qasim EGS, Kaleel ml). Must land before noon freeze.

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
- [ ] **G4-late.** [Ibrahim] Final route-decision reconciliation: if Qasim's C2 ended up route (b) and writeup was drafted Fri assuming route (a), strip Ollama special-prize claim now.
- [ ] **G5.** [Kaleel] Update `docs/22-writeup-draft.md` §7 — collapse to GO variant, drop §7.B + conditional banner, re-title to `## 7. Fine-Tuning`. Kaleel owns this section because it's his ML domain.

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
- [ ] **J2.** [Kaleel] Write `ml/README.md` linking to public Kaggle Model (Unsloth prize requirement). Pure docs.
- [ ] **J6.** [Kaleel] `docs/12-fine-tuning-plan.md` — beef up 2026-05-14 addendum to make C2A canonical, not just a pivot footnote.
- [ ] **J7.** [Thayyil] `docs/STATUS.md` full sweep — stale GATE 3 references, Kaleel's "Left" → Done, risk register.

#### Track K-Sun — Reproduction validation
- [ ] **K2.** [Thayyil] backup tester pass — confirms a non-author can reproduce from clean state. **If K2 surfaces a code bug, it goes on the post-submission punch list — code is frozen.**

#### Track L — Final writeup pass
- [ ] **L1.** [Ibrahim] Final read-aloud of `WRITEUP.md`. Word count ≤1,500. Tables populated, no `TBD`.
- [ ] **L2.** [Thayyil] Verify Kaggle Writeup / notebook submission requirement (`23-submission-checklist.md` L190). If yes: publish Kaggle Writeup mirroring `WRITEUP.md` (Ibrahim provides final text).
- [ ] **L3.** [Thayyil] Draft Kaggle submission form fields as text file (one-line desc ≤140 chars, track, URLs, prize claims, team names) — Ibrahim approves before save.

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
