# 01 — Vision and Pitch

## The Problem

After every major disaster — earthquakes, hurricanes, wildfires — communication infrastructure collapses in the first hour. Cell towers go down. Internet goes down. The very moment when coordinated response would save the most lives is the moment when the cloud-AI tools that responders depend on become useless.

Existing AI-powered drone systems for disaster response (Skydio, Shield AI, Auterion) require backhaul connectivity for any nontrivial reasoning. The most advanced published architecture for AI-driven disaster response (Nguyen et al., 2026) explicitly puts GPT-4.1 at the edge ground station — meaning even "edge-enabled" systems still depend on a cloud they can't reach in the disaster zone.

3.6 billion people live in climate-vulnerable regions. The Los Angeles fires of January 2025 demonstrated that even wealthy regions lose coordination infrastructure when it matters most.

## What We're Building

**FieldAgent** is a fully offline, multi-drone disaster response coordinator powered entirely by on-device Gemma 4. The system demonstrates:

- A simulated swarm of 2-3 drones, each running Gemma 4 E2B locally for vision, reasoning, and decision-making
- An Edge Ground Station running Gemma 4 E4B for swarm-level task allocation, multilingual operator commands, and replanning
- A self-organizing communication layer with simulated mesh dropout
- A validation-and-retry loop that catches Gemma 4 hallucinations on-camera before they corrupt the swarm's shared situational picture
- A Flutter dashboard giving the operator a live view and natural-language command capability in 140+ languages

The entire system operates with zero cloud dependency. The demo will explicitly show the laptop running with no network connectivity while the swarm continues to coordinate.

## The Differentiator vs the Reference Paper

The Nguyen et al. paper proposed three architectures (standalone, edge-enabled, edge/cloud-hybrid) and concluded that the edge-enabled design is right for SAR. They demonstrated this with TinyLLaMA-1.1B onboard each drone and **GPT-4.1 (cloud API)** at the EGS.

That cloud dependency is the actual failure mode of disaster zones. We replaced every LLM in their architecture with Gemma 4 running locally:

- **Onboard:** TinyLLaMA-1.1B → Gemma 4 E2B (multimodal, native vision)
- **EGS:** GPT-4.1 → Gemma 4 E4B (running on a portable workstation)
- **Cloud:** none → none

Same architecture. Same agentic pattern. Same validation-loop approach. Zero cloud.

## The Demo Moment

When a judge watches the 90-second video, they should see:

1. A real software-only Python simulation with 2-3 drones flying in a damaged-building scene
2. Gemma 4's reasoning and function calls visible on screen as drones identify victims and damage
3. The validation loop catching a Gemma 4 hallucination and correcting it (live)
4. An operator typing a command in Spanish; Gemma 4 translates to swarm tasking
5. A drone failure mid-mission; the swarm reallocates work
6. A terminal showing no internet connectivity while all of this happens

## Why This Wins

- **Specific and credible.** Not "AI for disaster response" — implementing a specific published architecture with a specific architectural change.
- **Technically correct use of Gemma 4.** Vision, reasoning, function calling, multilingual, on-device — all used naturally, none bolted on.
- **Emotionally resonant.** Disasters are universal. Cell towers failing is universal.
- **Falsifiable claims.** Coverage rate, mission completion time, hallucination catch rate, multilingual fidelity — measurable against the paper's baseline.
- **Open and reproducible.** Permissively licensed open stack throughout (Redis, LangGraph, Ollama, Flutter) with Gemma 4 weights under Google's permissive Gemma Terms of Use. Anyone with a laptop and the open weights can deploy this.

## Out of Scope (Intentionally)

- Real drone hardware (we're in simulation, framed honestly)
- Real fire physics or sensor fusion (the software sim uses scripted waypoint motion, not physics)
- Real satellite imagery / U-Net segmentation (we use predefined zones)
- Production-grade safety guarantees (this is a research prototype)
- Beyond-line-of-sight regulatory compliance (out of scope for sim)

See [`16-mocks-and-cuts.md`](16-mocks-and-cuts.md) for the full list and why each cut is defensible.
