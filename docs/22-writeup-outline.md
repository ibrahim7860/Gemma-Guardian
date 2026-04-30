# 22 — Writeup Outline

## Why This Doc Exists

The technical writeup is one of the three submission deliverables (alongside repo and video). Judges read it after watching the video to evaluate technical depth. This doc gives the locked structure so Person 4 can draft cleanly without inventing the outline. (Person 1 reviews the simulation / disaster-scene section for accuracy.)

## Length

**Target: 2,500 words** (≈ 8-10 minute read)

**Hard cap: 4,000 words.** Past that, judges skim.

## Structure

```
1. Problem Framing                          (~250 words)
2. Reference Architecture                   (~400 words)
3. Our Contribution                         (~250 words)
4. System Architecture                      (~400 words)
5. Gemma 4 Capabilities Used                (~300 words)
6. Validation-and-Retry Loop                (~400 words)
7. Fine-Tuning (if applicable)              (~300 words)
8. Results and Metrics                      (~400 words)
9. Honest Limitations                       (~250 words)
10. Reproducibility                         (~150 words)
11. Conclusion + Future Work                (~150 words)
```

## Section 1: Problem Framing

**Goal:** establish the stakes and the gap.

Key points:
- Disasters cause cell tower / internet failure in the first hour
- 3.6B people in disaster-vulnerable regions
- Existing AI drone systems require cloud
- The gap: AI-driven disaster response that works WITHOUT cloud
- Specific: Los Angeles fires January 2025 as concrete example
- **Anchor with one named operator persona** (e.g., a Red Cross volunteer in a wildfire response). Per [`02-hackathon-context.md`](02-hackathon-context.md), winning Gemma submissions name a specific person rather than only citing aggregate statistics. The "3.6B" framing belongs in the impact closer, not the opening.

Sources to cite:
- LA fires NASA imagery (https://svs.gsfc.nasa.gov/5558/, mentioned in the reference paper)
- WHO / UN climate vulnerability statistics
- Examples of existing systems (Skydio, Shield AI) and their cloud dependencies

## Section 2: Reference Architecture

**Goal:** explain Nguyen et al. 2026 in enough depth that the reader understands what we built on.

Key points:
- Three architectures: standalone, edge-enabled, edge/cloud-hybrid
- Their conclusion: edge-enabled wins for SAR
- Their setup: TinyLLaMA onboard, GPT-4.1 at EGS
- Their workflow: U-Net → grid → assignment (LLM) → routing (LLM) → execution → telemetry
- Their innovation: Algorithm 1 validation-and-retry loop
- Their results: ~100% coverage vs 70-80% baseline

Be precise but concise. The reader can read the paper themselves.

## Section 3: Our Contribution

**Goal:** clearly state what we did and why it matters.

The thesis sentence:

> "We implement the edge-enabled architecture proposed by Nguyen et al. (2026) with one fundamental modification: every LLM in the system runs Gemma 4 locally, eliminating the cloud dependency that fails in the precise environments where disaster response is needed."

Then enumerate:
1. Onboard TinyLLaMA-1.1B → Gemma 4 E2B (multimodal native)
2. EGS GPT-4.1 → Gemma 4 E4B (local Ollama instance)
3. Cloud APIs → none
4. Vision: separate model in original → native to Gemma 4
5. Operator interface: not built in original → multilingual Flutter dashboard

Why these changes matter:
- Cloud dependency is the core failure mode (state explicitly)
- Multimodal native means simpler architecture and prompt patterns
- Multilingual operator commands work without translation API

## Section 4: System Architecture

**Goal:** describe what we actually built.

Subsections:
- 4.1: Three-layer overview (drones, EGS, operator interface)
- 4.2: Per-drone agent (LangGraph 5 nodes)
- 4.3: EGS coordinator
- 4.4: Operator dashboard
- 4.5: Communication substrate

Include the architecture diagram from [`04-system-architecture.md`](04-system-architecture.md).

Keep this section descriptive, not procedural. The repo has the code.

## Section 5: Gemma 4 Capabilities Used

**Goal:** show that Gemma 4 is genuinely the right tool, not bolted on.

Five subsections:

1. **Vision** — drone camera input, multimodal native (no separate vision model needed)
2. **Reasoning** — per-drone tactical decisions, peer broadcast evaluation, EGS swarm coordination
3. **Function calling** — every action-driving output is structured (cite the schemas)
4. **Multilingual** — operator commands in 140+ languages, no translation API
5. **On-device** — Ollama local inference (E2B onboard, E4B at EGS), validated with offline demo. Explicitly call out the **Ollama special prize** play here: every Gemma 4 instance in the system is served by a local Ollama runtime, with no cloud inference fallback anywhere in the stack.

For each, give a concrete example from the system.

**Offline guarantee subsection (5.6):** state the offline claim as a falsifiable property, not a marketing line. Enumerate every network call in the system and show each is either (a) Redis pub/sub on localhost, (b) FastAPI WebSocket bridge on localhost, or (c) Ollama on localhost. No external hostnames. Reference the airplane-mode demo moment from [`21-demo-storyboard.md`](21-demo-storyboard.md) as evidence.

## Section 6: Validation-and-Retry Loop

**Goal:** showcase the technical innovation.

Subsections:
- 6.1: The hallucination problem (with examples observed in our system)
- 6.2: Algorithm 1 from the reference paper
- 6.3: Our adaptation to function calling
- 6.4: Corrective prompts (verbatim, including the paper's specific strings)
- 6.5: How we engineer reliable triggers for the demo
- 6.6: Empirical hallucination catch rate (number from logs)

Include a code block showing the Python validation loop pseudocode.

## Section 7: Fine-Tuning (Conditional)

**If Day-10 gate passed:**

Subsections:
- 7.1: Task definition (xBD building damage classification)
- 7.2: Why xBD (largest, most diverse, established benchmark)
- 7.3: LoRA approach via Unsloth — explicitly frame this as the **Unsloth special prize** play, with a one-line note on why Unsloth (kernel-level speedups making LoRA on the Gemma 4 vision adapter feasible inside the hackathon window)
- 7.4: Hyperparameters and training time
- 7.5: Results table: base vs fine-tuned accuracy, per-class F1
- 7.6: Sim-to-real considerations

**If Day-10 gate failed:**

Replace with section titled "Attempted Fine-Tuning":
- 7.1: What we attempted
- 7.2: What we observed (be honest)
- 7.3: Why we shipped with base Gemma 4 + structured prompting

Either version is acceptable. Honest engineering reporting is respected.

## Section 8: Results and Metrics

**Goal:** falsifiable performance claims.

Tables to include:

**Table 1: Coverage and Completion**

| Metric | Our system (3 drones) | Greedy baseline | Reference paper baseline |
|---|---|---|---|
| Coverage rate (avg) | __% | __% | 70-80% |
| Mission completion time | __ min | __ min | __ min |

**Table 2: Validation Loop Performance**

| Validator | Calls | First-attempt pass | Retry-1 pass | Retry-2 pass | Total fail |
|---|---|---|---|---|---|
| Drone agent | __ | __% | __% | __% | __% |
| EGS assignment | __ | __% | __% | __% | __% |
| Operator command | __ | __% | __% | __% | __% |

**Table 3: Inference Performance**

| Component | Model | Avg latency | Throughput |
|---|---|---|---|
| Drone agent | Gemma 4 E2B | __s | __ Hz/drone |
| EGS coordinator | Gemma 4 E4B | __s | __ calls/min |
| Operator command | Gemma 4 E4B | __s | event-driven |

**Table 4: Multilingual (if implemented)**

| Language | Commands tested | Translation accuracy |
|---|---|---|
| English | __ | __ |
| Spanish | __ | __ |
| Arabic | __ | __ |

Numbers come from logs of demo runs. Aim for 5+ runs per measurement.

## Section 9: Honest Limitations

**Goal:** transparently document what we cut and why.

Bulleted list with one paragraph per item:

- Pure simulation (no real hardware deployment)
- Predefined zones instead of U-Net segmentation
- Software mesh dropout instead of real WiFi mesh
- Limited drone count (2-3 vs paper's 8-12)
- Simulation aesthetic differs from real aerial imagery
- Inference time per drone limits sampling rate to ~1 Hz
- Resilience scenarios are scripted, not arbitrary

This is the most important section for credibility. Don't downplay.

## Section 10: Reproducibility

**Goal:** make it easy for judges to run our system.

Brief:
- Hardware requirements
- One-command setup script
- One-command demo launcher
- Expected output
- Explicit note that the runtime is **Ollama** (no API keys required, no network egress) — reinforces the Ollama special-prize play and the offline guarantee at the same time

Pointer to README.md for full instructions.

## Section 11: Conclusion + Future Work

**Goal:** end strong, identify what's next.

Future work:
- Real hardware deployment (Jetson Orin NX per drone)
- Multi-swarm coordination via Architecture C
- Full U-Net segmentation pipeline
- Real WiFi mesh networking
- More languages, voice operator commands
- Larger fleets (8+ drones)

Conclusion:
- Reaffirm the thesis: agentic SAR can work entirely offline with on-device Gemma 4
- Reaffirm the impact: 3.6B people in disaster-vulnerable regions

End with a memorable line. Suggested: *"Cell towers fail first. Brains shouldn't."*

## Style Guide

- **Voice:** confident but not boastful. Honest about limitations.
- **Tense:** present tense for the system, past tense for what we did.
- **Person:** "we" for the team, "the system" for the prototype.
- **Tone:** engineering writeup. Not marketing copy. Not academic stiffness.
- **Citations:** academic style. arXiv links acceptable.

## Length Discipline

If the draft exceeds 4,000 words:

- Cut: Section 4 detail (point to repo)
- Cut: Section 8 if metrics are sparse
- Cut: Section 5 examples (one per capability max)
- Keep: Sections 1, 3, 6, 9 — these are the core argument

## Iteration

Draft 1: by Day 14 (May 16).
Draft 2: incorporate feedback from teammates by Day 16.
Final: by Day 17 (May 17). Lock at end of Day 17.

## Cross-References

- The reference paper: [`03-reference-paper.md`](03-reference-paper.md)
- The architecture: [`04-system-architecture.md`](04-system-architecture.md)
- The validation loop: [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md)
- The fine-tuning plan: [`12-fine-tuning-plan.md`](12-fine-tuning-plan.md)
- The mocks list: [`16-mocks-and-cuts.md`](16-mocks-and-cuts.md)
- The demo video: [`21-demo-storyboard.md`](21-demo-storyboard.md)
