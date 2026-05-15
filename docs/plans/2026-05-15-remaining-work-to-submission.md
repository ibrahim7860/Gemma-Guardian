# Remaining Work to Submission — Day 13 → Day 16

**Drafted:** 2026-05-15 (Thu, Day 13, GATE 4 day)
**Submission deadline:** Sun May 18, 23:59 UTC (target submit 18:00 UTC = 6 PM CDT)
**Time remaining:** ~3.5 days
**Owner of this doc:** Ibrahim — strike items as they ship, log surprises inline.

Sources cross-referenced: `TODOS.md`, `docs/STATUS.md`, `docs/17-feasibility-and-gates.md`, `docs/19-day-by-day-plan.md`, `docs/21-demo-storyboard.md`, `docs/22-writeup-draft.md`, `WRITEUP.md`, `README.md`, `docs/23-submission-checklist.md`, `docs/12-fine-tuning-plan.md`, and 13 open files under `docs/plans/`.

---

## Three things to flag up front

- [x] **GATE 4 wow-moment Phase 5 is on Qasim's plate** — reassigned 2026-05-12 (`TODOS.md` L25, `STATUS.md` L48) because M1 can't carry E4B at usable speed.
- [x] **Kaggle Model is now public** with a published variation (v3 `Transformers/lora-c2a-bf16`). Notebook also public.
- [ ] **`WRITEUP.md` §6 still describes the OLD xBD path** and references empty `ml/adapters/`. Needs full rewrite to C2A victim-detection narrative + SUBMIT-DAY HTML comment at line 80 stripped.

---

## TODAY — Thursday May 15 (Day 13, GATE 4 day)

### Track A — Ibrahim — Kaggle artifact + handoff (~1-2 hr)
- [x] **A1.** Upload C2A adapter as Kaggle Model variation (`Transformers/lora-c2a-bf16/3`)
- [x] **A2.** Flip Model visibility to Public
- [x] **A3.** Flip Notebook visibility to Public
- [x] **A4.** Verify C2A dataset citation visible on the public notebook (`rgbnihal/c2a-dataset`)
- [x] **A5.** Send Qasim the handoff message (drafted in conversation — buckets 1-5)
- [x] **A6.** Update `docs/STATUS.md` L11 + Kaleel's section L34 + Risk Register row to reflect GATE 3 GO + eval numbers

### Track B — All hands — GATE 4 vote (~15 min)
- [ ] **B1.** Run GATE 4 evaluation per `docs/17-feasibility-and-gates.md` L105-130 (5 multi-drone criteria)
- [ ] **B2.** Record PASS/FAIL decision in `docs/decisions.md` (per L178-185)
- [ ] **B3.** If FAIL → drop to 2 drones, update storyboard

### Track C — Qasim — CUDA-box work (concurrent, 4-6 hr)
- [ ] **C1.** GATE 3 acceptance test: `qasim_inference.py` on `placeholder_victim_01.jpg` 3× — need 3/3 `finding_type: victim` (`TODOS.md` L29-33)
- [ ] **C2.** Route (a) vs (b) decision — 30-min Unsloth #2290 probe, max 1 hr before falling back to (b)
- [ ] **C3.** Wire C2A adapter into drone agent runtime per chosen route (`TODOS.md` L35-39)
  - [ ] Default-to-base fallback on adapter-load failure
  - [ ] Unit tests for loader + parser
  - [ ] Re-run GATE 3 acceptance test **through integrated drone agent** (not standalone script)
  - [ ] Open PR, tag Ibrahim
- [ ] **C4.** GATE 4 wow-moment Phase 5: `ml/evaluation/eval_wow_moment_trigger.py --runs 20` — paste results to `docs/plans/2026-05-12-gate4-wow-moment.md`
- [ ] **C5.** `scripts/measure_e4b_replan_latency.py` — paste p50/p95
- [ ] **C6.** If C4 reports <12/20 triggers → ship `--inject-overcount-once` flag on `agents/egs_agent/main.py` + writeup §6.5 disclosure
- [ ] **C7.** [Optional/skippable] `command_translator.py:70` 180s timeout hoist (`TODOS.md` L41-47)

### Track D — Ibrahim — Background retrain (own wall time)
- [x] **D1.** ~~Let v8 smoke test finish~~ → Ran v10 smoke (varied-labels fix, 30 steps, ~15 min, green: loss 3.456→0.382). Kicked off v11 full run (300 steps, ~49 min on T4). Eval: 77.25% binary / 0.78 F1 / 55% SARD (+13pp vs v9). Published as Kaggle Model `lora-c2a-bf16/3` PUBLIC.
- [x] **D2.** Schema confirmed stable: `to_chat_example` at `kaggle_work_c2a/gemma4-victim-vision-lora.py:262-278` emits `{finding_type, confidence, visual_evidence}`. v11 `parse_rate_ok: 1.0` on n=400 eval. Adapter swap is version-agnostic across v9/v10/v11.

---

## DAY 14 — Friday May 16 (Demo Capture Day)

### Track E — Ibrahim — Demo capture (~4 hr afternoon)
- [ ] **E1.** Beat 5 capture: `scripts/run_beat5_capture.sh` repeatedly + `scripts/check_beat5.py` A1-A6 PASS per take. ≥2-4 backup takes.
- [ ] **E2.** Wow-moment capture: `scripts/check_wow_moment.sh` before each take; if live trigger fails twice → use deterministic synth-WS PNGs (`docs_assets/dashboard-validation-wow-{failed,passed}.png`)
- [ ] **E3.** Beats 1-4 captures (Beat 1 NASA SVS Eaton Fire / Beat 2 paper + arch diagram / Beat 4 multilingual + EGS sever)
- [ ] **E4.** Backup raw `.mov`/`.mp4` files + `$DEMO_DIR` artifacts to second machine

### Track F — Qasim — Validation continuation (~2-3 hr)
- [ ] **F1.** drone3 reliability on integrated path: `scripts/run_drone3_reliability.sh` 3× — need 3/3 hits
- [ ] **F2.** Integration PR merged (Ibrahim reviews + merges)
- [ ] **F3.** If v8/v9 retrain landed overnight and materially better: swap adapter, rerun C1 + F1. If marginal: ship v3 — don't risk Lock Day.

### Track G — Ibrahim — Writeup major rewrite (~3-4 hr evening)
- [ ] **G1.** Rewrite `WRITEUP.md` §6 Fine-Tuning — replace xBD building-damage narrative with C2A victim detection. Real numbers: binary acc 76.75%, parse_rate 1.0, per-source C2A 99% / AIDER 82% / SARD 42%, victim F1 0.76
- [ ] **G2.** Strip SUBMIT-DAY HTML comment block at `WRITEUP.md:80`
- [ ] **G3.** Word count check (≤1,500; current 1,460 — tight). Spell-check, Grammarly, read aloud for flow
- [ ] **G4.** If route (b) shipped (no Ollama claim) → drop Ollama special-prize line from writeup
- [ ] **G5.** Update `docs/22-writeup-draft.md` §7 — collapse to GO variant, drop §7.B + conditional banner, re-title to `## 7. Fine-Tuning`

### Track H — All hands — Friday dress rehearsal
- [ ] **H1.** Full demo run, identify everything still rough (`19-day-by-day-plan.md` L132)

---

## DAY 15 — Saturday May 17 (LOCK DAY — no new features after EOD)

### Track I — Ibrahim — Video edit to picture-lock (~6-8 hr)
- [ ] **I1.** Edit in DaVinci Resolve. 1:45 target / 3:00 Kaggle cap. Pacing: B1 0:10 + B2 0:15 + B3 0:40 + B4 0:15 + B5 0:25
- [ ] **I2.** Captions throughout + "Software simulation" disclosure caption
- [ ] **I3.** Verify mandatory visual elements (`21-demo-storyboard.md` L217-228):
  - [ ] Real sim footage
  - [ ] Dashboard rendering live state
  - [ ] Gemma 4's structured output visible
  - [ ] Validation correction event visible
  - [ ] Multilingual command moment
  - [ ] Offline-proof terminal (`ollama list` + WAN DOWN)
  - [ ] Reference paper citation on screen
  - [ ] GitHub URL at end
- [ ] **I4.** Export 1080p MP4 H.264. Forbidden-elements check (no fake screens, no unmeasured perf claims)
- [ ] **I5.** Upload to YouTube unlisted. Verify publicly viewable without login (incognito test)
- [ ] **I6.** Backup upload to Vimeo or second YouTube account

### Track J — All hands — Repo cleanup (parallel, ~2-4 hr each)
- [ ] **J1.** `README.md` final pass: add video URL, Kaggle Model URL, finalize Quick Start
- [ ] **J2.** Either populate `ml/adapters/` OR `ml/README.md` links to public Kaggle Model (Unsloth prize requirement)
- [ ] **J3.** `scripts/pull_models.sh` works for both Gemma 4 tags + adapter (Ollama prize requirement IF route (a) shipped) — Qasim
- [ ] **J4.** `scripts/setup.sh` + `scripts/run_full_demo.sh` end-to-end works — Hazim
- [ ] **J5.** Code-quality sweep: no commented-out blocks, no `print` debug, no hardcoded home paths, no secrets, Black-formatted Python, dartfmt Flutter — all
- [ ] **J6.** `docs/12-fine-tuning-plan.md` — beef up 2026-05-14 addendum to make C2A canonical, not just a pivot footnote
- [ ] **J7.** `docs/STATUS.md` full sweep — stale GATE 3 references, Kaleel's "Left" → Done, risk register

### Track K — Reproduction cold-run
- [ ] **K1.** Hazim cold-tests reproduction docs from fresh Linux/WSL2 machine per `docs/sim-reproduction.md`
- [ ] **K2.** Thayyil backup tester pass
- [ ] **K3.** Fix any rough edges surfaced

### Track L — Final writeup pass
- [ ] **L1.** Final read-aloud of `WRITEUP.md`. Word count ≤1,500. Tables populated, no `TBD`.
- [ ] **L2.** Verify Kaggle Writeup / notebook submission requirement (`23-submission-checklist.md` L190). If yes: publish Kaggle Writeup mirroring `WRITEUP.md`
- [ ] **L3.** Draft Kaggle submission form fields as text file (one-line desc ≤140 chars, track, URLs, prize claims, team names)

---

## DAY 16 — Sunday May 18 (SUBMISSION DAY, GATE 5)

### Morning (9 AM CDT)
- [ ] **M1.** Verify all video + repo + Kaggle Model links work from incognito browsers
- [ ] **M2.** Read writeup one more time
- [ ] **M3.** Commit anything outstanding to main
- [ ] **M4.** Tag release `v1.0-submission`
- [ ] **M5.** Verify backup of repo + assets on ≥2 separate machines

### Afternoon (1-4 PM CDT)
- [ ] **N1.** Fill out Kaggle submission form (`23-submission-checklist.md` L175-190)
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
- [ ] **N2.** Second team member double-checks every field
- [ ] **N3.** **Submit by 18:00 UTC = 6 PM CDT**
- [ ] **N4.** Verify submission appears on Kaggle
- [ ] **N5.** Save submission confirmation email
- [ ] **N6.** Make repo public if private
- [ ] **N7.** Post confirmation to team channel

### Evening (post-submission)
- [ ] **O1.** Celebrate
- [ ] **O2.** Hazim/Thayyil: backup repo to private storage in case Kaggle/GitHub goes down

### Within 1 week (deferred)
- [ ] **P1.** Write `docs/RETRO.md` — what worked, what didn't

---

## Critical Path (the chain that can ship-block)

```
TODAY:
  A1-A2 Kaggle public ──► A5 handoff sent ──► Qasim starts
                                              │
                                              ├─► C1 GATE 3 acceptance
                                              ├─► C2-C3 integration
                                              ├─► C4-C5 wow-moment Phase 5
                                              └─► (concurrent)

DAY 14 (Fri):
  F1 drone3 reliability 3× on integrated path
  F2 PR merged
  E1-E3 demo captures (Ibrahim)
  G1-G5 writeup rewrite (Ibrahim)

DAY 15 (Sat) — LOCK:
  I1-I6 video edit + YouTube upload
  K1-K3 reproduction cold-run
  L1-L3 writeup final + Kaggle form draft
  J1-J7 repo cleanup + STATUS.md

DAY 16 (Sun) — SUBMIT:
  M1-M5 morning verification
  N1-N7 Kaggle submission by 18:00 UTC
```

---

## Risk Watch

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Qasim's CUDA box has scheduling conflicts | Medium | High | Pre-book CUDA box for Day 13-15 |
| Route (a) Ollama dead (Unsloth #2290) | Known | Medium | Route (b) PEFT/HF; document deviation |
| GATE 3 acceptance fails through integrated path | Low | High | Default-to-base fallback toggle |
| Wow-moment Phase 5 eval <12/20 triggers | Realized once on M1 | Medium | `--inject-overcount-once` + §6.5 disclosure |
| v8/v9 retrain doesn't finish in time | Medium | None | Ship v3, retrain is optional |
| Lock Day breaches | High historically | Catastrophic | Hard freeze rule per `17-feasibility-and-gates.md` L132-145 |
| YouTube upload flagged | Low | High | Backup upload to Vimeo |
| Hazim's cold-run surfaces broken setup script | Medium | Medium | Day 15 buffer for same-day fix |

---

## Irreducible Minimums (per `17-feasibility-and-gates.md` L187-197)

Even under extreme pressure, these do NOT get cut:
- Real Gemma 4 inference doing real work (no mocking the LLM itself)
- The validation-and-retry loop (visible in the demo)
- The offline / on-device claim demonstrated (terminal showing no internet)
- ≥1 working drone agent loop on Redis with real Gemma 4 driving decisions
- A submission by May 18, 23:59 UTC

Everything else is negotiable.
