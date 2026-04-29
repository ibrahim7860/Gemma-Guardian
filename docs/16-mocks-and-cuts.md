# 16 — Mocks and Cuts

## Why This Doc Exists

Hackathon timelines are unforgiving. Every "we'll just add this real quick" is a multi-hour cost that compounds. This doc is the canonical list of what we are NOT building. Anyone tempted to build one of these features must first justify how it doesn't break the timeline.

The principle: **build what makes the demo unforgettable; mock what doesn't move the needle for judges.**

## Things We Mock (And Why That's Fine)

### Wildfire / Zone Segmentation
- **What the paper does:** U-Net on satellite imagery extracts fire boundary
- **What we do:** Predefined polygons hardcoded in the world file or a config file. Optionally a polygon that "expands" on a timer to simulate fire spread.
- **Why it's fine:** The judges care about the LLM agentic behavior, not the segmentation pipeline. State this honestly: "U-Net segmentation is out of scope; the EGS uses pre-defined zones for our prototype." Nobody loses points for skipping a vision task that's not the focus.

### Real Satellite Imagery
- **What the paper does:** Continuous satellite feeds drive zone updates
- **What we do:** A single static aerial screenshot of our Gazebo world used as the EGS's "satellite view"
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
- **What we do:** Gazebo's default simulated GPS at the configured PX4 home
- **Why it's fine:** Sufficient accuracy for the demo. We don't claim production-grade.

### Real Mesh Networking
- **What the paper does:** Self-organizing WiFi mesh
- **What we do:** ROS 2 topics with software dropout based on Euclidean distance
- **Why it's fine:** The behavior is identical from the agent's perspective. We document the abstraction in the writeup.

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
- **Status:** AIM for 3, fall back to 2 if multi-drone Gazebo is unstable
- **Cutoff:** Day 13 (May 11). If 3-drone simulation isn't stable by then, demo with 2.
- **Why:** A polished 2-drone demo beats a flaky 3-drone demo.

### Multilingual Demo
- **Plan:** English + Spanish at minimum, Arabic as stretch
- **Cutoff:** Day 16 (May 14)
- **Why:** Spanish is non-negotiable for the multilingual showcase. Arabic is impressive but English+Spanish is sufficient.

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
- **Cross-platform support.** Ubuntu 22.04 only. Windows / macOS not supported.

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
> - **Mesh networking** is simulated via ROS 2 topics with software-based range dropout (the architecture is designed for WiFi mesh).
> - **Drone hardware** is fully simulated; we deploy on Jetson Orin NX in concept only.
> 
> These simplifications do not affect the validity of the agentic loop, validation patterns, or coordination behaviors demonstrated. They scope the prototype to what is feasible in a 20-day hackathon while preserving the architectural claims."

Judges respect this kind of transparency.

## Cross-References

- Why each mock is acceptable per track: [`02-hackathon-context.md`](02-hackathon-context.md)
- The full feasibility analysis: [`17-feasibility-and-gates.md`](17-feasibility-and-gates.md)
- What the demo shows vs. mocks: [`21-demo-storyboard.md`](21-demo-storyboard.md)
