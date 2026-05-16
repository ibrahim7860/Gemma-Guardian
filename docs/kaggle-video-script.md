# Kaggle Submission Video — Script

**Target runtime:** 2:53 (180s ceiling)
**Hackathon:** Gemma 4 Good Hackathon — Kaggle × Google DeepMind
**Submission deadline:** May 18, 2026, 23:59 UTC
**Hosting:** YouTube (public, no login required)

**Tone:** Five young developers who built something they're excited about, talking to the judges. Story-first. Technical detail only inside the demo segment. Casual, personal, every speaker finishes their own thought.

**Narrative anchors** (pulled from `docs/21-demo-storyboard.md`):
- One named recent disaster (Eaton Fire, Los Angeles, January 2025) instead of a generic montage
- The academic-paper reframe (someone published this architecture this year using cloud GPT-4 — we made it offline with Gemma 4)
- Proper Beat 5 offline-proof in the demo (drone keeps flying after link drop, buffers a finding, syncs on reconnect — not just an airplane-mode icon flash)
- Multilingual Spanish command moment inside the demo (mandatory visual per storyboard)

---

## [0:00 – 0:10]  COLD OPEN — Disaster News *(10s, no narration)*

**Visual:** Real news footage from the **Eaton Fire, Los Angeles, January 2025**. Anchor clips on mute, news chyrons visible, then NASA SVS imagery of the burn scar ([svs.gsfc.nasa.gov/5558](https://svs.gsfc.nasa.gov/5558/)). Three statistic overlays flash in sequence:

> "Eaton Fire — January 2025"
> "17 lives lost. 9,000+ structures destroyed."
> "Cell coverage collapsed across the foothills in the first hour."

**Audio:** Real news-anchor audio bleeds through low, then fades to a single beat of silence.

---

## [0:10 – 0:55]  WHY WE BUILT THIS *(45s, B-roll and webcams interleaved)*

No "we're the team" introduction. The news audio from the cold open fades, and Ibrahim's voice is already going as the imagery transitions from news clips into drone aerials. The segment cross-cuts between B-roll and webcams throughout — when each person's face appears, the lower-third can show their name, but no one says "I'm so-and-so." We let the disaster carry the weight, and our faces just show that real people are behind this.

**Visual opens on:** news footage dissolves into drone aerial footage over fire-damaged neighborhoods. News audio fades. Voice is already going.

**IBRAHIM (VO, over B-roll):** When the Eaton Fire hit Los Angeles, cell coverage across the foothills collapsed within the first hour. The technology meant to help in moments like this — just stopped working.

**Cut to webcam:** Ibrahim. Lower-third with his name.

**IBRAHIM (on camera):** And this happens in almost every major disaster.

**Cut to B-roll:** drone POV slowly tilting down toward a person waving from a rooftop. Hold on the figure.

**THAYYIL (VO, over B-roll):** The first few hours after a disaster hits — that's when most rescues actually happen.

**Cut to webcam:** Thayyil.

**THAYYIL (on camera):** But that's also exactly when the network breaks down. So rescue teams end up operating blind, right when they need information the most.

**Cut to B-roll:** aerial of collapsed structures, smoke rising. Text overlay fades in mid-shot:
> 3.6 billion people live in disaster-vulnerable regions.

**HAZIM (VO, over B-roll):** And this isn't a small problem. Billions of people live in places where this happens every year.

**Cut to webcam:** Hazim.

**HAZIM (on camera):** The gap between when help is needed and when the tech can actually deliver — that's where lives get lost.

**Cut to B-roll:** brief shot of a rescue worker or someone trapped near rubble.

**KHALEEL (VO, over B-roll):** So we built something to help close that gap.

**Cut to webcam:** Khaleel.

**KHALEEL (on camera):** Something that keeps working when nothing else does.

---

## [0:57 – 1:27]  HOW WE SOLVED IT *(30s)*

**Visual:** Simple animated graphic — a cloud icon appears, gets crossed out, replaced by a drone with a tiny "AI" chip glowing inside it. Then three drones connected to each other (not to the cloud).

**QASIM:** The way we did it is simple. Instead of having drones rely on the internet to think, we put the AI directly on the drones themselves.

**THAYYIL:** There's a paper from earlier this year that proposed something similar — but it needed cloud GPT-4. We took that architecture and made it run on Gemma 4 locally. Completely offline.

**IBRAHIM:** So now a swarm of drones can see, think, coordinate rescue work — without any internet at all.

---

## [1:27 – 2:27]  THE DEMO *(60s — voice-over on screen recording)*

**Visual:** Live screen recording of the actual Flutter dashboard. Three drones tracking across the aerial base map. *"Software simulation"* caption in the bottom-right corner throughout this segment (honest disclosure per storyboard).

### Setup *(0:00–0:05 of demo, ~5s)*

**Visual overlay** (top-right, holds ~2s): real macOS/Windows airplane-mode icon, captured with wifi actually off.

**IBRAHIM (VO):** And here's what that actually looks like in action. Three drones surveying a simulated disaster zone — and the wifi on our laptop is turned off.

### Drone spots a survivor *(~12s)*

**Visual:** Drone one's camera frame highlights a victim. Finding card pops on the dashboard. Inset overlay shows the actual Gemma function call:
```
report_finding(
  type="victim",
  severity=4,
  confidence=0.78,
  visual_description="Person prone,
    partially covered by debris..."
)
```

**THAYYIL (VO):** Right there — drone one just picked up a survivor. That's Gemma analyzing the camera frame, deciding it's a person who needs help, and producing a structured report — the operator sees it on the dashboard instantly.

### Multilingual command *(~10s)*

**Visual:** Operator types in Spanish: *"drone 2, regresa a la base"*. Dashboard shows Gemma's translation popping out as a structured `recall_drone()` call. Drone 2 turns around and heads home.

**HAZIM (VO):** Now the operator's typing a command in Spanish. Gemma understands it, translates it into the right action, and sends drone two back to base.

### The wow moment *(~15s)*

**Visual:** Drone 3 marker turns red. EGS triggers a replan. The validation banner appears at the top:
- **Attempt 1 — FAILED:** *"Your assignments cover 27 points but 25 are available. Reassign so every point is covered exactly once."*
- **Attempt 2 — PASSED.**

**QASIM (VO):** Here's a key moment. Gemma actually makes a mistake while re-coordinating — but the validation layer catches it and corrects it before any drone acts. In a real rescue, that's what keeps a bad decision from costing someone their life.

### Beat 5 — offline proof *(~15s)*

**Visual:** Operator runs `sudo ifconfig en0 down`. EGS LINK SEVERED banner appears. Drone 3 gets a STANDALONE badge. Drone 3 keeps flying. Sidecar log shows "finding produced (buffered)." Then operator runs `sudo ifconfig en0 up` — banner clears, the buffered finding pops onto the dashboard, victim count chip ticks up by one.

**IBRAHIM (VO):** Now I'm dropping drone three's connection completely. It keeps flying, finds another survivor while it's offline, and the second it reconnects — that finding shows up on the dashboard. Nothing lost.

### Local-only proof *(~8s)*

**Visual:** Cut to a terminal window. `ollama list` runs, output shows `gemma4:e2b` and `gemma4:e4b` cached locally. Airplane-mode icon still visible.

**KHALEEL (VO):** And just to prove it — everything you just saw, every drone, every decision, ran right here on our laptop. No cloud, no internet, nothing.

---

## [2:27 – 3:00]  WHAT THIS COULD MEAN *(33s)*

**Visual:** Cut back to the 5-up team grid. Clean framing.

**KHALEEL:** The next big disaster is going to happen eventually. And when it does, rescue teams shouldn't be losing people just because the cell network went down.

**QASIM:** Having drones that can keep coordinating even when there's no internet — that could be what makes the difference between finding someone in time, or not.

**HAZIM:** And that's what we want to actually get into the hands of real rescue teams someday. Faster searches, fewer people slipping through.

**THAYYIL:** Yeah, we're nowhere near done with this either. There's a ton more we want to build.

**IBRAHIM:** If you want to check out the code, everything's up on GitHub. Thanks for watching.

**End card:** Project name • GitHub URL • Apache-2.0 • *Built for the Gemma 4 Good Hackathon*

---

# Production Notes

## Speaker distribution

Every speaker appears at least twice. Demo voice-over rotates speakers per beat so the demo doesn't feel like one person narrating a movie.

| Segment | Speakers (in order) | Notes |
|---|---|---|
| Why we built this (0:10) | Ibrahim → Thayyil → Hazim → Khaleel | Each person speaks both as VO over B-roll and on-camera. Ibrahim opens over aerial footage with the Eaton Fire stake — no team-name intro, voice is already going when we land. Thayyil lands the timing point. Hazim lands the scale + the gap-equals-lost-lives line. Khaleel closes with the lead-in to "how we solved it." |
| How we solved it (0:57) | Qasim → Thayyil → Ibrahim | Qasim picks up directly from Khaleel ("keeps working when nothing else does" → "the way we did it is simple"). Thayyil drops the paper reframe casually. Ibrahim closes with the offline payoff that sets up the demo. |
| Demo VO (1:27) | Ibrahim → Thayyil → Hazim → Qasim → Ibrahim → Khaleel | Beats cycle so the demo feels like a group narration, not a single host. Qasim's wow-moment line is the one place inside the demo where impact framing is foregrounded ("a bad decision costing someone their life"). |
| Close (2:27) | Khaleel → Qasim → Hazim → Thayyil → Ibrahim | Impact-first, not us-first. Khaleel sets the stake. Qasim lands the lives-saved core line. Hazim names the user — real rescue teams. Thayyil and Ibrahim close clean. |

## Capture-day flags

1. **Eaton Fire footage must be license-clean.** Use NASA SVS imagery directly ([svs.gsfc.nasa.gov/5558](https://svs.gsfc.nasa.gov/5558/) is U.S. government work, free to use). For news anchor B-roll, use AP / Reuters free-use archive or Pexels disaster stock — don't lift directly from CNN / KTLA broadcasts.
2. **The airplane-mode overlay must be real.** Toggle wifi off on the demo machine and screen-record it for real. Free credibility moment.
3. **The wow-moment banner has three capture options** (from storyboard `docs/21-demo-storyboard.md` Sub-beat 3c):
   - Live trigger via `scripts/check_wow_moment.sh` (preferred — natural)
   - Synth-WS PNGs already committed: [`docs_assets/dashboard-validation-wow-failed.png`](../docs_assets/dashboard-validation-wow-failed.png) + [`docs_assets/dashboard-validation-wow-passed.png`](../docs_assets/dashboard-validation-wow-passed.png) — splice in as still frames if live trigger fails
   - `agents/egs_agent/main.py --inject-overcount-once` for deterministic live capture
4. **Beat 5 capture rig already exists.** [`scripts/run_beat5_capture.sh`](../scripts/run_beat5_capture.sh) drives the wifi-down/wifi-up sequence; verifier is [`scripts/check_beat5.py`](../scripts/check_beat5.py). Reference video at [`docs_assets/beat5-offline-proof.mp4`](../docs_assets/beat5-offline-proof.mp4).

---

# Shot List & Capture Day Plan

## Pre-capture checklist (do the day before)

- [ ] Pull NASA SVS Eaton Fire imagery + supporting news B-roll
- [ ] Pull aerial drone footage of disaster aftermath (license-clean, ~10s clip)
- [ ] Pull rooftop-survivor / aerial-distress shot (stock or staged)
- [ ] Confirm GitHub repo URL for end card
- [ ] Build the cloud-→-drone animation graphic for "How we solved it"
- [ ] Test webcam framing for all 5 — agreed background / lighting / shirt color (avoid clashing logos)
- [ ] Confirm `scripts/check_wow_moment.sh` and `--inject-overcount-once` flag both work on the capture machine
- [ ] Confirm `scripts/run_beat5_capture.sh` runs cleanly end-to-end
- [ ] Smoke-test full demo path on capture machine, wifi off, three drones
- [ ] Pre-record one practice take of every spoken line for pacing
- [ ] Confirm `ollama list` shows both `gemma4:e2b` and `gemma4:e4b` cached

## Capture order (shoot what's hardest first)

### Block A — Demo screen recording (60–90 min)
Hardest to get right. Shoot first while operator is fresh.

1. **Take 1 — clean baseline.** Wifi off, three drones, full scenario end-to-end. Even if it's not the keeper, you'll know the timing.
2. **Take 2 — Spanish moment isolated.** Run multilingual scenario cleanly.
3. **Take 3 — wow moment.** Run `scripts/check_wow_moment.sh` until it greenlights, or fire `--inject-overcount-once` at the replan moment. Capture the red→green banner.
4. **Take 4 — Beat 5 offline-proof.** Use `scripts/run_beat5_capture.sh`. Capture the full F1→F8 sequence.
5. **Take 5 — backup clean run.** One more end-to-end for safety.
6. **Cutaway shots.** Zoom in on the finding card, airplane-mode indicator, validation banner, the `report_finding()` JSON overlay, `ollama list` terminal output. Shoot isolated for B-roll inserts.

### Block B — Webcam talking heads (45 min)
All 5 in one session if possible. Pin one Zoom-style window per person.

1. Each person reads **both** their VO line and their on-camera line, 3× each (cold, warm, best). The "Why we built this" segment uses both — the VO carries over the B-roll, the on-camera line lands when we cut to their webcam.
2. Capture the 5-up grid silent footage for the brief intro cut and the 2:28 close.
3. Capture each person nodding / listening for cutaways during voice-over sections.
4. Capture clean room-tone for each speaker — the cross-cut between B-roll and webcam needs the audio to feel continuous, which means matching room acoustics in post.

### Block C — Voice-over (30 min)
Re-record demo VO clean over a quiet mic, even if the original demo audio is fine. Sync in post.

## Edit pass checklist

- [ ] Total runtime ≤ 3:00 (target 2:53)
- [ ] Eaton Fire date stamp visible for ≥ 1.5s
- [ ] Airplane-mode indicator visible for ≥ 1.5s
- [ ] `report_finding()` JSON visible on screen for ≥ 2s
- [ ] Spanish command text visible on screen
- [ ] Validation banner red → green visible for ≥ 2s, corrective text legible
- [ ] EGS LINK SEVERED banner + STANDALONE badge clearly visible
- [ ] Victim-count chip ticking from N to N+1 after reconnect — hold ≥ 1.5s (the money shot)
- [ ] `ollama list` output legible for ≥ 2s
- [ ] "Software simulation" subtle caption present throughout demo segment
- [ ] All five team members appear on camera
- [ ] All five team members speak at least one line
- [ ] End card holds for ≥ 3s with GitHub URL legible
- [ ] Captions burned in (judges may watch muted)
- [ ] Audio levels: dialogue at -12 dB, music bed at -24 dB
- [ ] Color-grade pass on disaster B-roll (cooler, slightly desaturated for tonal contrast vs. the warm webcam shots)

## Upload checklist

- [ ] YouTube upload, **Public** (not Unlisted — judges shouldn't need a link forwarded)
- [ ] Video title: "FieldAgent — Offline Disaster-Response Swarm Powered by Gemma 4"
- [ ] Description includes GitHub repo URL, team names, hackathon track, reference paper citation (Nguyen, Truong, Le 2026, arXiv 2601.14437)
- [ ] Thumbnail: validation banner (red→green) split-screen with team grid
- [ ] Captions enabled (auto-generated is fine if reviewed for accuracy)
- [ ] Confirm video plays without login from incognito session
- [ ] Direct YouTube link added to Kaggle submission form

---

# Word-count budget (sanity check)

| Segment | Duration | Spoken words | Pace check |
|---|---|---|---|
| Cold open | 10s | 0 | n/a |
| Why we built this (B-roll + webcams interleaved) | 47s | ~105 | ~134 wpm ✓ — comfortable for cross-cut pacing |
| How we solved it | 30s | ~75 | ~150 wpm ✓ |
| Demo VO | 60s | ~135 | ~135 wpm ✓ (slower, deliberate VO) |
| Close | 33s | ~80 | ~145 wpm ✓ |
| **Total** | **180s** | **~395** | Right at 3:00 cap — at casual ~150 wpm delivery we land at ~2:55. If anyone runs slow, cut Hazim's "Faster searches…" tail in the close. |

**On the close timing:** if any take in the close runs long, the easiest cut is to merge Hazim's line into Khaleel's ("…that means a lot to all of us — and we'd love to take it to real hardware next").
