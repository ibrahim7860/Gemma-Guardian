# 03 — Reference Paper

## The Paper

**Nguyen, T. M., Truong, V. T., & Le, L. B. (2026).** *Agentic AI Meets Edge Computing in Autonomous UAV Swarms.* arXiv:2601.14437.

INRS, University of Québec, Montréal. Published January 20, 2026.

## Why This Paper Matters to Us

This is the most directly relevant published architecture for what we're building. It defines the academic framing for our submission and gives us a falsifiable baseline to compare against.

**Our pitch leverages this paper:** we implement their architecture with on-device Gemma 4 replacing every cloud LLM dependency. This gives us academic legitimacy, a clear differentiator, and a credible quantitative comparison.

## What the Paper Proposes

Three architectures for LLM-powered UAV swarms:

### A. Standalone UAV Swarm
Each UAV is fully self-contained. Onboard processors (NVIDIA Jetson Orin, Qualcomm RB5) run lightweight LLMs (TinyLLaMA). Self-organizing wireless mesh, no external infrastructure. Best for extreme environments with no infrastructure.

### B. Edge-Enabled UAV Swarm (RECOMMENDED FOR SAR)
Adds a mobile ground station as edge server with high-capacity processors running full-scale LLMs. UAVs still have onboard intelligence; the EGS handles advanced reasoning, validation, and operator interface. Best for semi-connected, dynamic environments. **This is the architecture we implement.**

### C. Edge/Cloud-Enabled UAV Swarm
Adds cloud servers for global storage, model updates, cross-swarm coordination. Best for large-scale, long-duration missions. Out of scope for us (and out of scope for disaster response — cloud isn't available).

## The Wildfire SAR Use Case (What They Actually Built)

Setup:
- Onboard: TinyLLaMA-1.1B (int4) on Jetson Orin NX (70 TOPS)
- EGS: GPT-4.1 via OpenAI API
- Drone model: Skydio X10 (RGB + thermal, 1500m range, 15 m/s)
- Test scene: Eaton Fire (Los Angeles, January 2025) ~300 grid cells of 450m × 450m
- 8 and 12 drone configurations evaluated
- Framework: LangGraph
- Wildfire boundary: U-Net segmentation on satellite imagery

Workflow:
1. Satellite image arrives → U-Net extracts fire boundary
2. EGS generates uniform grid inside boundary; centroids = survey points
3. EGS LLM (GPT-4.1) assigns survey points to UAVs (with validation loop)
4. Each UAV's onboard LLM (TinyLLaMA) plans its flight route (with validation loop)
5. UAVs survey, perform real-time detection, transmit telemetry
6. EGS continuously updates fire boundary and re-plans

## Key Results

- Coverage rate: near-100% with their design vs. 70-80% with the baseline
- Mission completion time: 17 min (12 drones) vs. 22+ min greedy baseline
- 8 vs 12 drones: smaller fires → 8 drones better (12 causes hallucinations); larger fires → 12 drones better

## What's Crucial to Replicate

### Algorithm 1 — The Validation-and-Retry Loop

This is the most important thing in the paper. Both GPT-4.1 (EGS) and TinyLLaMA (onboard) hallucinated in this domain. Specifically: assigning more survey points than exist, missing survey points, generating routes that didn't visit assigned waypoints.

Their mitigation pattern:

```
1. LLM generates structured output
2. Deterministic code validates against hard constraints
3. If validation fails, append CORRECTIVE PROMPT and re-prompt:
   - Too many points: "You are hallucinating, creating more survey points 
     than required. Do not invent, modify, or add any new points."
   - Missing points: "You have not assigned all survey points to UAVs. 
     You must allocate all survey points to UAVs."
4. Repeat until valid (capped at N retries)
```

We **must** implement this pattern. It's the demonstrable wow moment of the demo. See [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md).

### LangGraph as the Orchestration Framework

The paper recommends LangGraph for UAV swarms over AutoGen and CrewAI. Their reasoning:
- Graph-based, stateful, event-driven
- Cyclic and asynchronous execution (drones sense-plan-coordinate continuously)
- Eliminates single points of control via swarm handoff tools
- Suited to communication-constrained environments

We use LangGraph. Don't second-guess this — building our own orchestration eats time we don't have.

### The Five Modules per Agent

Every agent (per-drone, EGS) implements:

- **Perception** — multimodal sensor inputs → structured representations
- **Reasoning** — interpret objectives, decompose tasks, generate plans
- **Action Execution** — translate plans to API calls / flight commands
- **Memory** — short-term (active task) + long-term (mission history)
- **Coordination** — multi-agent dialogue, task negotiation, consensus

Our LangGraph nodes map 1:1 to these modules. See [`05-per-drone-agent.md`](05-per-drone-agent.md).

## The Six Open Challenges (And Our Response)

The paper's Section V lists open challenges. Our response to each:

1. **Efficient Onboard LLMs** — we use Gemma 4 E2B (designed for edge). Trade reasoning depth for inference speed. We sample camera at 1 Hz, not 30.

2. **Hallucination Mitigation** — we implement Algorithm 1 with our function-calling schema. Confidence scores propagate across drones so receiving drones can reason about whether to trust peer broadcasts.

3. **Robust Multi-Agent Collaboration** — we simulate communication dropout and demonstrate the swarm continuing in standalone mode if EGS link severs. See [`08-mesh-communication.md`](08-mesh-communication.md).

4. **Edge Infrastructure Scalability and Reliability** — out of scope for us; we mock the EGS as a laptop. Honest in writeup.

5. **Evaluation and Benchmarks** — we define our own metrics (see [`22-writeup-outline.md`](22-writeup-outline.md)) since the paper notes none exist. This is an opportunity, not a constraint.

6. **UAV Technical Limitations** — out of scope (we're in simulation). Honest in writeup.

## What We Change vs the Paper

| Component | Paper | Us |
|---|---|---|
| Onboard LLM | TinyLLaMA-1.1B (int4) | Gemma 4 E2B (multimodal) |
| EGS LLM | GPT-4.1 (cloud API) | Gemma 4 E4B (local) |
| Cloud dependency | Required for EGS | None |
| Vision model | Separate (YOLO/LLaVA implied) | Native to Gemma 4 |
| Operator interface | Mentioned, not built | Multilingual Flutter dashboard |
| Hardware | Jetson Orin NX per UAV | Pure simulation |
| Use case | Wildfire SAR | General disaster (broader applicability for demo) |

## What We Don't Change

- The three-architecture taxonomy (we implement Architecture B)
- The five-module agent design
- LangGraph as orchestrator
- The validation-and-retry loop (Algorithm 1)
- The UAV/EGS division of labor
- Performance metrics (coverage rate, completion time)

## How to Cite the Paper in Our Writeup

> "Our work implements the edge-enabled architecture proposed by Nguyen et al. (2026) [cite arXiv:2601.14437], with one fundamental modification: every LLM in the system runs Gemma 4 locally. The original architecture relies on GPT-4.1 via OpenAI API at the edge ground station — a cloud dependency that fails in the precise environments where disaster response is needed. By replacing both the onboard LLM (TinyLLaMA-1.1B) and the EGS LLM (GPT-4.1) with on-device Gemma 4 variants (E2B and E4B respectively), we demonstrate that the agentic SAR pattern can operate entirely without internet access while preserving the core architectural benefits the paper validated."
