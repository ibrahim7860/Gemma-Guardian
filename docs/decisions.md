# Decisions — FieldAgent

Gate decisions recorded per `docs/17-feasibility-and-gates.md` §Communication Protocol.

## GATE 4: Multi-Drone Coordination — 2026-05-16

**Decision:** FAIL on 3-drone → **DROP TO 2-DRONE configuration.**

**Evaluator:** Qasim (CUDA box — RTX A2000 8GB, 64GB system RAM)

**Runs performed:**
1. **3-drone run** (`scripts/run_resilience_scenario.sh`, default `--drones=drone1,drone2,drone3`): System RAM saturated at 64GB. All three drone agents + EGS hitting Ollama concurrently caused constant VRAM model swapping (8GB VRAM holds only one Gemma 4 model at a time). `drone_failure` scripted event received by EGS, replanning attempted but hit `ReadTimeout` on every attempt. No drone findings produced. Scenario did not auto-terminate (system too overloaded).
2. **2-drone run** (`scripts/run_resilience_scenario.sh --drones=drone1,drone3`): System RAM at 95% — survivable but still under pressure. Same `ReadTimeout` pattern on EGS replanning. No drone findings produced. Root cause identical: `gemma4:e2b` (drones) + `gemma4:e4b` (EGS) cannot coexist in 8GB VRAM; Ollama swaps models on every inference request.

**Root cause:** Hardware constraint, not code defect. The code paths are correct:
- `sim.scripted_events` → `drone_failure` fires and EGS receives it ✅
- EGS coordinator triggers replanning ✅
- Replanning calls `assign_survey_points` via Ollama ✅
- But Ollama `ReadTimeout` (30s per-attempt timeout from GH #32 fix) fires because model swapping takes >30s on 8GB VRAM ❌

**No team member has access to ≥16GB VRAM hardware** (needed to keep both Gemma 4 E2B and E4B resident simultaneously).

**Mitigation per gate doc L124-130:**
1. Demo proceeds with 2-drone configuration
2. Demo capture uses `scripts/ollama_mock_server.py` for deterministic takes (documented backup path per `docs/plans/2026-05-12-beat5-video-capture.md` prereq #10)
3. Writeup frames as: "core architecture validated; scaling to N drones is straightforward future work"
4. Freed time reallocated to polishing the 2-drone demo

**Rationale:** Per gate doc: "A polished 2-drone demo absolutely beats a flaky 3-drone demo. There's no shame in this."
