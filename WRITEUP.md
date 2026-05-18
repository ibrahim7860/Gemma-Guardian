# FieldAgent — Disaster Response When the Cloud Goes Down

*Gemma 4 Good Hackathon submission. Repo: [`github.com/ibrahim7860/Gemma-Guardian`](https://github.com/ibrahim7860/Gemma-Guardian). Team: Ibrahim Ahmed, Hazim Kuniyil, Muhammad Kaleelurrahman, Qasim Bhutta, Muhammad Thayyil.*

## 1. The Problem

January 2025. A Red Cross volunteer is coordinating evacuation at the Eaton Fire above Pasadena. In the first hour, the foothills cell tower fails from heat damage. By the third, her handheld radio is the only working communication device on the hillside — and every AI tool her agency paid for has become a useless rectangle on a screen.

This is not unusual. It is the rule.

The disasters where AI assistance would matter most — wildfires, hurricanes, earthquakes, floods — are precisely the disasters that take down the infrastructure those AI tools depend on. Today's leading drone platforms (Skydio, Shield AI, Auterion) need a working network for any non-trivial reasoning. Even the strongest published research on AI-driven disaster response, Nguyen, Truong & Le (2026, arXiv:2601.14437), assumes a cloud LLM at the mobile command tier — a working internet connection at the exact place where there isn't one.

Roughly 3.6 billion people live in regions the IPCC classifies as highly vulnerable to climate-driven disasters. The intersection of "needs AI rescue coordination" and "has reliable internet during the rescue" is approximately empty.

**FieldAgent removes the dependency.** Every AI decision in our system happens locally, on a single laptop, with no internet, no API keys, and no cloud account. We pulled the strongest published architecture in the field and amputated its weakest joint.

## 2. What We Built

Nguyen et al. recommend a middle architecture — a small language model on each drone, plus a larger model at a mobile ground station — paired with a validation algorithm that catches model hallucinations before they become bad commands. Their published numbers show this lifting drone coverage of a disaster zone from 70–80% (rule-based baselines) to nearly 100%.

We kept the architecture and replaced the cloud:

- **The model on each drone:** a 1B-parameter text-only model in the paper → **Gemma 4 E2B**, which can see *and* reason in one pass.
- **The model at the ground station:** GPT-4.1 via OpenAI's cloud API → **Gemma 4 E4B**, served locally through Ollama. No API key, no egress.
- **The vision pipeline:** a separate computer-vision model in the paper's design → folded into Gemma 4's multimodal forward pass. One model now does what used to take two.
- **The operator interface, which the paper does not build:** a Flutter dashboard with a multilingual command box. A relief worker types in Spanish, Arabic, or Tagalog; Gemma 4 E4B turns it into a structured drone task and replies in the same language.

The validation safety net carries over unchanged. Same architecture, same safety net, zero cloud.

## 3. How It Works

A relief worker opens a web dashboard on a laptop. They type a command — *"Search the burned block north of Lake Avenue and report anyone you find"* — in their own language.

That command travels (over the laptop's loopback interface only) to the **Edge Ground Station**, where Gemma 4 E4B parses it into a structured search task, divides the area into survey points, and assigns them to the available drones. Each drone runs its own copy of Gemma 4 E2B and works through five steps in a loop: look at the camera frame, reason about what's in it, decide on an action (report a finding, mark the cell explored, request help, return to base), update its memory, and share what it learned with the swarm.

If a drone drifts out of radio range, it keeps surveying and buffers findings to disk. When it reconnects, the queue drains and the ground station deduplicates against findings it already has — a 60-second outage produces zero data loss in the dashboard.

When the demo cuts to a terminal showing zero network interfaces up, the swarm keeps operating.

*Implementation: LangGraph agents for both drones and ground station, Redis pub/sub on loopback, FastAPI WebSocket bridge to the Flutter client. The simulation tier is the only piece that would change on real hardware.*

## 4. Gemma 4 in Action

**The drones see.** A JPEG from a drone camera goes directly into Gemma 4 E2B. The same model that decides what to do is the model that interprets the image. No YOLO, no LLaVA, no glue code translating one model's output into another's input. What a drone writes about what it found is grounded in what it actually saw.

**The drones act in structured commands, not prose.** Every action is a function call against a defined schema: `report_finding`, `mark_explored`, `request_assist`, `return_to_base`, `continue_mission`. Free-form text gets rejected by a validator and the model gets a second chance. This is what makes the agent reliable enough to act on, not just chat with.

**The interface speaks 140+ languages.** A relief worker who only speaks Tagalog can drive the same swarm as an English speaker at the same incident, with no translation API and no per-character cloud fee.

**Everything runs offline.** Both Gemma 4 sizes run through a local Ollama install — Metal, CUDA, or CPU fallback. The only network endpoints in the system are `localhost`.

## 5. Catching the Hallucinations

Small language models hallucinate. In a chatbot that's annoying. In a search-and-rescue swarm it means a drone reports a victim at the wrong GPS coordinate, or the ground station assigns the same building to two drones while a third sits idle. Catastrophic when the swarm trusts peer broadcasts and the operator trusts the swarm.

The reference paper's Algorithm 1 wraps every model call in four protections: hard constraints in the prompt, a deterministic post-check, a corrective re-prompt that includes the model's failed attempt, and bounded retries with a safe fallback. We implement all four in three places: per-drone decisions, ground-station mission assignments, and operator command translation. After three failed attempts the system falls through to deterministic round-robin assignment — the swarm keeps operating even when its LLM hangs.

In the demo, the audience sees a real catch on screen: the ground station's first attempt at assigning survey points double-counts a drone, the validator rejects it with a specific complaint, the model receives the complaint as part of the next prompt, and the second attempt is correct.

**Honesty note.** Base Gemma 4 E4B doesn't hallucinate often enough in a 30-second camera window to be reliably filmable. For that one on-camera moment we use a flag that seeds the *first* attempt to be wrong; every step downstream — the validator's complaint, the second-attempt inference, the validator's acceptance — runs unmodified production code. The mechanism is real. Only the trigger is staged. Full disclosure in `docs/16-mocks-and-cuts.md`.

## 6. Teaching It to See Victims

Our hardest test was a FEMA aerial photograph from Hurricane Katrina — water, debris, and a person on a rooftop. Base Gemma 4 E2B sees a damaged building. We needed it to see the person.

We trained a 120 MB vision adapter — not a full retrain — using **Unsloth**, on the [C2A dataset](https://www.kaggle.com/datasets/rgbnihal/c2a-dataset): 10,215 UAV photographs with roughly 360,000 human instances across four disaster scenarios. We held out AIDER and SARD to test transfer to imagery it had never seen.

**Results on 400 held-out images:** 77% binary accuracy, 0.78 F1 on victim detection, 100% structured-output parse rate. Within the training domain (C2A), 97%. On the toughest cross-domain test (SARD), 55%. We publish the honest spread, not just the headline number. Public on Kaggle Models ([adapter](https://www.kaggle.com/models/ibrahimahmed7860/gemma4-e2b-victim-vision-lora-c2a), [training notebook](https://www.kaggle.com/code/ibrahimahmed7860/gemma-4-e2b-victim-vision-lora-c2a-disaster)).

## 7. What We Faked, and What We Didn't

No drone in this project has ever taken off. Drone motion is YAML waypoints interpolated in software. Camera frames are pre-recorded FEMA and USFWS aerials served from disk. The mesh radio is software dropout, not real WiFi multipath. We run 2–3 drones; the paper runs 8–12. Resilience events (drone failure, link drop, fire spread) are scripted.

What is real: every line of the agent code, the validation loop, both Gemma 4 instances doing live multimodal inference, the operator dashboard, the multilingual command path, and the offline guarantee. Swap the simulation tier for a Jetson Orin NX per drone and the rest of the stack runs unchanged. Full accounting in `docs/16-mocks-and-cuts.md`.

## 8. Run It Yourself

Any laptop with Python 3.11, Redis, and Ollama. No GPU required; no API keys; no internet after the initial model pull. `uv sync --all-extras` then `scripts/run_full_demo.sh disaster_zone_v1` launches Redis, the simulation, both Gemma 4 instances, the WebSocket bridge, and the dashboard in one tmux session. A judge can disconnect from WiFi and run the entire system.

## 9. The Stakes

The Red Cross volunteer at the Eaton Fire is not a hypothetical. The hour after a disaster strikes is the hour when AI assistance matters most — and it is exactly the hour when cloud-dependent tools stop working. FieldAgent shows the strongest published architecture for AI-driven disaster response can run entirely on-device, on a single laptop, on Gemma 4. Validation still catches hallucinations. The swarm still coordinates through dropout. The operator still drives it in their own language. Nothing in the thesis requires a network.

**Cell towers fail first. Brains shouldn't.**
