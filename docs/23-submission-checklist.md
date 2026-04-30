# 23 — Submission Checklist

## Why This Doc Exists

Per [`19-day-by-day-plan.md`](19-day-by-day-plan.md), Day 15 (Sat May 16, polish + final video edit) and Day 16 (Sun May 18, GATE 5 + SUBMIT by 23:59 UTC) require everything to be ready. This doc is the literal checklist. Print it, check items off, post in the team channel.

Note: the recalibrated schedule in `19-day-by-day-plan.md` collapses lock day and submission day into the same Day 16 (May 18). There is no separate "Day 17" or "Day 18" in the real schedule — those existed only in the earlier draft. The "Last 24 Hours" section below maps onto Day 15 (May 17) → Day 16 (May 18).

## Submission Deadline

**May 18, 2026, 23:59 UTC**

Convert to Central Time (DFW): **6:59 PM CDT, May 18, 2026.**

Submit by 6:00 PM CDT to leave 1 hour of buffer.

## Submission Channels

1. **Kaggle competition page:** primary submission
2. **GitHub repository:** public, link in submission
3. **Demo video:** uploaded to YouTube (unlisted), link in submission
4. **Technical writeup:** in repo as `WRITEUP.md` and pasted into Kaggle submission

## Repository Checklist

The GitHub repo at submission time:

### Top-level files
- [ ] `README.md` — public-facing project description (different from CLAUDE.md)
- [ ] `WRITEUP.md` — the technical writeup
- [ ] `LICENSE` — Apache 2.0
- [ ] `CLAUDE.md` — left in for context (optional but recommended)

### Code organization
- [ ] `simulation/` — software sim world definitions, scripted waypoint motion
- [ ] `agents/drone_agent/` — drone agent code
- [ ] `agents/egs_agent/` — EGS coordinator code
- [ ] `agents/mesh_simulator/` — mesh dropout simulator
- [ ] `shared/schemas/` — JSON Schema files
- [ ] `shared/prompts/` — all prompt templates
- [ ] `frontend/flutter_dashboard/` — Flutter web app
- [ ] `ml/` — fine-tuning code (if applicable)
- [ ] LoRA adapter artifact published if Gate 3 passed — either committed under `ml/adapters/` (if size allows) or hosted on Hugging Face / Kaggle Models with a link in `ml/README.md` and `WRITEUP.md`. Required for the Unsloth special-prize claim.
- [ ] `scripts/` — launch and demo scripts
- [ ] Ollama deployment artifact — `Modelfile`(s) for E2B and E4B (and the fine-tuned adapter if Gate 3 passed) plus a `scripts/pull_models.sh` or equivalent. Required for the Ollama special-prize claim.
- [ ] `docs/` — all detailed documentation

### Code quality
- [ ] No commented-out code blocks
- [ ] No `print` debugging statements
- [ ] No hardcoded paths to your home directory
- [ ] No API keys or secrets in any file (verify with `git secrets` or manual scan)
- [ ] All code formatted (Black for Python, dartfmt for Flutter)
- [ ] At least basic docstrings on public functions

### Documentation completeness
- [ ] README explains what the project is
- [ ] README has a "Quick Start" with single-command demo
- [ ] README links to the demo video
- [ ] README links to the writeup
- [ ] README cites the reference paper
- [ ] WRITEUP.md is complete

### Reproducibility
- [ ] `scripts/setup.sh` installs all dependencies
- [ ] `scripts/run_full_demo.sh` runs the demo end-to-end
- [ ] Reproduction instructions tested by someone other than the writer
- [ ] Required Python packages in `requirements.txt` (or `pyproject.toml`)
- [ ] Flutter dependencies in `pubspec.yaml`

## README.md Template

```markdown
# FieldAgent

Offline multi-drone disaster response coordination with Gemma 4.

[![Watch the demo](thumbnail.png)](video_url)

## What It Is

FieldAgent is a simulated UAV swarm that coordinates disaster response 
entirely offline, using Gemma 4 running locally on every drone and at 
the edge ground station. It implements the architecture proposed in 
Nguyen, Truong & Le (2026) [arXiv:2601.14437] with the cloud LLM 
dependency replaced by on-device Gemma 4.

## Demo Video

[90-second demonstration](video_url)

## Quick Start

```bash
git clone https://github.com/your-org/fieldagent.git
cd fieldagent
bash scripts/setup.sh
bash scripts/run_full_demo.sh
```

Open the dashboard at `http://localhost:8080`.

## Hardware Requirements (for reproduction)

- Cross-platform: macOS, Linux, or Windows (native or WSL2)
- 16 GB RAM minimum (32 GB recommended for running two Ollama instances simultaneously)
- 50 GB free disk
- NVIDIA GPU optional; Ollama runs on CPU, Metal (macOS), or CUDA

## What's Inside

- Software-only Python multi-drone simulation (Redis pub/sub, scripted waypoint motion)
- Per-drone agents running Gemma 4 E2B via Ollama
- Edge Ground Station running Gemma 4 E4B
- Flutter web dashboard with multilingual operator commands
- LangGraph orchestration with validation-and-retry loop

See [WRITEUP.md](WRITEUP.md) for the technical deep-dive.

## Hackathon

Submitted to the Gemma 4 Good Hackathon (Kaggle × Google DeepMind, 
May 2026). Tracks: Global Resilience (primary), Safety (secondary).

## License

Apache 2.0. See [LICENSE](LICENSE).

## Citation

If you build on this work, please cite:

```
@misc{fieldagent2026,
  title={FieldAgent: Offline Multi-Drone Disaster Response with Gemma 4},
  author={...},
  year={2026},
  url={https://github.com/your-org/fieldagent}
}
```

And the reference paper:

```
Nguyen, T. M., Truong, V. T., & Le, L. B. (2026). 
Agentic AI Meets Edge Computing in Autonomous UAV Swarms. 
arXiv:2601.14437.
```
```

## Video Checklist

- [ ] Length: ≤90 seconds (hard cap)
- [ ] Resolution: 1080p minimum
- [ ] Format: MP4 (H.264)
- [ ] Audio: clear, no clipping (or muted with strong captions)
- [ ] Captions: present throughout
- [ ] Hosted on YouTube, set to **unlisted** (not private, not public)
- [ ] All mandatory visual elements from [`21-demo-storyboard.md`](21-demo-storyboard.md) present
- [ ] Test: 3 people unfamiliar with the project understand it after watching
- [ ] Test: video works on mobile (judges may watch on phone)

## Writeup Checklist

- [ ] Length: 2,000-4,000 words
- [ ] All sections from [`22-writeup-outline.md`](22-writeup-outline.md) present
- [ ] Reference paper cited in academic format
- [ ] Tables with actual measured numbers (not "TBD")
- [ ] Honest limitations section
- [ ] Reproducibility section
- [ ] Spell-checked
- [ ] Grammar-checked (Grammarly or similar)
- [ ] Read aloud for flow

## Kaggle Submission Form

Required fields (verify on Kaggle):

- [ ] Project name: "FieldAgent"
- [ ] One-line description (≤140 chars)
- [ ] Track selection: Global Resilience (primary)
- [ ] GitHub URL
- [ ] Demo video URL
- [ ] Long description (paste relevant excerpt from WRITEUP.md)
- [ ] Special prize claims:
  - [ ] Unsloth (if fine-tuning succeeded)
  - [ ] Ollama (deployment via Ollama)
- [ ] Team member names
- [ ] Acknowledgement of competition rules
- [ ] Verify against the live Kaggle competition page whether a **Kaggle Writeup / notebook** is required as the submission entry (Kaggle hackathons usually require this). If yes: publish a Kaggle Writeup mirroring `WRITEUP.md` and link the GitHub repo + video from inside it.

## Last 24 Hours: What Happens

### Day 15 (May 17, Sunday): Lock Day -1

- Final video editing
- Final writeup pass
- Reproduction test by Person 1 (clean machine if possible)
- Test demo on a different machine if available
- Fix anything broken; no new features

### Day 16 (May 18, Monday): Submission Day

**Morning (9 AM CDT):**
- Final reproducibility check
- Verify all video links work
- Verify all repo links work
- Read the writeup one more time
- Commit anything outstanding to main branch
- Tag a release: `v1.0-submission`

**Afternoon (1-4 PM CDT):**
- Fill out Kaggle submission form
- Have one team member double-check it
- Submit
- Verify submission appears on Kaggle

**Evening (after submission):**
- Celebrate
- Backup repo to private storage in case Kaggle/GitHub goes down
- Save submission confirmation email

## Backup Plan

In case of catastrophic failure on submission day:

- [ ] Repo cloned to at least 2 separate machines
- [ ] Video uploaded to at least 2 platforms (YouTube + Vimeo or backup)
- [ ] Writeup in 3 places (repo, Google Doc, local)
- [ ] Kaggle submission form prepared as a draft text file in advance
- [ ] At least 2 team members can submit on behalf of the team

## What If We're Not Ready

If on Day 18 morning, deliverables aren't ready:

1. Submit what we have. Honest writeup about limitations is better than missing the deadline.
2. Pre-record a "what we built so far" video as backup.
3. Submit early; iterating after submission isn't allowed.

The deadline is hard. Late submissions are rejected.

## Post-Submission

Immediately after submission:

- [ ] Make repo public (if private during dev)
- [ ] Tweet / post about the project
- [ ] Update LinkedIn / portfolio
- [ ] Keep monitoring Kaggle for any submission issues

Within 1 week:

- [ ] Write a retrospective doc (`docs/RETRO.md`): what worked, what didn't
- [ ] Thank the team
- [ ] Whatever happens with judging, this is a portfolio piece

## Cross-References

- The day-by-day plan that builds toward this checklist: [`19-day-by-day-plan.md`](19-day-by-day-plan.md)
- The video being submitted: [`21-demo-storyboard.md`](21-demo-storyboard.md)
- The writeup being submitted: [`22-writeup-outline.md`](22-writeup-outline.md)
- The hackathon submission requirements: [`02-hackathon-context.md`](02-hackathon-context.md)
