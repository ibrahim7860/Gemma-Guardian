# 16 — Mocks and Cuts

## Why This Doc Exists

Hackathon timelines are unforgiving. Every "we'll just add this real quick" is a multi-hour cost that compounds. This doc is the canonical list of what we are NOT building. Anyone tempted to build one of these features must first justify how it doesn't break the timeline.

The principle: **build what makes the demo unforgettable; mock what doesn't move the needle for judges.**

## The One Thing We Never Mock

**Gemma 4 itself is never mocked.** No stubbed LLM responses, no canned function-call JSON returned from a fixture, no "if demo mode then return hardcoded plan" branches. Every agentic decision in the system must come from a real Gemma 4 call (E2B onboard, E4B at EGS) running through Ollama on the dev workstation. If Gemma 4 isn't visibly the brain, the project has no submission. This rule overrides everything else in this doc — if a "mock" you're considering would replace a Gemma 4 call, stop and rescope.

The Plan C path in the hallucination demo (below) is the only adjacent edge case: it injects a *validation* failure on a real Gemma 4 output, not a mocked LLM response. The model is still doing the work.

**Disambiguation:** [`sim/manual_pilot.py`](../sim/manual_pilot.py) is a single-drone REPL that lets a developer type findings, broadcasts, and function calls into a live sim by hand. It is a **development aid, not a demo mock** — it never runs during a recorded demo or evaluation. We do not replace Gemma 4's reasoning step with the REPL; the REPL just exists alongside it so Kaleel/Qasim/Thayyil can *see what a drone is actually doing on the wire* while their portions of the stack are still being built. Recommended, not required. See [`docs/15-multi-drone-spawning.md`](15-multi-drone-spawning.md) for the workflow.

**Disambiguation (test-only):** [`scripts/ollama_mock_server.py`](../scripts/ollama_mock_server.py) is a minimal FastAPI shim that mocks Ollama's `/api/chat` endpoint with canned tool-call responses. It is used **only** by [`frontend/ws_bridge/tests/test_e2e_playwright_real_drone_findings.py`](../frontend/ws_bridge/tests/test_e2e_playwright_real_drone_findings.py) (the GATE 2 acceptance e2e) so CI can run the real drone-agent process end-to-end without pulling 7+ GB of Gemma 4 weights into the runner. It is **never** invoked from any production code path, the demo box, or the recorded video. The "Gemma 4 itself is never mocked" rule above applies to runtime decisions; CI test isolation is a different concern. Do not import this module from non-test code; if you need mock LLM responses for a new test, add them here, not inline in the test.

## Things We Mock (And Why That's Fine)

### Wildfire / Zone Segmentation
- **What the paper does:** U-Net on satellite imagery extracts fire boundary
- **What we do:** Predefined polygons hardcoded in the world file or a config file. Optionally a polygon that "expands" on a timer to simulate fire spread.
- **Why it's fine:** The judges care about the LLM agentic behavior, not the segmentation pipeline. State this honestly: "U-Net segmentation is out of scope; the EGS uses pre-defined zones for our prototype." Nobody loses points for skipping a vision task that's not the focus.

### Real Satellite Imagery
- **What the paper does:** Continuous satellite feeds drive zone updates
- **What we do:** A single static aerial image (one of the xBD base frames or a public-domain satellite photograph) used as the EGS's "satellite view"
- **Why it's fine:** Same reasoning as segmentation. We're not pretending to have satellite access; we're showing the architecture works.

### Real Fire Spread Physics
- **What the paper does:** Implicitly, the satellite shows fire growing
- **What we do:** A polygon that scripted-expands on a timer (every 60 seconds, polygon grows by 10%). Triggers replanning.
- **Why it's fine:** The visual appearance of "the situation is changing" matters for the demo. The physics doesn't.

### Drone Hardware (Jetson Orin)
- **What the paper does:** Real Jetson Orin NX onboard each UAV
- **What we do:** All inference runs on the dev workstation, time-shared across simulated drones via a single Ollama instance
- **Why it's fine:** Pure simulation. Stated honestly in the writeup. The architecture is designed for Jetson; future work would deploy.

### Real GPS / Sensor Fusion
- **What the paper does:** Real RTK-GPS, IMU, etc.
- **What we do:** Scripted lat/lon/alt positions interpolated from waypoints in the scenario YAML, published by `sim/waypoint_runner.py`
- **Why it's fine:** Sufficient accuracy for the demo. We don't claim production-grade.

### Real Mesh Networking
- **What the paper does:** Self-organizing WiFi mesh
- **What we do:** Redis pub/sub with software dropout based on Euclidean distance. `agents/mesh_simulator/main.py` subscribes to `swarm.broadcasts.*`, filters each message against live drone positions, and republishes accepted messages on `swarm.<receiver_id>.visible_to.<receiver_id>`. See [`20-integration-contracts.md`](20-integration-contracts.md) Contract 9.
- **Why it's fine:** The behavior is identical from the agent's perspective. We document the abstraction in the writeup.

### Drone Flight Dynamics
- **What the paper does:** PX4 SITL flight controller with dynamics simulation, control loops, and sensor fusion
- **What we do:** Scripted waypoint tracks at configurable speed. The drone "appears" at the next waypoint after `t = distance / speed`. No dynamics, no control loops, no sensor fusion.
- **Why it's fine:** Agentic decisions are independent of flight physics. The agent cares about position and camera frames, not the underlying flight controller state.

### 3D Rendering / Synthetic Camera
- **What the paper does (and what we originally planned):** Gazebo renders camera frames from a 3D world in real time
- **What we do:** Pre-recorded xBD post-disaster crops and public-domain aerial/satellite photographs, served from `sim/fixtures/frames/` by `sim/frame_server.py` at 1 Hz
- **Why it's fine:** Real aerial disaster imagery is more visually compelling than Gazebo's default rendering, and it is the exact same distribution the vision fine-tuning pipeline trains on — eliminating sim-to-real gap for the vision task entirely.

### Real Drone Failures
- **What the paper does:** Actual hardware failures, sensor faults
- **What we do:** Scripted "drone N simulates GPS failure at time T" events for the demo
- **Why it's fine:** The agentic response is what matters. We're showing the swarm reacts correctly, not validating physical hardware reliability.

### Multi-Swarm Coordination
- **What the paper hints at:** Architecture C supports cross-swarm coordination via cloud
- **What we do:** Single swarm only. Architecture C is out of scope.
- **Why it's fine:** The paper itself recommends Architecture B for SAR. We focus where the value is.

### Forensic Logging / Regulatory Compliance
- **What the paper mentions:** EGS aggregates for forensic analysis
- **What we do:** Basic logging to disk; nothing audit-grade
- **Why it's fine:** Out of scope for a research prototype.

## Things We Mock Conditionally

### xBD Vision Fine-Tuning
- **Status:** START as a real workstream, gate at Day 10 (May 8)
- **If GO:** Real LoRA adapter trained, integrated, evaluated
- **If NO-GO:** Drop entirely, base Gemma 4 + prompts only
- **Why this approach:** Fine-tuning is the credibility play AND the highest single-person risk. We isolate it; we either ship it real or skip it cleanly. We do NOT half-ship.

See [`12-fine-tuning-plan.md`](12-fine-tuning-plan.md).

### Three Drones vs Two
- **Status:** AIM for 3, fall back to 2 if multi-drone Redis coordination is unstable
- **Cutoff:** Day 13 (May 15). If 3-drone simulation isn't stable by then, demo with 2.
- **Why:** A polished 2-drone demo beats a flaky 3-drone demo.

### Multilingual Demo
- **Plan:** English + Spanish at minimum, Arabic as stretch
- **Cutoff:** Day 16 (May 14)
- **Why:** Spanish is non-negotiable for the multilingual showcase. Arabic is impressive but English+Spanish is sufficient.

### Bridge Cutover Hybrid Fakes (egs.state, drones.<id>.findings)
- **Status:** ON during the hybrid window — until Qasim's EGS aligns its `zone_polygon` to the active scenario YAML and Kaleel's drone agent publishes findings to Redis instead of stdout. Both expected before Gate 4.
- **Plan:** [`scripts/run_hybrid_demo.sh`](../scripts/run_hybrid_demo.sh) launches the real sim for `drones.<id>.state` (Hazim) and uses [`scripts/dev_fake_producers.py`](../scripts/dev_fake_producers.py) `--emit=egs` and `--emit=findings --drone-id <id>` to fill the remaining channels with schema-valid fixture-derived payloads.
- **Cutoff:** Pass `--no-fake-egs` to drop the EGS fake the day Qasim ships; pass `--no-fake-findings` the day Kaleel ships. Defaults stay ON so today's behaviour is unchanged. No source edits required.
- **Why it's fine:** The bridge and dashboard are exercised against contract-valid payloads on the same channels they'll see in production. The real sim already drives drone state, so the dashboard renders live drone position, battery, and waypoint progress. Operator approval flow + `egs.state` shape are the only two paths still touching fixture data; both flip to real with one CLI flag.
- **Honesty test:** When recording the demo video, declare hybrid mode in the writeup so a judge knows what's real and what's fixture-derived. The migration log (this entry + `sim/ROADMAP.md`) tracks when each piece flips.

### Hallucination Catch-and-Correct Demo Moment
- **Plan A (best):** Engineer the scenario so Gemma 4 reliably hallucinates, validation catches it on camera
- **Plan B (backup):** Adversarial replanning scenario forces the catch
- **Plan C (last resort):** Deterministic mock failure injected on first attempt of one specific call
- **Why a fallback exists:** The catch-and-correct is the technical innovation moment. We must have one in the video. If the real model behaves too well during the demo run, we use Plan C and document it transparently.

See [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md).

## Things We Definitively Do NOT Build

These are tempting but cut hard:

- **A backend database.** State lives in memory, persisted to disk every 10 seconds.
- **Authentication / user management.** Single operator, no auth.
- **A mobile app.** Flutter web only.
- **Production deployment infrastructure.** Local dev only. Reproduction is via the documented setup, not a prebuilt VM.
- **Voice operator commands.** Text only. (Stretch only if everything else is done.)
- **Drone camera live feed in dashboard.** Map view only. (Stretch.)
- **Mission timeline replay.** Out of scope.

## Decision Heuristic

When tempted to build something not in the doc:

1. Does it appear in the demo video? If no → skip.
2. Is it required for the architecture argument? If no → skip.
3. Is it required for one of the five Gemma 4 capability showcases? If no → skip.
4. Can it be added in <4 hours? If no → skip.
5. If yes to all four → ask the team in standup before adding.

## Honest Disclosure in Writeup

The writeup explicitly enumerates every mock with the rationale. This is a credibility move:

> "FieldAgent is a research prototype demonstrating the agentic LLM architecture for disaster response. Several components are deliberately simplified for the prototype:
> 
> - **Zone segmentation** is replaced with predefined polygons (the original architecture uses U-Net on satellite imagery).
> - **Mesh networking** is simulated via Redis pub/sub with software-based range dropout (`agents/mesh_simulator/main.py`); the architecture is designed for WiFi mesh.
> - **Drone flight dynamics** are replaced with scripted waypoint tracks; no flight controller or sensor fusion runs. The drone advances from waypoint to waypoint at a fixed configured speed.
> - **Camera frames** are pre-recorded xBD post-disaster crops and public-domain aerial imagery served by `sim/frame_server.py`; no real-time 3D rendering is performed.
> - **Drone hardware** is fully simulated; we deploy on Jetson Orin NX in concept only.
> 
> These simplifications do not affect the validity of the agentic loop, validation patterns, or coordination behaviors demonstrated. They scope the prototype to what is feasible in a 20-day hackathon while preserving the architectural claims. The software-only simulation stack runs on any modern laptop (macOS, Linux, Windows) with Python 3.11+, Redis, and Ollama."

Judges respect this kind of transparency.

## Cross-References

- Why each mock is acceptable per track: [`02-hackathon-context.md`](02-hackathon-context.md)
- The full feasibility analysis: [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md)
- What the demo shows vs. mocks: [`21-demo-storyboard.md`](21-demo-storyboard.md)
