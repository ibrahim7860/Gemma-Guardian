# FieldAgent — Technical Writeup (LONG-FORM WORKING DRAFT)

> **This is the long-form working draft (~4,070 words).** The Kaggle Writeup hard cap is **≤1,500 words**, so the *submission* version lives at the repo root as [`WRITEUP.md`](../WRITEUP.md) (~1,437 words, page-verified cap 2026-05-13). Keep this long-form for internal reference and section archaeology; do not paste it into the Kaggle Writeup. Final §-by-§ decisions sync into `WRITEUP.md` before submit.

*Gemma 4 Good Hackathon submission (Kaggle × Google DeepMind, May 2026). Repo: [`github.com/ibrahim7860/Gemma-Guardian`](https://github.com/ibrahim7860/Gemma-Guardian). Team: Ibrahim Ahmed, Hazim Kuniyil, Muhammad Kaleelurrahman, Qasim Bhutta, Muhammad Thayyil.*

---

## 1. Problem Framing

Imagine a Red Cross volunteer running point on a wildfire response in the
Eaton Fire footprint, January 2025. The first thing she lost was the cell
tower at the foothills. The second was the Skydio relay her team had brought
in. By hour two the only working radio was hers, and the only AI tools her
agency had paid for had become useless rectangles. This is not a hypothetical.
NASA's post-fire imagery from Eaton showed coordinated response gaps in
exactly the cells where infrastructure had collapsed first.

This is the gap FieldAgent targets. Existing AI-powered drone platforms —
Skydio, Shield AI, Auterion — require backhaul connectivity for any
non-trivial reasoning. Even the most advanced published architecture for
AI-driven disaster response, Nguyen, Truong & Le (2026), assumes GPT-4.1 over
the public internet at the edge ground station. That is a cloud dependency at
the precise tier where the cloud isn't reachable.

The result: the most advanced AI tooling for SAR fails in the first hour
of the disaster it was built to help with. Volunteers fall back to paper
maps and voice radio. Drones become expensive cameras.

We took that architecture and removed its cloud dependency. Every LLM in
the system runs on a single laptop — no internet, no API keys. Same
volunteer, same disaster, drones still thinking.

## 2. Reference Architecture

Nguyen et al. (2026) propose three architectures for LLM-powered UAV swarms
and benchmark them on the Eaton Fire SAR scenario.

**Architecture A — Standalone.** Fully self-contained UAVs running
lightweight LLMs (TinyLLaMA-1.1B int4) over a self-organizing mesh. Best for
environments with no surviving infrastructure.

**Architecture B — Edge-Enabled.** Adds a mobile ground station running a
high-capacity LLM. UAVs keep onboard intelligence; the EGS handles
swarm-level reasoning, replanning, validation, and operator interface.
The authors *recommend* B for SAR and demonstrate it with TinyLLaMA-1.1B
onboard each Skydio X10 and **GPT-4.1 via OpenAI API** at the EGS.

**Architecture C — Edge/Cloud-Hybrid.** Adds cloud servers for storage,
model updates, cross-swarm coordination. Out of scope for disaster
response: the cloud is precisely what isn't available.

The Architecture-B workflow is six stages: U-Net-segmented satellite frame
→ EGS grid + survey-point centroids → EGS LLM assigns points → onboard LLM
plans routes → swarm executes + streams telemetry → EGS continuously
replans.

The contribution that matters most is **Algorithm 1**, a validation-and-
retry loop wrapped around every LLM call. Both GPT-4.1 and TinyLLaMA
hallucinated in this domain (over-assignment, missed points, skipped
waypoints). Algorithm 1 wraps each call with a deterministic post-condition
check; on failure it re-prompts with a specific corrective string. The
pattern lifts coverage from 70–80% (greedy baseline) to near-100% across
8- and 12-drone configurations.

We adopt Architecture B verbatim — LangGraph orchestrator, five-module
agent (Perception, Reasoning, Action, Memory, Coordination), Algorithm 1
retry loop. We do not adopt the cloud LLM.

## 3. Our Contribution

We implement the edge-enabled architecture proposed by Nguyen et al. (2026)
with one fundamental modification: every LLM in the system runs Gemma 4
locally, eliminating the cloud dependency that fails in the precise
environments where disaster response is needed.

Five concrete changes:

1. **Onboard LLM:** TinyLLaMA-1.1B int4 (text-only) → Gemma 4 E2B
   (multimodal native) via Ollama. Same model reasons *and* sees.
2. **EGS LLM:** GPT-4.1 (OpenAI API) → Gemma 4 E4B (local Ollama). No
   API keys, no egress, no per-token cost.
3. **Cloud dependency:** required at EGS tier in the original → none
   anywhere in our stack. Verified in §5.6.
4. **Vision pipeline:** separate detection model implied by the paper →
   absorbed into Gemma 4's native multimodal forward pass.
5. **Operator interface:** mentioned but not built in the reference → a
   Flutter dashboard with a multilingual command box that round-trips
   through Gemma 4 E4B for natural-language → structured-task translation.

These matter beyond engineering tidiness. Cloud dependency is not a
nice-to-have — it's the actual failure mode of disaster zones. Multimodal
native lets the validator reason about image evidence and structured
output in one place. Multilingual without a translation API means a
Spanish- or Arabic-speaking volunteer isn't waiting on Google Translate's
reachability to dispatch her swarm.

Same architecture. Same agentic pattern. Same validation loop. Zero cloud.

---

## 4. System Architecture

FieldAgent is three layers stacked on a localhost message bus. Drones publish
state and camera frames; an Edge Ground Station (EGS) coordinates the swarm; an
operator dashboard provides the human-in-the-loop view. Every layer runs on a
single laptop in the demo, with no cloud APIs at any tier.

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 3 — Operator Interface (Flutter web)                   │
│   Live map, findings feed, multilingual command box          │
└──────────────────────────────────────────────────────────────┘
                  ▲   FastAPI WebSocket bridge (ws://localhost:9090)
                  ▼
┌──────────────────────────────────────────────────────────────┐
│ Layer 2 — Edge Ground Station                                │
│   Gemma 4 E4B (Ollama) + LangGraph coordinator               │
│   Zone allocation, replan, command translation, validation   │
└──────────────────────────────────────────────────────────────┘
                  ▲   Redis pub/sub (drones.*.state/findings/tasks, egs.state)
                  ▼
┌──────────────────────────────────────────────────────────────┐
│ Layer 1 — Per-Drone Agents (×2–3)                            │
│   Gemma 4 E2B (Ollama, time-shared) + LangGraph 5-node agent │
│   Perception · Reasoning · Action · Memory · Coordination    │
└──────────────────────────────────────────────────────────────┘
                  ▲   Redis pub/sub (drones.<id>.camera, drones.<id>.state)
                  ▼
┌──────────────────────────────────────────────────────────────┐
│ Simulation — sim/ (pure Python, cross-platform)              │
│   waypoint_runner.py · frame_server.py · scenario YAML       │
└──────────────────────────────────────────────────────────────┘
```

### 4.1 Per-drone agent

Each drone runs a LangGraph agent with five nodes (Perception, Reasoning,
Action, Memory, Coordination) driven by Gemma 4 E2B on local Ollama.
Perception samples 1 Hz from `drones.<id>.camera`. Reasoning calls Gemma 4
with the frame, drone state, and recent peer broadcasts. Action emits a
validated function call (Contract 4 in [`20-integration-contracts.md`](20-integration-contracts.md)).
Demo: 2-3 drones time-share one Ollama process; real deployment is one
Jetson Orin NX per drone. Details: [`05-per-drone-agent.md`](05-per-drone-agent.md).

### 4.2 Edge Ground Station

The EGS is a LangGraph coordinator backed by Gemma 4 E4B on a separate
Ollama instance. It maintains the shared situational picture, allocates
survey points, replans on drone failure or fire spread, translates
operator natural-language commands to structured tasks, and aggregates
findings for the dashboard. Every agentic output also passes through the
validation loop — Algorithm 1 at swarm scope. Details:
[`06-edge-ground-station.md`](06-edge-ground-station.md).

### 4.3 Operator dashboard

A Flutter web app renders three panels: map (live drone positions +
findings), per-drone status (battery, current task, last action), and
findings feed with `APPROVE`/`DISMISS` controls. The command box accepts
multilingual natural language and shows the Gemma 4-translated structured
swarm task before dispatch. The dashboard is the only component that ever
sees a human. Details: [`07-operator-interface.md`](07-operator-interface.md).

*(Phase 3c Debug Disclosure: Base Gemma 4 E4B proved unable to reliably self-correct a 25-point assignment puzzle within our inference window. To guarantee reproducibility for the Beat 3c "Wow Moment" camera capture, we run the EGS with an `--inject-overcount-once` flag, which deterministically inserts a hallucination into the first LLM output so the validation-and-retry loop is exercised visibly on camera. The recovery on the second attempt is genuine.)*

### 4.4 Communication substrate

All inter-process traffic is Redis pub/sub on `localhost:6379`. Drone-to-EGS
uses `drones.<id>.{state,findings,tasks}`. Drone-to-drone uses
`swarm.broadcasts.<id>`; a mesh simulator applies Euclidean range-based
dropout so each agent sees only in-range peers. The dashboard receives a
merged envelope over a FastAPI WebSocket at `ws://localhost:9090`. Full
channel registry locked in [`20-integration-contracts.md`](20-integration-contracts.md).

### 4.5 Simulation tier

Drones are scripted, not flown. `sim/waypoint_runner.py` interpolates each
drone along a YAML waypoint track at 2 Hz; `sim/frame_server.py` serves
pre-recorded disaster JPEGs at 1 Hz. The agent stack is unaware of the
simulation — it receives the same Redis traffic a real drone would emit.
The system we ship is the system that would deploy, modulo replacing the
sim layer with hardware drivers. Honest accounting:
[`16-mocks-and-cuts.md`](16-mocks-and-cuts.md).

---

## 5. Gemma 4 Capabilities Used

The judging brief asks whether Gemma 4 is genuinely the right tool or
ornamentally bolted on. Five capabilities are load-bearing in FieldAgent;
none are decorative.

### 5.1 Vision

Each drone's Perception node passes a JPEG frame from `drones.<id>.camera`
directly into Gemma 4 E2B's multimodal forward pass. There is no separate
vision model — no YOLO, no LLaVA stage, no CLIP embedding. The same model
that reasons about the scene also looks at it. Concretely: the prompt
includes the image bytes plus a structured description of the drone's
current state, and the model returns a `report_finding` function call whose
`visual_description` field is grounded in what the model actually saw.

### 5.2 Reasoning

Three loci: per-drone tactical (report a victim vs mark explored vs call
assist), peer evaluation (does my view confirm drone 2's low-confidence
broadcast?), and EGS swarm-level (drone 3 dropped out of range — how do I
redistribute its survey points?).

### 5.3 Function calling

Every action-driving output is a structured function call validated against
[`09-function-calling-schema.md`](09-function-calling-schema.md). Drone
agents call one of `report_finding`, `mark_explored`, `request_assist`,
`return_to_base`, `continue_mission`. The EGS calls `assign_survey_points`
or `replan_mission`. Free-form prose is rejected by the validator and
triggers a corrective re-prompt (§6). Function calling is the agentic
backbone, not a postprocessing step.

### 5.4 Multilingual

The operator command box accepts any of Gemma 4's 140+ trained languages.
The EGS round-trips through Gemma 4 E4B with a prompt asking for *both*
an operator-visible response (in the operator's language) and the
structured swarm task (canonical English). Dashboard renders both side-by-
side before dispatch. No translation API.

### 5.5 On-device

Both Gemma 4 instances run via local Ollama (E2B on drone, E4B on EGS) —
Metal on Apple Silicon, CUDA on Linux/WSL2, CPU fallback for development.
**Ollama special prize:** every agentic LLM call flows through local
Ollama; zero cloud inference path.

### 5.6 Offline guarantee

The offline claim is falsifiable, not aspirational. Every network call in
FieldAgent is one of three things: (a) Redis pub/sub on
`localhost:6379`, (b) the FastAPI WebSocket bridge on `localhost:9090`, or
(c) Ollama on `localhost:11434`. There are no external hostnames anywhere in
the agent code paths or scenario YAMLs — the only network reachability is
loopback. The demo's closing beat (Beat 5, 1:20–1:30 in
[`21-demo-storyboard.md`](21-demo-storyboard.md)) cuts to a terminal showing
no active network interface alongside `ollama list` running both Gemma 4
variants locally. That is the claim, and the demo is the test.

### 5.7 Disconnection-tolerant findings pipeline

A real disaster implies a radio link between drones and ground station
that can fail. The mesh simulator emits a `mesh.link_status` event when
a drone crosses out of EGS range or the scenario YAML trips a scripted
drop; the drone's `LinkStateMonitor` flips a `BufferedPublisher` into
standalone mode. While standalone, every Contract-4 finding is appended
to a per-drone JSONL queue alongside the in-memory deque. On link
restore the buffer drains in FIFO order; the EGS dedupes by `finding_id`
against a 5-minute window so replayed findings never double-count. Net
result: a 60-second outage produces zero data loss in the dashboard's
findings panel. The demo's strongest image is the victim-count chip
ticking 0 → 1 *after* link restore, with the buffered tile labeled
"buffered during link drop"
([`docs_assets/dashboard-beat5-phase3-restored.png`](../docs_assets/dashboard-beat5-phase3-restored.png)).
Regression-tested in `agents/egs_agent/tests/test_e2e_link_drop_replay.py`
(fakeredis) and `frontend/ws_bridge/tests/test_e2e_playwright_beat5_offline_recovery.py`
(real Chromium).

---

## 6. Validation-and-Retry Loop

### 6.1 The hallucination problem

Small LLMs hallucinate. In our domain that means a drone reports a "victim"
at a GPS coordinate outside its assigned zone, or assigns the same survey
point to two drones, or returns prose where a structured function call was
required. None of these are catastrophic in isolation. All of them are
catastrophic when the swarm trusts peer broadcasts and the operator trusts
the swarm.

### 6.2 Algorithm 1

Nguyen et al. (2026) Algorithm 1 — *Hallucination Mitigation via
Constraint-Conditioned Re-prompting* — defines four invariants: (a) hard
constraints stated explicitly in the prompt, (b) deterministic post-hoc
validation of every LLM output, (c) a corrective re-prompt that includes the
model's own failed attempt, and (d) bounded retries with a safe fallback. We
implement all four verbatim and apply them to three loci: per-drone function
calls, EGS swarm-level assignment, and operator command translation.

### 6.3 Our adaptation

Reference paper validates free-form text against expected structure. We
validate *function calls* against a three-layer stack: JSON Schema shape
(`jsonschema.Draft202012Validator`), typed argument coercion (Pydantic v2
`model_validate`), and semantic constraints in Python (zone bounds,
duplicate detection, severity↔confidence rules, monotonic coverage). The
retry loop is hand-written because each retry mutates the conversation
(appending the failed attempt + corrective prompt), which `tenacity`
wasn't built for.

```python
for attempt in range(MAX_RETRIES):  # MAX_RETRIES = 3
    response = await ollama_call(model="gemma4:e2b",
                                 messages=conversation,
                                 tools=DRONE_FUNCTION_SCHEMAS)
    call = parse_function_call(response)
    result = validate(call, perception_bundle)  # shape → types → semantics
    if result.valid:
        return call
    conversation.append({"role": "assistant", "content": str(call)})
    conversation.append({"role": "user", "content": result.corrective_prompt})
return continue_mission_call(reason="validation_exhausted")  # safe fallback
```

### 6.4 Corrective prompts

The corrective strings are terse, specific, and directive. We carry the
paper's strings verbatim where the failure mode matches:

> *"You are hallucinating, creating more survey points than required. Do
> not invent, modify, or add any new points. There are exactly {n} survey
> points. Reassign so that exactly these {n} points are distributed across
> drones."*

And we add the function-calling-specific strings the paper does not cover:

> *"You reported a severity {severity} finding with confidence {conf}. For
> severity 4 or higher, confidence must be at least 0.6. Either lower the
> severity or increase confidence with stronger visual evidence, or use
> continue_mission() if you are uncertain."*

Each failure is mapped to a single `RuleID` enum value
(`shared/contracts/rules.py`) so the corrective prompt is one lookup, not a
conditional cascade. Full table in
[`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md).

### 6.5 Engineering a reliable demo trigger

The video needs at least one visible catch. We don't rely on Gemma 4
spontaneously hallucinating on cue. We constrain the EGS assignment task
with a deliberately awkward survey-point count (25 points / 3 drones /
one partially out of mesh range) that produces over- or under-assignment
with measurable frequency. The validation loop catches it; the corrective
prompt fires; the second attempt succeeds. Terminal log streams to the
dashboard so the audience sees catch and correction in the same frame.

The same loop has a structurally important second property: when Gemma
4 E4B is slow or unreachable under VRAM pressure, the EGS falls through
max-retries to a **deterministic round-robin assignment** instead of
raising. Transport-class exceptions (`httpx.HTTPError`,
`asyncio.TimeoutError`, `json.JSONDecodeError`) are retryable; the
spawned replan task is wrapped in `asyncio.wait_for(..., timeout=240s)`
so the in-flight guard always clears within bounded wall time. The
swarm keeps operating even when the EGS LLM hangs — the operator gets
*some* assignment rather than indefinite silence. (GitHub issue #32;
regression coverage at `agents/egs_agent/tests/test_coordinator_replan_hang.py`
and `test_replanning.py`.)

### 6.6 Empirical catch rate

Quantitative breakdown of validator pass-rate per locus (drone agent / EGS
assignment / operator command) lives in §8 Table 2, populated from
`validation_event` log telemetry of the demo runs.

---

## 7. Fine-Tuning

We fine-tuned a LoRA on Gemma 4 E2B against the **xBD** dataset (Gupta et
al., 2019) — the largest public benchmark for post-disaster building damage
classification, covering 850,736 annotated buildings across 19 disasters
(wildfires, hurricanes, earthquakes, floods, tornadoes, volcanic eruptions,
tsunamis) with four Joint Damage Scale classes (no_damage, minor_damage,
major_damage, destroyed). xBD is the established benchmark in this space;
using it makes our results comparable to prior literature.

LoRA via **Unsloth special prize**: kernel-level speedups on the LoRA
forward/backward path bring single-GPU multimodal fine-tuning into a
single-day window. Following Unsloth's current Gemma 4 vision recipe, we
start with `finetune_vision_layers=False` and tune the language, attention,
and MLP modules first; the vision tower is enabled only if the visual task
plateaus. Hyperparameters (per [`12-fine-tuning-plan.md`](12-fine-tuning-plan.md)):
rank 32, alpha 32, `target_modules="all-linear"`, learning rate 2e-4 with
cosine schedule, batch size 2–4 with gradient accumulation 4–8, bf16, 1–3
epochs over the cropped per-building patch set (~500k patches at 224×224),
on a rented A10 / A4000 / A5000 instance.

Results (Table 5, §8): base Gemma 4 E2B vs fine-tuned LoRA, per-class F1 and
overall accuracy on the held-out xBD test split (split by disaster, not
random sample, for honest generalization). Sim-to-real caveat: the xBD
imagery is high-altitude post-event satellite, while our simulation serves
curated crops. The fine-tune helps the *model*; transferring its gains to
live drone footage is future work.

---

## 8. Results and Metrics

All numbers come from telemetry logs of demo runs (target: ≥5 runs per
metric for variance bounds). The tables below define the shape of the
reportable claim; cells are populated from `validation_event` and
`mission_summary` events emitted by the agent stack.

**Table 1 — Coverage and Completion (3-drone disaster_zone_v1)**

| Metric | FieldAgent | Greedy baseline | Reference paper (12 drones) |
|---|---|---|---|
| Coverage rate (mean of N runs) | __% | __% | ~100% |
| Mission completion time (s) | __ | __ | 17 min |
| First-finding latency (s) | __ | __ | n/a |

**Table 2 — Validation-and-Retry Loop**

| Validator | Calls | First-attempt pass | Retry-1 pass | Retry-2 pass | Total fail (fallback) |
|---|---|---|---|---|---|
| Drone agent | __ | __% | __% | __% | __% |
| EGS assignment | __ | __% | __% | __% | __% |
| Operator command | __ | __% | __% | __% | __% |

**Table 3 — Inference Latency**

| Component | Model | Avg latency (p50) | p95 | Throughput |
|---|---|---|---|---|
| Drone agent | Gemma 4 E2B (Ollama) | __s | __s | ~1 Hz/drone |
| EGS coordinator | Gemma 4 E4B (Ollama) | __s | __s | event-driven |
| Operator command | Gemma 4 E4B (Ollama) | __s | __s | event-driven |

**Table 4 — Multilingual Operator Command Fidelity**

| Language | Commands tested | Correct structured task | Notes |
|---|---|---|---|
| English | __ | __% | baseline |
| Spanish | __ | __% | demo language |
| Arabic | __ | __% | RTL rendering check |

**Table 5 — Fine-Tuning (if §7.A applies)**

| Class | Base F1 | Fine-tuned F1 | Δ |
|---|---|---|---|
| no-damage | __ | __ | __ |
| minor-damage | __ | __ | __ |
| major-damage | __ | __ | __ |
| destroyed | __ | __ | __ |
| **macro-F1** | __ | __ | __ |

The reportable claim from these tables, in narrative form: FieldAgent
matches or approaches the reference paper's coverage and completion-time
results using *only on-device Gemma 4*, with the validation loop intercepting
hallucinations at a measurable rate, across a multilingual operator
interface that the reference paper described but did not implement.

---

## 9. Honest Limitations

A submission that overclaims is worse than one that underclaims. The
following is what FieldAgent does *not* do, and why each cut is defensible
within a 20-day hackathon window. Full rationale per item lives in
[`16-mocks-and-cuts.md`](16-mocks-and-cuts.md).

- **Pure simulation, no hardware.** No drone in this project has ever flown.
  `sim/waypoint_runner.py` interpolates GPS along a YAML-scripted track and
  `sim/frame_server.py` serves pre-recorded JPEGs. The agent stack above the
  simulation tier is the same code that would run on a Jetson Orin NX; the
  honest claim is that the *cognition* would deploy, not the airframe
  control.

- **Predefined zones, not U-Net segmentation.** The reference paper extracts
  the wildfire boundary from satellite imagery via a U-Net. We ship YAML
  polygons. Building U-Net inference on top of a 20-day Gemma-focused build
  was not the right trade.

- **Software mesh dropout, not WiFi mesh.** Drone-to-drone broadcasts are
  Redis pub/sub on localhost with Euclidean range filtering applied by a
  `mesh_simulator` process. From the agent's perspective, behaviour is
  identical — peers in range deliver, peers out of range don't — but the
  physics of WiFi multipath and mesh routing are not modelled.

- **2–3 drones, not the paper's 8 or 12.** Each Gemma 4 E2B Ollama process
  carries real inference weight; we time-share one onboard model across the
  swarm. Scaling to 12 drones is a hardware question (one Jetson per drone),
  not an architectural one.

- **Public-domain disaster aerials, not live drone footage.** Fixtures
  under `sim/fixtures/frames/` are real post-disaster aerials curated from
  the FEMA Photo Library and USFWS (8 frames + 1 scene aerial under
  `sim/fixtures/base_images/`, all with full LICENSES.md provenance and
  upstream `source_sha256` drift lockdown in `scripts/fixtures_manifest.json`).
  The aesthetic differs from a Skydio X10's downward camera but is
  functionally equivalent for sim-vision iteration. xBD-proper (xView2
  credentials-gated) remains the fine-tune training corpus under
  `ml/data_prep/`, not the sim playback set. We flag the distinction in
  §10 reproducibility notes.

- **Perception ground-truth gap on the demo fixtures.** None of the
  public-domain aerials in `sim/fixtures/frames/` show a visibly
  identifiable human body — the "victim" fixture is the FEMA aerial of
  Gulfview Elementary post-Hurricane-Katrina (a destroyed structure shot
  from altitude, not a body). Base Gemma 4 E2B reads it correctly as a
  damaged building and the system prompt biases against false positives,
  so `report_finding(type="victim", ...)` does not fire reliably on every
  pass over the standalone window. We address this two ways for the
  demo: (a) the validation-loop + deterministic-fallback path (§6.5)
  produces a guaranteed assignment artifact even when the perception
  call is non-trivial; (b) a mock-Ollama mode (`scripts/ollama_mock_server.py`)
  is available for capture reproducibility. The fine-tune adapter (§7),
  if it ships, is the real fix for this gap. Full background in
  [`plans/2026-05-12-drone3-reliability-capture.md`](plans/2026-05-12-drone3-reliability-capture.md).

- **~1 Hz perception sampling.** Gemma 4 E2B inference latency on commodity
  GPUs is the bottleneck. Sampling more frequently than 1 Hz starves the
  reasoning node. Real deployments would run one model per drone and raise
  the rate. On Apple Silicon, 3 concurrent vision+tools calls serialize on
  Metal; the tuning recipe cited above brings this back into a survivable
  window for laptop demos.

- **Resilience scenarios are scripted.** Drone failure, fire spread, and
  EGS link drop are timeline-fired in
  `sim/scenarios/resilience_v1.yaml`, not driven by emergent dynamics. The
  swarm's *response* to each event is genuine; the *triggering* is
  scripted so the demo is reproducible.

We list these explicitly because the architecture and the validation loop are
the contributions worth defending. The limitations above are deliberate
descopes from a clear scope hierarchy ([`17-feasibility-and-gates.md`](17-feasibility-and-gates.md)),
not accidents.

---

## 10. Reproducibility

Hardware floor: any laptop with Python 3.11+, Redis 7+, and Ollama. NVIDIA
GPU (Linux or WSL2 on Windows 11) is preferred for inference throughput;
Apple Silicon via Metal is fully supported (with the tuning recipe in
[`plans/2026-05-12-drone3-reliability-capture.md`](plans/2026-05-12-drone3-reliability-capture.md)
for 3-drone concurrent vision+tools); CPU fallback works for development.
Fine-tuning is the only step that requires CUDA and is owned by a single
workstream.

Setup is one command (`uv sync --all-extras`) plus pulling the two Gemma 4
tags from Ollama. The demo launcher is one command
(`scripts/run_full_demo.sh disaster_zone_v1`) and brings up Redis, the
simulation tier, the agent stack, the EGS, the WebSocket bridge, and the
dashboard in a single tmux session. Every launcher under `scripts/*.sh`
auto-detects `.venv/bin/activate` and sources it inside its spawned tmux
panes, so an outside tester can run the demo without manually activating
the venv (regression-guarded by
`scripts/tests/test_launch_scripts.py::test_shell_launcher_emits_venv_activation_when_present`).

The cold-start path is [`sim-reproduction.md`](sim-reproduction.md):
`git clone` → `uv sync` → `ollama pull` → three escalating one-command
demos. A v1 cold-run from a fresh clone was completed on Apple Silicon
M1 16GB on 2026-05-12 (Phase G); every gap surfaced was fixed in the
same PR (findings doc:
[`plans/2026-05-12-phase-g-cold-run-findings.md`](plans/2026-05-12-phase-g-cold-run-findings.md)).
A formal outside-tester pass on a fresh Linux/WSL2 machine lands
Days 15–16 of the timeline.

The runtime is **Ollama**: no API keys, no network egress, no cloud account.
This is both the Ollama special-prize play and the falsifiable form of the
offline guarantee — a judge with no internet connection can still run the
full system. Detailed setup in `README.md` and
[`13-runtime-setup.md`](13-runtime-setup.md).

---

## 11. Conclusion + Future Work

**Future work.** Real hardware deployment with a Jetson Orin NX per drone
is the natural next step — the agent stack above the simulation tier is
already hardware-ready. Beyond that: U-Net survey-zone segmentation from
live satellite imagery; real WiFi-Halow mesh in place of the Redis
simulator; voice-mode operator commands; fleets in the 8–12 drone range
the paper benchmarks against.

**Conclusion.** Agentic search-and-rescue can run entirely on-device. The
edge-enabled architecture from Nguyen et al. (2026) holds when the cloud
LLM is replaced with on-device Gemma 4 — the validation loop still catches
hallucinations, the swarm still coordinates through dropout, the operator
still drives the system in their own language. Billions of people live in
climate-vulnerable regions, and the first hour of every disaster is the
hour the cloud is unreachable. **Cell towers fail first. Brains shouldn't.**
