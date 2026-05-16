# Kaggle Submission Form — Field-by-Field Values

**Purpose:** Copy-paste sheet for Kaggle submission day (Mon May 18, 2026). Each section below maps 1:1 to a field on the Kaggle Gemma 4 Good Hackathon submission form. Source: `docs/23-submission-checklist.md` L175-190.

**Owner on the day:** Thayyil (submission ops), with Ibrahim reviewing pre-submit.

**Last drafted:** 2026-05-16. Verify against the live Kaggle page before pasting — Kaggle may add/rename fields between now and Mon AM.

---

### Field: Project name

```
FieldAgent
```

(13 characters)

---

### Field: One-line description (≤140 chars)

```
On-device Gemma 4 turns a drone swarm into an offline disaster-response coordinator — every brain local, every decision survives the blackout.
```

(140 characters — at the cap, verify in the Kaggle text input before saving in case their counter differs by a char.)

**Backup shorter version (124 chars) if the form rejects 140:**

```
On-device Gemma 4 turns a drone swarm into an offline disaster-response coordinator. Every brain local. No cloud needed.
```

---

### Field: Track selection

**Primary:** Global Resilience

**Secondary (if the form supports multi-select):** Safety

**Special-track framing (in long description, not a separate field):** Climate & Green Energy

---

### Field: GitHub URL

```
https://github.com/ibrahim7860/Gemma-Guardian
```

(Resolved from `README.md` citation block L142.)

---

### Field: Demo video URL

```
[TBV — fill Mon AM after Sun YouTube upload]
```

**Where to get it:** Ibrahim uploads the final Beat-5 cut to YouTube on Sun May 17 (Day 15 lock day). Submission video link placeholder is already in `README.md` L15 — update both that line and this file simultaneously on Mon AM.

---

### Field: Long description excerpt

**Paste the following (excerpt from `WRITEUP.md` §1 — Problem):**

```
In post-disaster zones, cell towers fail in the first hour. Existing AI-powered drone platforms (Skydio, Shield AI, Auterion) require backhaul connectivity for any non-trivial reasoning. Even the most advanced published architecture for AI-driven disaster response — Nguyen, Truong & Le (2026, arXiv:2601.14437) — assumes GPT-4.1 over the public internet at the edge ground station: a cloud dependency at the tier where the cloud isn't reachable.

We removed it. FieldAgent is a multi-drone disaster-response coordinator powered entirely by on-device Gemma 4. Every drone runs a five-node LangGraph agent driven by Gemma 4 E2B (multimodal: it both reasons and sees). The edge ground station runs Gemma 4 E4B via local Ollama. The Flutter operator dashboard talks to a FastAPI WebSocket bridge over loopback. Every network call is localhost. The system survives total internet failure, which is the actual condition of post-disaster zones.

Function calling is the agentic backbone, not a postprocessing step. Every action-driving output is a structured function call validated against a JSON schema with a corrective re-prompt on failure (Algorithm 1 from the reference paper). On top of base Gemma 4 E2B, we ship a victim-detection LoRA fine-tuned via Unsloth on the C2A disaster-aerial dataset — published as a public Kaggle Model (77.25% binary accuracy, 0.78 F1 on held-out eval).
```

(Word count: ~210 words. If Kaggle's long-description field is shorter, trim from the second paragraph first, keep the §1 hook and the LoRA closer.)

**If Kaggle wants the full writeup pasted instead of an excerpt:** point them to `WRITEUP.md` (≤1,500 words, that's the canonical Kaggle Writeup body). Do NOT paste `docs/22-writeup-draft.md` (~4,070 words — over the cap).

---

### Field: Special prize — Unsloth

**Status:** **CLAIMED (GO)**

**Justification (paste into the form's claim-reason field if one exists):**

```
We trained a Gemma 4 E2B vision-tower LoRA via Unsloth on the C2A disaster-aerial victim-detection dataset. The adapter is published as a public Kaggle Model and runs in-process inside the drone agent (PEFT/HF Transformers route — see Special prize: Ollama section for why we did not go through Ollama Modelfile). Held-out eval: 77.25% binary accuracy, 0.78 F1.

Kaggle Model: https://www.kaggle.com/models/ibrahimahmed7860/gemma4-e2b-victim-vision-lora-c2a
Training Notebook: https://www.kaggle.com/code/ibrahimahmed7860/gemma-4-e2b-victim-vision-lora-c2a-disaster
Adapter version: lora-c2a-bf16/3
```

---

### Field: Special prize — Ollama

**Status:** **NOT CLAIMED — leave checkbox unchecked.**

**Reason (internal — do not paste into form unless Kaggle has a "why not?" field):**

Per the G4-late routing decision: we chose route (b) PEFT/HF Transformers in-process loading over route (a) Ollama Modelfile + GGUF for the C2A adapter. The Unsloth GGUF vision-tower export is blocked on upstream issue `unslothai/unsloth#2290`. We deploy *Gemma 4* via Ollama (both E2B onboard and E4B at EGS), but the fine-tuned adapter does not flow through Ollama, so we are not claiming the Ollama prize. Honest non-claim > overclaim.

---

### Field: Team member names

**Paste exactly:**

```
- Ibrahim Ahmed — Project Lead, Frontend + Demo + Comms (Flutter dashboard, FastAPI WebSocket bridge, demo video, technical writeup)
- Hazim Kuniyil — Simulation Lead (sim/waypoint_runner, frame_server, mesh_simulator, launch scripts, Redis infra)
- Muhammad Kaleelurrahman — Per-Drone Agent + ML (LangGraph drone agent, Gemma 4 E2B function calling, C2A/xBD LoRA fine-tuning via Unsloth)
- Qasim Bhutta — EGS / Coordination (Gemma 4 E4B LangGraph coordinator, survey-point assignment, multilingual command path)
- Muhammad Thayyil — Simulation Co-Pilot + Submission Ops (paired with Hazim — frame library curation, scenario YAML, submission day execution)
```

(Full names resolved from `WRITEUP.md` L3 byline. Verify spelling with each teammate before final submit.)

---

### Field: Acknowledgement of competition rules

```
☐ check at submission time
```

**Note for Thayyil:** Do not pre-tick; Ibrahim ticks this himself on Mon May 18 AM after a final read-through of the Kaggle competition rules page. Re-verify the page hasn't changed since last review (Kaggle sometimes pushes terms updates close to deadline).

---

### Field: Kaggle Writeup / Notebook entry (if required)

**Per checklist L190:** Verify on the live Kaggle competition page whether a Kaggle Writeup or notebook is the submission entry vehicle (Kaggle hackathons usually require this).

**If yes:**

- Kaggle Writeup body source: `docs/submission/kaggle_writeup_body.md` (mirrors `WRITEUP.md`)
- Linked from inside the Writeup: GitHub repo URL above + Demo video URL above

---

## Pre-submit checklist for Thayyil (Mon May 18 AM)

- [ ] Demo video URL is filled in (replaces `[TBV — fill Mon AM after Sun YouTube upload]`)
- [ ] YouTube video set to **Unlisted** or **Public** (NOT Private — judges can't see private)
- [ ] One-line description fits Kaggle's actual character counter (paste, watch the counter, don't trust the count here)
- [ ] GitHub repo is **public** and the `main` branch contains everything cited above
- [ ] Kaggle Model `lora-c2a-bf16/3` is **public** (not draft/private)
- [ ] Kaggle Notebook `gemma-4-e2b-victim-vision-lora-c2a-disaster` is **public**
- [ ] All five teammate names spelled correctly (cross-check with each person)
- [ ] Ibrahim has reviewed this file end-to-end and signed off in chat
- [ ] Rules acknowledgement ticked by Ibrahim, not by Thayyil
