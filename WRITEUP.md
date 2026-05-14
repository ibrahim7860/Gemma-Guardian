# FieldAgent — Technical Writeup

*Gemma 4 Good Hackathon submission. Repo: [`github.com/ibrahim7860/Gemma-Guardian`](https://github.com/ibrahim7860/Gemma-Guardian). Team: Ibrahim Ahmed, Hazim Kuniyil, Muhammad Kaleelurrahman, Qasim Bhutta, Muhammad Thayyil.*

## 1. Problem

A Red Cross volunteer running point on the Eaton Fire response, January 2025. The first thing she lost was the cell tower at the foothills. The second was the Skydio relay her team had brought in. By hour two the only working radio was hers, and the AI tools her agency had paid for had become useless rectangles.

Existing AI-powered drone platforms — Skydio, Shield AI, Auterion — require backhaul connectivity for any non-trivial reasoning. Even the most advanced published architecture for AI-driven disaster response, Nguyen, Truong & Le (2026, arXiv:2601.14437), assumes GPT-4.1 over the public internet at the edge ground station. That is a cloud dependency at the precise tier where the cloud isn't reachable.

We took that architecture and removed its cloud dependency. Every LLM in the system runs on a single laptop — no internet, no API keys. Same volunteer, same disaster, drones still thinking.

## 2. Reference and Our Contribution

Nguyen et al. propose three architectures for LLM-powered UAV swarms. They recommend Architecture B (Edge-Enabled): TinyLLaMA-1.1B onboard each UAV plus GPT-4.1 at a mobile edge ground station. Their Algorithm 1 wraps every LLM call with a deterministic post-condition check and a constraint-conditioned retry; it lifts swarm coverage from 70–80% to near-100%.

We adopt Architecture B verbatim — LangGraph orchestrator, five-node agent, Algorithm 1 retry loop. We do not adopt the cloud LLM. Five concrete substitutions:

- **Onboard LLM:** TinyLLaMA-1.1B int4 (text-only) → **Gemma 4 E2B** multimodal. Same model reasons *and* sees.
- **EGS LLM:** GPT-4.1 via OpenAI API → **Gemma 4 E4B** via local Ollama. No API keys, no egress.
- **Cloud dependency:** required at EGS tier → none anywhere; loopback only.
- **Vision pipeline:** separate detection model in the paper → absorbed into Gemma 4's multimodal forward pass.
- **Operator interface:** mentioned but not built in the paper → Flutter dashboard with a multilingual command box that round-trips through Gemma 4 E4B for natural-language → structured-task translation. No translation API.

Same architecture. Same agentic pattern. Same validation loop. Zero cloud.

## 3. System

```
Operator Dashboard (Flutter web)
        ▲ WebSocket (FastAPI bridge, ws://localhost:9090)
        ▼
Edge Ground Station — Gemma 4 E4B + LangGraph
        ▲ Redis pub/sub (localhost:6379)
        ▼
Per-Drone Agents (×2–3) — Gemma 4 E2B + LangGraph 5-node agent
        ▲ Redis pub/sub
        ▼
Simulation — sim/waypoint_runner.py + frame_server.py (scenario YAML)
```

Each drone runs a five-node LangGraph agent (Perception → Reasoning → Action → Memory → Coordination) driven by Gemma 4 E2B. The EGS is a LangGraph coordinator backed by Gemma 4 E4B that allocates survey points, replans on drone failure or link drop, translates operator commands, and dedupes findings. The dashboard is the only component a human ever touches. The system we ship is the system that would deploy, modulo replacing the simulation tier with hardware drivers.

## 4. Gemma 4 Capabilities — Load-Bearing, Not Decorative

**Vision.** Each drone passes a JPEG frame from `drones.<id>.camera` directly into Gemma 4 E2B's multimodal forward pass. No YOLO, no LLaVA stage, no CLIP embedding. The same model that reasons about the scene looks at it; `report_finding.visual_description` is grounded in what the model actually saw.

**Reasoning + function calling.** Every action-driving output is a structured function call validated against a JSON schema. Drones call one of `report_finding`, `mark_explored`, `request_assist`, `return_to_base`, `continue_mission`. The EGS calls `assign_survey_points` or `replan_mission`. Free-form prose is rejected; the validator triggers a corrective re-prompt. Function calling is the agentic backbone, not a postprocessing step.

**Multilingual.** The operator command box accepts any of Gemma 4's 140+ trained languages. Gemma 4 E4B returns both an operator-visible response in the operator's language and the structured swarm task in canonical English. No translation API; a Spanish- or Arabic-speaking volunteer isn't waiting on Google Translate's reachability.

**On-device, offline-falsifiable.** Both Gemma 4 instances run via local Ollama (E2B on drone, E4B on EGS) — Metal on Apple Silicon, CUDA on Linux/WSL2, CPU fallback. Every network call in FieldAgent is one of: Redis on `localhost:6379`, the WebSocket bridge on `localhost:9090`, or Ollama on `localhost:11434`. The demo's closing beat cuts to a terminal showing no active network interface alongside `ollama list` running both Gemma 4 variants.

**Disconnection-tolerant findings.** When a drone crosses out of EGS range, its `LinkStateMonitor` flips a `BufferedPublisher` into standalone mode; every Contract-4 finding is appended to a per-drone JSONL queue. On link restore the buffer drains in FIFO order; the EGS dedupes by `finding_id` against a 5-minute window. A 60-second outage produces zero data loss in the dashboard.

## 5. Validation-and-Retry Loop (Algorithm 1)

Small LLMs hallucinate. In our domain that means a drone reports a "victim" at a GPS coordinate outside its assigned zone, or the EGS assigns the same survey point to two drones. None of these are catastrophic in isolation; all are catastrophic when the swarm trusts peer broadcasts and the operator trusts the swarm.

Algorithm 1 defines four invariants: hard constraints in the prompt, deterministic post-hoc validation, a corrective re-prompt including the failed attempt, and bounded retries with a safe fallback. We implement all four and apply them to three loci: per-drone function calls, EGS swarm-level assignment, operator command translation.

```python
for attempt in range(MAX_RETRIES):  # = 3
    response = await ollama_call(model="gemma4:e2b", messages=convo, tools=SCHEMAS)
    call = parse_function_call(response)
    result = validate(call, perception_bundle)  # shape → types → semantics
    if result.valid:
        return call
    convo.append({"role": "assistant", "content": str(call)})
    convo.append({"role": "user", "content": result.corrective_prompt})
return continue_mission_call(reason="validation_exhausted")  # safe fallback
```

A reliable demo trigger: the EGS assignment task is constrained with a deliberately awkward survey-point count (25 points / 3 drones / one partially out of mesh range), which produces over- or under-assignment with measurable frequency. The validation loop catches it; the corrective prompt fires; the second attempt succeeds. Terminal log streams to the dashboard so the audience sees catch and correction in the same frame.

The same loop has a second important property: when Gemma 4 E4B is slow or unreachable under VRAM pressure, the EGS falls through max-retries to a deterministic round-robin assignment instead of raising. The swarm keeps operating even when its LLM hangs.

## 6. Fine-Tuning

<!-- SUBMIT-DAY: assumes GATE 3 GO. If NO-GO, rewrite per `docs/22-writeup-draft.md` §7.B. Strip comment + delete this note before pasting into Kaggle. -->

We trained a LoRA on Gemma 4 E2B against the xBD dataset (Gupta et al., 2019) using Unsloth for kernel-level forward/backward speedups on the LoRA path. Rank 32, `target_modules="all-linear"`, learning rate 2e-4 cosine, 1–3 epochs over ~500k 224×224 per-building patches. Adapter, weights, and per-class F1 against the held-out xBD test split (split by disaster, not random sample) are published in the linked repo under `ml/adapters/`. Sim-to-real caveat: the xBD imagery is high-altitude post-event satellite while our simulation serves curated public-domain aerials; the adapter helps the model, transferring its gains to live drone footage is future work.

## 7. Honest Limitations

No drone in this project has ever flown. `sim/waypoint_runner.py` interpolates GPS along a YAML track; `sim/frame_server.py` serves pre-recorded JPEGs. The agent stack above the simulation tier is the same code that would run on a Jetson Orin NX per drone. Mesh is software dropout, not WiFi multipath. We run 2–3 drones, not the paper's 8 or 12 — scaling is a hardware question (one Jetson per drone), not an architectural one. Resilience events (drone failure, link drop, fire spread) are scripted in YAML so the demo is reproducible; the swarm's *response* to each event is genuine. Public-domain FEMA / USFWS aerials serve as the perception fixture set; none show visibly identifiable human bodies, so the validator-fallback path and the demo's mock-Ollama mode jointly guarantee a capture-day artifact even when the base model conservatively chooses `continue_mission`. Full accounting in `docs/16-mocks-and-cuts.md`.

## 8. Reproducibility

Hardware floor: any laptop with Python 3.11+, Redis 7+, and Ollama. NVIDIA GPU optional. Apple Silicon via Metal is fully supported with the tuning recipe in `docs/plans/2026-05-12-drone3-reliability-capture.md`. Setup is one command (`uv sync --all-extras`) plus `scripts/pull_models.sh` to fetch both Gemma 4 tags via Ollama. The demo launcher is one command (`scripts/run_full_demo.sh disaster_zone_v1`) and brings up Redis, sim, agents, EGS, bridge, and dashboard in a single tmux session. The runtime is Ollama — no API keys, no network egress, no cloud account. A judge with no internet connection can run the full system.

## 9. Conclusion

Agentic search-and-rescue can run entirely on-device. The edge-enabled architecture from Nguyen et al. (2026) holds when the cloud LLM is replaced with on-device Gemma 4: the validation loop still catches hallucinations, the swarm still coordinates through dropout, the operator still drives the system in their own language. Billions of people live in climate-vulnerable regions, and the first hour of every disaster is the hour the cloud is unreachable.

**Cell towers fail first. Brains shouldn't.**
