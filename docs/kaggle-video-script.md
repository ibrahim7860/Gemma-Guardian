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

The voice is already going when we land here — we don't introduce ourselves over silence and *then* cut to footage. The drone B-roll and the team webcams cross-cut throughout, so the segment plays as one continuous thought with our faces appearing and disappearing over the imagery.

**Visual opens on:** aerial drone footage over fire-damaged neighborhoods. Audio is already playing.

**IBRAHIM (VO, over B-roll):** Hey, we're the team behind FieldAgent.

**Cut to webcams:** 5-up grid for ~1s, then settle on Ibrahim.

**IBRAHIM (on camera):** And honestly, the reason we built this is pretty personal for all of us.

**Cut to B-roll:** drone POV slowly tilting down toward a person waving from a rooftop. Hold on the figure.

**THAYYIL (VO, over B-roll):** Watching what happened with the Eaton Fire really got to us. All this tech built to help people in disasters, but the second the cell towers go down, it's basically useless.

**Cut to webcam:** Thayyil.

**THAYYIL (on camera):** And that's not just an Eaton Fire problem — that's how every major disaster goes.

**Cut to B-roll:** aerial of collapsed structures, smoke rising. Text overlay fades in mid-shot:
> 3.6 billion people live in disaster-vulnerable regions.

**HAZIM (VO, over B-roll):** And that's the worst possible time for the tech to fail.

**Cut to webcam:** Hazim.

**HAZIM (on camera):** The first few hours after a disaster hits are when most rescues actually happen.

**Cut to B-roll:** brief shot of a rescue worker or someone trapped near rubble.

**KHALEEL (VO, over B-roll):** So we wanted to build something that actually still works when everything else breaks.

**Cut to webcam:** Khaleel.

**KHALEEL (on camera):** Something that could genuinely help save lives.

---

## [0:55 – 1:23]  HOW WE SOLVED IT *(28s)*

**Visual:** Simple animated graphic — a cloud icon appears, gets crossed out, replaced by a drone with a tiny "AI" chip glowing inside it. Then three drones connected to each other (not to the cloud).

**QASIM:** Honestly, the idea is pretty simple. Instead of having the drones rely on the internet to think, we just put the AI directly on the drones themselves.

**THAYYIL:** We actually found a paper from earlier this year that proposed a similar setup — but theirs needed cloud GPT-4 to work. We took the same architecture and made it run on Gemma 4 locally. Completely offline.

**IBRAHIM:** So now the drones can see, think, talk to each other, coordinate rescue work — even with zero internet for miles.

---

## [1:23 – 2:28]  THE DEMO *(65s — voice-over on screen recording)*

**Visual:** Live screen recording of the actual Flutter dashboard. Three drones tracking across the aerial base map. *"Software simulation"* caption in the bottom-right corner throughout this segment (honest disclosure per storyboard).

### Setup *(0:00–0:05 of demo, ~5s)*

**Visual overlay** (top-right, holds ~2s): real macOS/Windows airplane-mode icon, captured with wifi actually off.

**IBRAHIM (VO):** Okay, so this is the actual system running. Three drones surveying a simulated disaster zone — and the wifi on our laptop is turned off.

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

**QASIM (VO):** And this is one of our favorite moments. Gemma's planning a re-coordination and actually makes a mistake — but our validation layer catches it instantly and corrects it before anything ships.

### Beat 5 — offline proof *(~15s)*

**Visual:** Operator runs `sudo ifconfig en0 down`. EGS LINK SEVERED banner appears. Drone 3 gets a STANDALONE badge. Drone 3 keeps flying. Sidecar log shows "finding produced (buffered)." Then operator runs `sudo ifconfig en0 up` — banner clears, the buffered finding pops onto the dashboard, victim count chip ticks up by one.

**IBRAHIM (VO):** Now I'm dropping drone three's connection completely. It keeps flying, finds another survivor while it's offline, and the second it reconnects — that finding shows up on the dashboard. Nothing lost.

### Local-only proof *(~8s)*

**Visual:** Cut to a terminal window. `ollama list` runs, output shows `gemma4:e2b` and `gemma4:e4b` cached locally. Airplane-mode icon still visible.

**KHALEEL (VO):** Every model. Every decision. All running locally. No cloud anywhere.

---

## [2:28 – 2:56]  WHAT THIS COULD MEAN *(28s)*

**Visual:** Cut back to the 5-up team grid. Clean framing.

**KHALEEL:** Honestly, building this has been one of the most meaningful things I've worked on. Knowing it could one day actually help save lives — that means a lot to all of us.

**QASIM:** We genuinely think this could change how emergency response works after a disaster. Faster rescues, fewer people slipping through the cracks.

**HAZIM:** And this is just our v1 — we'd love to take it to real hardware and put it in the hands of teams who actually need it.

**THAYYIL:** Thanks so much for checking out our project.

**IBRAHIM:** That's FieldAgent. The code's on GitHub — thanks for watching.

**End card:** Project name • GitHub URL • Apache-2.0 • *Built for the Gemma 4 Good Hackathon*

---

# Production Notes

## Speaker distribution

Every speaker appears at least twice. Demo voice-over rotates speakers per beat so the demo doesn't feel like one person narrating a movie.

| Segment | Speakers (in order) | Notes |
|---|---|---|
| Why we built this (0:10) | Ibrahim → Thayyil → Hazim → Khaleel | Each person speaks both as VO over B-roll and on-camera. Ibrahim opens over aerial footage; Thayyil delivers the Eaton Fire personal hook; Hazim lands the timing stake; Khaleel closes on motivation. |
| How we solved it (0:55) | Qasim → Thayyil → Ibrahim | Qasim explains the on-device idea; Thayyil mentions the paper reframe casually; Ibrahim closes with the offline payoff. |
| Demo VO (1:23) | Ibrahim → Thayyil → Hazim → Qasim → Ibrahim → Khaleel | Beats cycle so the demo feels like a group narration, not a single host. |
| Close (2:28) | Khaleel → Qasim → Hazim → Thayyil → Ibrahim | Personal-meaning → societal impact → next steps → thanks → sign-off. |

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
| Why we built this (B-roll + webcams interleaved) | 45s | ~100 | ~133 wpm ✓ — comfortable for cross-cut pacing |
| How we solved it | 28s | ~75 | ~160 wpm ✓ |
| Demo VO | 65s | ~140 | ~130 wpm ✓ (slower, deliberate VO) |
| Close | 28s | ~75 | ~160 wpm — slight push; trim Hazim line if needed |
| **Total** | **176s** | **~390** | 4s buffer for transitions; well under 3:00 cap |

**On the close timing:** if any take in the close runs long, the easiest cut is to merge Hazim's line into Khaleel's ("…that means a lot to all of us — and we'd love to take it to real hardware next").
