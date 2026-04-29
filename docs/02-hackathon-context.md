# 02 — Hackathon Context

## The Competition

**Gemma 4 Good Hackathon**
- Hosted by: Kaggle × Google DeepMind
- Prize pool: $200,000 USD
- Start date: April 2, 2026
- **Submission deadline: May 18, 2026, 23:59 UTC**
- URL: https://www.kaggle.com/competitions/gemma-4-good-hackathon

## The Five Tracks

1. **Future of Education** — personalized learning, educator tools
2. **Health and Sciences** — medical research, patient care, health literacy
3. **Digital Equity** — accessibility for underserved communities
4. **Global Resilience** — climate, disaster, sustainability (special Climate & Green Energy sub-track)
5. **Safety** — protective applications

## Our Track Strategy

- **Primary submission:** Global Resilience (with Climate & Green Energy framing — disasters as climate-driven, drone swarms as resilience infrastructure)
- **Secondary fit:** Safety
- **Special prize plays:**
  - **Unsloth prize:** fine-tune Gemma 4 vision component on xBD building damage dataset
  - **Ollama prize:** entire system runs via Ollama instances locally

## Judging Criteria (Confirmed)

From the official competition description and analyst commentary:

- **Social impact** — does this solve a real problem for real people?
- **Technical innovation** — does this leverage Gemma 4's multimodal capabilities and native function calling effectively?
- **Ability to operate in constrained environments** — low bandwidth, no cloud, privacy-sensitive
- **Working prototype required** — not a deck, not a mocked UI, an actual demo
- **Public code repository** — open and reproducible
- **Technical write-up** — explaining how Gemma 4 is applied
- **Short video** — demonstrating real-world use

## What Wins (and What Loses)

The strongest published analysis of this hackathon called out the failure modes explicitly:

> "The competition is not asking for generic demos. It is asking for solutions that could actually help people in the real world. The winners will not necessarily be the people with the most complicated architecture. Not vague. Not trendy. Not theoretical. Not a fake UI. Not a mocked-up chatbot. The people who win these things are usually not the ones with the flashiest idea. They're the ones who actually finish something that matters."

Concrete signals from this analysis:

- **Surface-level prompting is a losing strategy.** "You can improve performance for a specific task rather than relying only on generic prompting." This is the explicit pointer toward fine-tuning. See [`12-fine-tuning-plan.md`](12-fine-tuning-plan.md).
- **Realistic resource-constrained settings matter.** Demo must show the offline / on-device claim, not just assert it.
- **Finish > impress.** A working narrow prototype beats a half-finished ambitious one.

## Lessons from the Predecessor (Gemma 3n Impact Challenge)

Eight winners from the previous hackathon shared traits we should replicate:

1. **One specific person's story** anchored each project (not "millions of people" — a named user)
2. **On-device deployment** was non-negotiable for every winner
3. **Vision was the primary input** for most winners
4. **Flutter was used by the 1st place winner** (flutter_gemma)
5. **Ollama and Unsloth special prizes were claimed** by projects that genuinely used those tools
6. **Working hardware demos** beat polished software demos

The 1st place project (Gemma Vision) used a chest-mounted phone camera, an 8BitDo controller, and flutter_gemma — physically functional, emotionally resonant, technically credible.

## What This Means for Our Submission

We need:

- **A specific operator story** for the demo — name them, show their face, give them a context (a fictional Red Cross volunteer in a wildfire response works)
- **The offline claim demonstrated, not asserted** — terminal showing no internet, airplane-mode laptop in some shot
- **Vision as primary input** — drone cameras driving the agentic loop
- **Function calling visible on screen** — the structured outputs aren't just used, they're shown
- **Validation loop catching a hallucination on camera** — the technical innovation moment
- **Multilingual command moment** — operator speaks Spanish, system responds correctly
- **Resilience moment** — drone fails, swarm continues

## Deliverables Required

- [ ] Working code in a public GitHub repository
- [ ] 90-second (or shorter) demo video
- [ ] Technical write-up explaining Gemma 4 usage (Markdown in repo + Kaggle submission)
- [ ] Reproducibility instructions (README with setup steps)
- [ ] Submission via Kaggle by May 18, 2026, 23:59 UTC

## What Each Track Submission Looks Like

We are submitting under one primary track (Global Resilience). The submission needs to:

1. Open with the Global Resilience narrative (disaster, climate, infrastructure failure)
2. Position the technical work as enabling that mission
3. Make the Climate & Green Energy connection explicit (climate-driven disasters, off-grid operation)
4. Demonstrate the Safety crossover (responder safety, victim safety) without diluting the primary frame

For special prizes, we will note the Unsloth and Ollama angles in the writeup but the core narrative stays focused.
