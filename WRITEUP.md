# FieldAgent

*Gemma 4 Good Hackathon submission. Repo: [`github.com/ibrahim7860/Gemma-Guardian`](https://github.com/ibrahim7860/Gemma-Guardian). Team: Ibrahim Ahmed, Hazim Kuniyil, Muhammad Kaleelurrahman, Qasim Bhutta, Muhammad Thayyil.*

## 1. Problem

A Red Cross volunteer at the Eaton Fire, January 2025. First the foothills cell tower failed. Then the Skydio relay. By hour two the only working radio was hers, and the AI tools her agency had paid for had become useless rectangles.

Existing AI-powered drone platforms (Skydio, Shield AI, Auterion) require backhaul connectivity for any non-trivial reasoning. Even the most advanced published architecture for AI-driven disaster response, Nguyen, Truong & Le (2026, arXiv:2601.14437), assumes GPT-4.1 over the public internet at the edge ground station: a cloud dependency at the tier where the cloud isn't reachable.

We removed it. Every LLM runs on a single laptop: no internet, no API keys.

## 2. Reference and Our Contribution

Nguyen et al. recommend Architecture B (Edge-Enabled): TinyLLaMA-1.1B onboard each UAV plus GPT-4.1 at a mobile edge ground station. Their Algorithm 1 wraps every LLM call with a deterministic post-condition check and a constraint-conditioned retry, lifting swarm coverage from 70–80% to near-100%.

We adopt Architecture B verbatim (LangGraph orchestrator, five-node agent, Algorithm 1 retry loop). We do not adopt the cloud LLM. Five substitutions:

- **Onboard LLM:** TinyLLaMA-1.1B int4 (text-only) → **Gemma 4 E2B** multimodal. Same model reasons *and* sees.
- **EGS LLM:** GPT-4.1 via OpenAI API → **Gemma 4 E4B** via local Ollama. No API keys, no egress.
- **Cloud dependency:** required at EGS tier → none anywhere; loopback only.
- **Vision pipeline:** separate detection model → absorbed into Gemma 4's multimodal forward pass.
- **Operator interface:** unbuilt in the paper → Flutter dashboard with a multilingual command box that round-trips through Gemma 4 E4B for natural-language → structured-task translation. No translation API.

Same architecture, same validation loop, zero cloud.

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

Each drone runs a five-node LangGraph agent (Perception → Reasoning → Validation → Action → Memory) driven by Gemma 4 E2B. The EGS is a LangGraph coordinator backed by Gemma 4 E4B that allocates survey points, replans on drone failure or link drop, translates operator commands, and dedupes findings. The dashboard is the only component a human touches. What we ship is what would deploy, modulo swapping the simulation tier for hardware drivers.

## 4. Gemma 4 Capabilities — Load-Bearing, Not Decorative

**Vision.** Each drone passes a JPEG from `drones.<id>.camera` directly into Gemma 4 E2B's multimodal forward pass. No YOLO, no LLaVA, no CLIP. The same model that reasons looks; `report_finding.visual_description` is grounded in what it saw.

**Reasoning + function calling.** Every action-driving output is a structured function call validated against a JSON schema. Drones call one of `report_finding`, `mark_explored`, `request_assist`, `return_to_base`, `continue_mission`. The EGS calls `assign_survey_points` or `replan_mission`. Free-form prose is rejected; the validator triggers a corrective re-prompt. Function calling is the agentic backbone, not a postprocessing step.

**Multilingual.** The command box accepts any of Gemma 4's 140+ languages. E4B returns an operator-visible response in their language and the structured swarm task in canonical English. No translation API.

**On-device, offline-falsifiable.** Both Gemma 4 instances run via local Ollama (Metal, CUDA, or CPU fallback). Every network call is one of: Redis (`localhost:6379`), WebSocket bridge (`localhost:9090`), or Ollama (`localhost:11434`). The demo's closing beat cuts to a terminal showing no active network interface alongside `ollama list`.

**Disconnection-tolerant findings.** When a drone crosses out of EGS range, its `LinkStateMonitor` flips a `BufferedPublisher` into standalone mode; every Contract-4 finding is appended to a per-drone JSONL queue. On restore the buffer drains FIFO; the EGS dedupes by `finding_id` against a 5-minute window. A 60-second outage produces zero data loss in the dashboard.

## 5. Validation-and-Retry Loop (Algorithm 1)

Small LLMs hallucinate. In our domain that means a drone reports a "victim" at a GPS coordinate outside its zone, or the EGS assigns the same survey point to two drones. Not catastrophic alone; catastrophic when the swarm trusts peer broadcasts and the operator trusts the swarm.

Algorithm 1 defines four invariants: hard constraints in the prompt, deterministic post-hoc validation, a corrective re-prompt including the failed attempt, and bounded retries with a safe fallback. We implement all four across three loci: per-drone function calls, EGS swarm-level assignment, operator command translation.

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

Demo trigger: the EGS assignment uses an awkward count (25 points / 3 drones / one partially out of range), producing mis-assignment with measurable frequency. The validation loop catches it; corrective prompt fires; second attempt succeeds. Terminal log streams to the dashboard so the audience sees catch and correction in one frame.

Second property: under VRAM pressure when E4B is slow or unreachable, the EGS falls through max-retries to deterministic round-robin instead of raising. The swarm keeps operating even when its LLM hangs.

**Demo disclosure.** For Beat 3c we use a `--inject-overcount-once` flag on the EGS coordinator — base Gemma 4 E4B produced 0 natural `ASSIGNMENT_TOTAL_MISMATCH` triggers across 7 eval runs (M1 + RTX A2000), so the flag deterministically seeds the first attempt's over-count (27 of 25 points). Downstream — rule firing, corrective re-prompt, second-attempt inference, validation pass — runs production code; only the seed is scripted. A full E4B retry-loop replan measures p50 ≈ 30s on RTX 3090 (`measure_e4b_replan_latency.py`, n=10), still exceeding the 8s camera budget, so Beat 3c jump-cuts from "validation rejected" to "second attempt accepted" rather than rolling in real time.

## 6. Engineering Challenges

Three problems shaped the implementation. **(1) Small-LLM hallucination under structured output** — Algorithm 1 with corrective re-prompts (§5). **(2) Base Gemma 4 E2B reads our wow-moment fixture as a damaged building, not a victim** — C2A LoRA fine-tune (§7). **(3) Unsloth's GGUF vision-tower export regresses on `unslothai/unsloth#2290`**, so the C2A adapter loads via PEFT/HF Transformers in-process while base Gemma 4 tags ship via Ollama; two Unsloth↔PEFT shims required (`Gemma4ClippableLinear` unwrap + DoRA magnitude-vector key rename).

## 7. Fine-Tuning

GATE 3 was `report_finding(type='victim')` on a FEMA Hurricane Katrina aerial. Base Gemma 4 E2B reads it as a damaged building, so we trained a vision LoRA for human detection in disaster aerials.

**Dataset.** [C2A](https://www.kaggle.com/datasets/rgbnihal/c2a-dataset) (10,215 UAV images, ~360k human instances across four disaster scenarios). Schema collapsed to binary `{finding_type: "victim" | "none", confidence, visual_evidence}` to match `report_finding`. Held-out eval on AIDER and SARD tests domain transfer.

**Method.** Unsloth LoRA on `unsloth/gemma-4-e2b-it-unsloth-bnb-4bit`, `target_modules="all-linear"`, `finetune_vision_layers=True`, lr 2e-4 cosine. ~120 MB adapter; [public Kaggle Model](https://www.kaggle.com/models/ibrahimahmed7860/gemma4-e2b-victim-vision-lora-c2a) under `Transformers/lora-c2a-bf16`; [training notebook](https://www.kaggle.com/code/ibrahimahmed7860/gemma-4-e2b-victim-vision-lora-c2a-disaster) also public.

**Results (n=400 held-out).** Binary acc 77.25%, victim F1 0.78 (precision 0.79, recall 0.77), parse_rate 1.0. Per-source: C2A 97.2%, AIDER 77.5%, SARD 55%; SARD (held-out cross-domain) honestly bounds the in-domain claim.

**Runtime.** Unsloth's GGUF vision-tower export regresses on [#2290](https://github.com/unslothai/unsloth/issues/2290), so the adapter runs via PEFT/HF Transformers while base Gemma 4 tags ship via Ollama. The adapter runs alongside, not through, Ollama, softening but not invalidating the deployment narrative.

## 8. Honest Limitations

No drone in this project has ever flown. `sim/waypoint_runner.py` interpolates GPS along a YAML track; `sim/frame_server.py` serves pre-recorded JPEGs. The stack above the simulation tier is the same code that would run on a Jetson Orin NX per drone. Mesh is software dropout, not WiFi multipath. We run 2–3 drones, not the paper's 8 or 12; scaling is hardware, not architectural. Resilience events (drone failure, link drop, fire spread) are scripted YAML; the swarm's *response* is genuine. Public-domain FEMA / USFWS aerials serve as the fixture set; none show identifiable human bodies, so the validator-fallback path and mock-Ollama mode jointly guarantee a capture-day artifact when the base model conservatively chooses `continue_mission`. Full accounting in `docs/16-mocks-and-cuts.md`.

## 9. Reproducibility

Hardware floor: any laptop with Python 3.11+, Redis 7+, and Ollama. NVIDIA GPU optional; Apple Silicon via Metal supported with the tuning recipe in `docs/plans/2026-05-12-drone3-reliability-capture.md`. Setup is `uv sync --all-extras` plus `scripts/pull_models.sh` for both Gemma 4 tags. The launcher (`scripts/run_full_demo.sh disaster_zone_v1`) brings up Redis, sim, agents, EGS, bridge, and dashboard in one tmux session. No API keys, no egress, no cloud account. A judge with no internet can run the full system.

## 10. Conclusion

Agentic search-and-rescue can run entirely on-device. The edge-enabled architecture from Nguyen et al. (2026) holds when the cloud LLM is replaced with on-device Gemma 4: validation still catches hallucinations, the swarm still coordinates through dropout, the operator drives the system in their own language. The first hour of every disaster is the hour the cloud is unreachable.

**Cell towers fail first. Brains shouldn't.**
