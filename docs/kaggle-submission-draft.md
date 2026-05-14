# Kaggle Submission Form — Draft

> Working draft for the Gemma 4 Good Hackathon submission. Pre-filled to the
> point where Day-16 (May 18) submission is paste-and-verify, not write-from-
> scratch. Update TBD-marked rows as content lands.
>
> Authoritative source for what must be ready by submission day:
> [`23-submission-checklist.md`](23-submission-checklist.md).

**Deadline:** May 18, 2026, 23:59 UTC (6:59 PM CDT). Submit by 6:00 PM CDT for buffer.

## Page-verified rules (https://www.kaggle.com/competitions/gemma-4-good-hackathon, 2026-05-13)

- **The Kaggle Writeup IS the submission entry.** Not a wrapper around the form fields — the Writeup itself, with attached video, code repo, live demo, and media gallery, is what gets submitted. Each team is limited to a single Writeup; un-submit / re-submit allowed any number of times before deadline. Track selection happens *inside* the Writeup at creation time.
- **Writeup hard cap: ≤1,500 words.** "Submissions over this limit may be subject to penalty." ([`../WRITEUP.md`](../WRITEUP.md) is the cut version at 1,437 words; `docs/22-writeup-draft.md` is the ~4,070-word long-form retained for reference only.)
- **Video hard cap: ≤3 minutes**, must be on YouTube, viewable without login (unlisted OK, private not). Our internal target is **1:45** per `21-demo-storyboard.md` (extended from 90s on 2026-05-13 to give Beat 5 room).
- **Live Demo:** required. URL or files attached under Writeup → Attachments → Project Links / Files.
- **Code Repository:** public (no login/paywall). GitHub link under Writeup → Attachments → Project Links.
- **Media Gallery:** cover image required to submit the Writeup at all.
- **Evaluation rubric:**
  - Impact & Vision (40 pts) — video-driven; real-world problem, inspiring vision, tangible positive change.
  - Video Pitch & Storytelling (30 pts) — exciting, engaging, well-produced; story over spec.
  - Technical Depth & Execution (30 pts) — verified by code + writeup; innovative use of Gemma 4 features; real and functional.
  - **70 points are video-driven.** Storyboard polish is the single highest-ROI activity remaining.
- **A Main Track prize and a Special Technology prize can be won by the same project.** We claim Global Resilience (Impact Track) AND Ollama AND Unsloth simultaneously where eligible.

---

## 1. Project name

`FieldAgent`

(Decision 2026-05-12: ship as "FieldAgent" alone. Matches the writeup lead,
operator-facing product name, fits single-name submission fields cleanly.
The repo stays at `Gemma-Guardian` on GitHub — repo = dev name, submission
= product name.)

## 2. One-line description (≤140 chars) / Kaggle Writeup subtitle

```
Multi-drone disaster response with on-device Gemma 4 — cell towers fail in hour one; brains shouldn't.
```

102 characters. Echoes the writeup's closing line. Kaggle Writeup requires both a title and a subtitle; this string is the subtitle.

```
Title:    FieldAgent
Subtitle: Multi-drone disaster response with on-device Gemma 4 — cell towers fail in hour one; brains shouldn't.
```

## 3. Track selection

Page-verified track structure: Main Track ($100K top-4), Impact Track ($50K split 5 ways at $10K each), Special Technology Track ($50K split 5 ways at $10K each). Track is picked inside the Writeup at creation time.

- **Impact Track slot:** **Global Resilience** ($10K). Exact Kaggle page language matches the writeup's framing: "Build the systems of tomorrow — from offline, edge-based disaster response to long-range climate mitigation."
- **Main Track:** automatic; we're in the running for the $100K top-4 alongside the Impact Track slot. No separate selection.
- **Special Technology Track claims:** Ollama ($10K) confirmed; Unsloth ($10K) conditional. See §7.
- The Safety & Trust impact slot ($10K) is not a fit — judges would weigh us against projects whose primary contribution is safety frameworks. Stick to Global Resilience.

## 4. GitHub URL

```
https://github.com/ibrahim7860/Gemma-Guardian
```

**Pre-submission verification:**
- [ ] Repo set to public (currently private during dev — flip immediately
      before submission per `23-submission-checklist.md` "Post-Submission")
- [ ] `WRITEUP.md` at repo root, committed to main (file created 2026-05-13, still untracked at time of writing — needs `git add WRITEUP.md` before Day 16)
- [ ] `LICENSE` present (Apache-2.0, ✅ already in repo)
- [ ] Demo video link landed in README + WRITEUP

## 5. Demo video URL

**TBD** — Beat 5 capture lands Day 14–15 (May 16–17). Storyboard: [`21-demo-storyboard.md`](21-demo-storyboard.md).

**Pre-submission verification:**
- [ ] Uploaded to YouTube, set to **unlisted** (publicly viewable without login)
- [ ] Mirror upload to Vimeo or another platform as backup per `23-submission-checklist.md` §Backup Plan
- [ ] Length ≤3:00 (Kaggle hard cap); internal target 1:45
- [ ] 1080p minimum, MP4 (H.264)
- [ ] Captions present throughout (judges may watch muted)
- [ ] Mobile-friendly — test on phone before submitting
- [ ] All mandatory visual elements from [`21-demo-storyboard.md`](21-demo-storyboard.md)
- [ ] 3 people unfamiliar with the project tested for "did you get it?"

## 6. Long description (paste-ready, ~300 words)

This block is paste-ready for the Kaggle Writeup body or any "describe your submission" field. It mirrors `WRITEUP.md` §§1–4 in shortened form. If a Kaggle field is shorter than 300 words, trim from the bottom up — the first paragraph + the five-substitution list are load-bearing.

```
FieldAgent is a simulated multi-drone disaster-response coordinator powered entirely
by on-device Gemma 4. We implement the edge-enabled architecture proposed in
Nguyen, Truong & Le (2026, arXiv:2601.14437) — three layers (per-drone agents,
edge ground station, operator dashboard) on a localhost message bus — with one
fundamental change: every LLM in the system runs Gemma 4 locally via Ollama,
eliminating the paper's GPT-4.1 cloud dependency. The system survives total
internet failure, which is the actual condition of post-disaster zones in the
first hour after infrastructure collapse.

Five concrete substitutions:
- Onboard LLM (paper: TinyLLaMA-1.1B int4 text-only) → Gemma 4 E2B multimodal.
  Same model reasons about and sees the scene.
- EGS LLM (paper: GPT-4.1 via OpenAI API) → Gemma 4 E4B via local Ollama.
- Cloud dependency (paper: required at EGS tier) → none anywhere; loopback only.
- Vision pipeline (paper: separate detection model) → absorbed into Gemma 4's
  native multimodal forward pass.
- Operator interface (paper: mentioned but not built) → Flutter dashboard with a
  multilingual command box that round-trips through Gemma 4 E4B for natural-
  language → structured-task translation. No translation API.

The reference paper's Algorithm 1 — constraint-conditioned re-prompting against
deterministic post-condition checks — is implemented verbatim and applied at
three loci: per-drone function calls, EGS swarm-level assignment, and operator
command translation. When Gemma 4 E4B is slow or unreachable under VRAM pressure,
the EGS falls through max-retries to a deterministic round-robin assignment so
the swarm keeps operating even when its LLM hangs.

The system runs cross-platform (macOS Metal, Linux CUDA, Windows WSL2) on
commodity laptops with 16 GB RAM. One command brings up the full stack.
The demo's closing beat cuts to a terminal showing no active network interface
while the system continues coordinating.

Full writeup: WRITEUP.md in the linked repo.
```

## 7. Special-prize claims

Page-verified rubric language for each:

- **Ollama ($10K):** *"For the best project that **utilizes and showcases** the capabilities of Gemma 4 running locally via Ollama."* **CLAIM.** Every LLM call (drone E2B + EGS E4B) flows through local Ollama; zero cloud inference path. Deployment artifacts: [`../scripts/pull_models.sh`](../scripts/pull_models.sh) + [`../ollama/Modelfile.e2b`](../ollama/Modelfile.e2b) + [`../ollama/Modelfile.e4b`](../ollama/Modelfile.e4b). Falsifiable via writeup §5.6 (loopback-only network) and the demo's closing beat (Beat 5, no active network interface while system continues coordinating).

- **Unsloth ($10K):** *"For the best fine-tuned Gemma 4 model created using Unsloth, **optimized for a specific, impactful task**."* Rubric judges on (a) used Unsloth in the training pipeline, (b) the resulting fine-tune is optimized for a *specific impactful task* (xBD post-disaster building damage classification fits this), (c) "best" — competitive against other Unsloth submissions.
  - **Claim eligibility (independent of GATE 3 outcome):** if the Unsloth training pipeline ran to completion and produced an adapter, we are eligible to claim. The rubric does not require the adapter to beat the baseline — it requires *use of Unsloth optimized for a specific impactful task*.
  - **Strength of the claim varies with outcome:**
    - **GATE 3 GO + adapter beats baseline:** strongest. Claim + writeup §6 (cut) / §7.A (long). xBD test-split numbers in the writeup.
    - **Training completed but adapter underperforms:** still claim. Honest writeup framing (hybrid §7.A methodology + "fine-tune is an enhancement, not load-bearing" framing from §7.B). Publish weights anyway per page guidance: "If training a model, publish your weights and benchmarks."
    - **Training pipeline never completed (OOM, data prep failed, etc.):** do not claim. Ship §7.B verbatim.
  - **Adapter publication:** required either way if we claim. Page says "publish your weights and benchmarks." Commit under `ml/adapters/` or host on Hugging Face / Kaggle Models with link in `ml/README.md` and the writeup.

## 8. Team members

| Name | Role | Email / GitHub |
|---|---|---|
| Ibrahim Ahmed | Project lead, Frontend, Demo, Comms | `darkmatter8789@gmail.com` / @ibrahim7860 |
| Hazim Kuniyil | Simulation Lead | TBD (verify before submit) |
| Muhammad Kaleelurrahman | Per-Drone Agent + ML | TBD |
| Qasim Bhutta | EGS / Coordination | TBD |
| Muhammad Thayyil | Simulation Co-Pilot | TBD |

**Pre-submission verification:**
- [ ] Confirm all team emails / Kaggle handles with each person (legal names matching their Kaggle profile registration)
- [ ] All team members aware of the submission window
- [ ] At least two team members can submit on behalf of the team (per `23-submission-checklist.md` backup plan)

## 9. Kaggle Writeup workflow (CONFIRMED required, page-verified 2026-05-13)

The Kaggle Writeup IS the submission entry. Hard cap **≤1,500 words**.

Submission day workflow:

1. **The cut version exists at [`../WRITEUP.md`](../WRITEUP.md)** — 1,437 words, 63 under the cap. Final-pass adjustments on submit day:
   - Confirm §6 (Fine-Tuning) reflects Kaleel's actual GATE 3 outcome (currently written as if the LoRA shipped — rewrite to honest-failure framing if NO-GO)
   - Fill in concrete numbers from demo-run telemetry if any §-by-§ statements ("near-100% coverage" / "60-second outage produces zero data loss") need backing data
   - Spell-check + read-aloud pass
2. Long-form `docs/22-writeup-draft.md` (~4,070 words) is retained for section archaeology and is NOT pasted into Kaggle.
3. Create a new Kaggle Writeup, paste `WRITEUP.md` contents.
4. Select track at creation time: **Global Resilience**.
5. Attach via the Writeup's Attachments / Media Gallery panels:
   - **Video:** YouTube, publicly viewable (unlisted OK, private not), ≤3 min, link in Media Gallery
   - **Code Repository:** GitHub URL under "Project Links"
   - **Live Demo:** under "Project Links" (URL) or "Files" (uploaded artifacts)
   - **Cover image:** required for the Writeup to be submittable at all (use a still from the video or `docs_assets/dashboard-finding-rendered.png`)
6. Hit Submit. Confirm submission appears on the team's Submissions page.

## 10. Submission acknowledgements

- [ ] I confirm acknowledgement of the competition rules (live form checkbox)
- [ ] I confirm the work is original or properly attributed (citations: Nguyen et al. paper; xBD dataset terms; FEMA Photo Library / USFWS public-domain aerial provenance)
- [ ] I confirm the team list is accurate
- [ ] I confirm the GitHub repo link works in an incognito window

## Backup-plan artifacts

Per `23-submission-checklist.md` §Backup Plan, the following must exist before Day 16:

- [x] This draft file committed to repo (you're reading it).
- [ ] Repo cloned to ≥2 separate machines.
- [ ] Video uploaded to ≥2 platforms (YouTube unlisted + Vimeo or equivalent).
- [ ] `WRITEUP.md` in 3 places (repo, Google Doc, local).
- [ ] ≥2 team members authorized to submit on team's behalf (decide who is the primary submitter and who is the backup).

## Day-16 submission runbook (compressed)

1. Verify GitHub repo is **public** and `WRITEUP.md` is at root.
2. Verify the demo video URL works in an unauthenticated browser.
3. Create the Kaggle Writeup, paste `WRITEUP.md`, select track, attach video / repo / live demo / cover image.
4. Have a second team member double-check before clicking Submit.
5. Take a screenshot of the submission confirmation.
6. Save the confirmation email to two places.
7. Verify the submission appears on the Kaggle competition's Submissions tab.

## Where each piece comes from

| Submission field | Source of truth |
|---|---|
| Project name + one-liner | this doc §1–§2 |
| Long description | this doc §6 (mirrors `WRITEUP.md` §§1–4) |
| GitHub URL | repo public flip on Day 16 morning |
| Demo video URL | Beat 5 capture (Day 14–15), uploaded to YouTube unlisted |
| Track / prize claims | this doc §3 + §7; cross-ref [`02-hackathon-context.md`](02-hackathon-context.md) |
| Team list | this doc §8 (verify with each member) |
| Cover image | docs_assets/dashboard-finding-rendered.png (or video still) |
| Acknowledgements | live form checkboxes (manual on Day 16) |

## Cross-references

- Cut writeup (the submission entry): [`../WRITEUP.md`](../WRITEUP.md)
- Long-form writeup (internal reference): [`22-writeup-draft.md`](22-writeup-draft.md)
- Day-of timeline (morning checks, afternoon submit window): [`23-submission-checklist.md`](23-submission-checklist.md) §Last 24 Hours
- Storyboard for the video URL deliverable: [`21-demo-storyboard.md`](21-demo-storyboard.md)
- Hackathon context (tracks, judging criteria, special prizes): [`02-hackathon-context.md`](02-hackathon-context.md)
