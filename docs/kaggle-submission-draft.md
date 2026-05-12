# Kaggle Submission Form — Draft

> Working draft for the Gemma 4 Good Hackathon submission. Pre-filled to the
> point where Day-16 (May 18) submission is paste-and-verify, not write-from-
> scratch. Update TBD-marked rows as content lands.
>
> Verify the live Kaggle form before submission; field names may shift.
> Authoritative source for what must be ready:
> [`23-submission-checklist.md`](23-submission-checklist.md).

---

## 1. Project name

`Gemma-Guardian / FieldAgent`

(README and writeup both use the dual name. Pick the one Kaggle prefers if
the field allows only one — recommend "FieldAgent" if so, since it's shorter
and what the writeup leads with.)

## 2. One-line description (≤140 chars)

> Multi-drone disaster-response coordinator that runs entirely on-device with
> Gemma 4 — survives the cell-tower failures that disable cloud-AI drones.

*(138 chars including the period. Verify the live form's exact limit.)*

## 3. Track selection

- **Primary:** Global Resilience
- **Secondary:** Safety
- Special-track framing: Climate & Green Energy (per [`docs/02-hackathon-context.md`](02-hackathon-context.md))

## 4. GitHub URL

`https://github.com/ibrahim7860/Gemma-Guardian`

**Pre-submission verification:**
- [ ] Repo set to public (currently private during dev — flip immediately
      before submission per `23-submission-checklist.md` "Post-Submission")
- [ ] `WRITEUP.md` promoted from `docs/22-writeup-draft.md` to repo root
- [ ] `LICENSE` present (Apache-2.0, ✅ already in repo)
- [ ] Demo video link landed in README + WRITEUP

## 5. Demo video URL

**TBD** — Beat 5 capture not yet final. Target: Day 15 (May 17).

**Pre-submission verification:**
- [ ] Uploaded to YouTube, set to **unlisted** (NOT private, NOT public)
- [ ] Mirror upload to Vimeo or another platform as backup
- [ ] Length ≤90 seconds (hard cap)
- [ ] 1080p minimum, MP4 (H.264)
- [ ] Captions present throughout (judges may watch muted)
- [ ] Mobile-friendly — test on phone before submitting
- [ ] All mandatory visual elements from [`21-demo-storyboard.md`](21-demo-storyboard.md)
- [ ] 3 people unfamiliar with the project tested for "did you get it?"

## 6. Long description (Kaggle "describe your submission" field)

Paste a 200-400 word excerpt from `WRITEUP.md`. Recommended seed text:

> **FieldAgent: offline multi-drone disaster response with Gemma 4.**
>
> Post-disaster zones lose cell towers in the first hour. Drones with
> cloud-AI dependencies become useless when they're needed most. We took
> the strongest published architecture for AI-driven disaster response
> (Nguyen, Truong, Le, 2026 — *Agentic AI Meets Edge Computing in Autonomous
> UAV Swarms*, arXiv:2601.14437) and removed its cloud GPT-4.1 dependency.
> Every drone runs **Gemma 4 E2B** on-device for perception; the **Edge
> Ground Station** runs **Gemma 4 E4B** for command translation and mission
> replanning. Both via Ollama. Zero cloud.
>
> The system survives:
>
> - Total internet failure (cloud unreachable from `t=0`)
> - Drone-to-drone mesh dropout (simulated via Redis-side range filter)
> - EGS link loss (drones detect via heartbeat, buffer findings, replay on
>   reconnect)
> - Individual drone failure (EGS replans surviving drones via a
>   deterministic fallback if Gemma is slow)
>
> Function calling is the agentic backbone: every action-driving output is
> a structured JSON tool call validated against hard constraints, with a
> corrective re-prompt loop on failure (Algorithm 1 from the reference paper).
> 720+ unit + integration tests cover the validation surface. The operator
> dashboard (Flutter web) talks to the swarm through a FastAPI WebSocket
> bridge that mirrors Redis channels — multilingual command input,
> translated by Gemma 4 E4B, previewed in the operator's language before
> dispatch.
>
> The included scripts/run_full_demo.sh launches the entire stack end-to-end
> on a single laptop in under a minute. We've tested cold-start reproduction
> on macOS M1, Linux, and Windows 11 (WSL2).

## 7. Special-prize claims

| Prize | Claim? | Why | Verification |
|---|---|---|---|
| **Unsloth** | TBD (gated on Kaleel's GATE 3 LoRA decision today) | Vision-adapter fine-tune on xBD post-disaster imagery, rank 32, all-linear, vision layers frozen on first pass | LoRA adapter committed to `ml/adapters/` or hosted on Hugging Face / Kaggle Models with link in `ml/README.md` and `WRITEUP.md` |
| **Ollama** | YES | Every Gemma 4 invocation goes through Ollama (E2B on each drone, E4B at EGS); deployment shipped via `Modelfile` + `scripts/pull_models.sh` | See `23-submission-checklist.md` checklist item under "Code organization" |

## 8. Team members

| Name | Role | Email / GitHub |
|---|---|---|
| Ibrahim Ahmed | Project lead, Frontend, Demo, Comms | `darkmatter8789@gmail.com` / @ibrahim7860 |
| Hazim Kuniyil | Simulation Lead | TBD (verify before submit) |
| Kaleel | Per-Drone Agent + ML | TBD |
| Qasim | EGS / Coordination | TBD |
| Thayyil | Simulation Co-Pilot | TBD |

**Pre-submission verification:**
- [ ] Confirm all team emails/handles with each person
- [ ] All team members aware of the submission window
- [ ] At least two team members can submit on behalf of the team (per
      `23-submission-checklist.md` backup plan)

## 9. Kaggle Writeup / notebook

The hackathon checklist flags this:

> Verify against the live Kaggle competition page whether a Kaggle Writeup /
> notebook is required as the submission entry (Kaggle hackathons usually
> require this). If yes: publish a Kaggle Writeup mirroring `WRITEUP.md` and
> link the GitHub repo + video from inside it.

**Pre-submission verification:**
- [ ] Check Kaggle competition page on Day 14 (May 16) — is a Writeup
      notebook required?
- [ ] If yes: create the Writeup as a copy of `WRITEUP.md`, ensure the
      content fits Kaggle's markdown rendering (no raw HTML the page won't
      render)
- [ ] Embed the demo video link + GitHub link inside the Writeup
- [ ] Mark the Writeup as the official submission entry

## 10. Submission acknowledgements

- [ ] I confirm acknowledgement of the competition rules (live form
      checkbox)
- [ ] I confirm the work is original or properly attributed (citations:
      Nguyen et al. paper; xBD dataset terms; FEMA Photo Library / USFWS
      public-domain aerial provenance)
- [ ] I confirm the team list is accurate
- [ ] I confirm the GitHub repo link works in an incognito window

## Day-16 submission runbook (compressed)

1. Verify GitHub repo is **public** and `WRITEUP.md` is at root.
2. Verify the demo video URL works in an unauthenticated browser.
3. Paste each field from this draft into the live Kaggle form.
4. Have a second team member double-check before clicking Submit.
5. Take a screenshot of the submission confirmation.
6. Save the confirmation email to two places.
7. Verify the submission appears on the Kaggle competition's Submissions
   tab.

## Where each piece comes from

| Submission field | Source of truth |
|---|---|
| Project name + one-liner | this doc |
| Long description | `WRITEUP.md` §1 (problem framing) |
| GitHub URL | repo public flip on Day 16 morning |
| Demo video URL | Beat 5 capture (Day 14-15), uploaded to YouTube as unlisted |
| Track / prize claims | `docs/02-hackathon-context.md` + this doc §7 |
| Team list | this doc §8 (verify with each member) |
| Acknowledgements | live form checkboxes (manual on Day 16) |
