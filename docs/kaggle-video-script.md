# Kaggle Submission Video — Script

**Target runtime:** 2:55 (180s ceiling, 5s buffer)
**Hackathon:** Gemma 4 Good Hackathon — Kaggle × Google DeepMind
**Submission deadline:** May 18, 2026, 23:59 UTC
**Hosting:** YouTube (public, no login required)

This is the v1 script. Companion shot list / capture day plan lives below the script.

---

## [0:00 – 0:12]  COLD OPEN — Disaster Montage *(12s, no narration)*

**Visual:** Rapid cuts of real disaster footage — Türkiye-Syria earthquake rubble, Maui wildfires, Helene flooding. News-anchor audio bleeds through low and clipped. Three text overlays flash, one per cut:

> "Cell towers down across 4 counties."
> "Search teams operating blind."
> "First 72 hours are critical."

**Audio:** News chatter fades to a single beat of silence.

---

## [0:12 – 0:25]  STAKES — Drone POV *(13s)*

**Visual:** Aerial drone footage over collapsed buildings. Slow tilt-down reveals a person on a rooftop waving for help. Hold on the figure.

**Text overlay (large, centered):**
> 3.6 billion people live in climate-vulnerable regions.
> When the network dies, so does coordination.

---

## [0:25 – 0:55]  TEAM + PROBLEM *(30s)*

**Visual:** Cut to a 5-up grid of all team webcams for ~2s, then settle on the speaker.

**IBRAHIM:** Hey, we're the team behind FieldAgent. So the thing that kept bugging us — basically every serious disaster-response AI out there runs in the cloud. Which works great, until a hurricane takes out the cell towers.

**THAYYIL:** Which is the worst possible time for it to fail, right? The first 72 hours after a disaster hits are when most rescues actually happen.

**HAZIM:** So we figured, what if you just put the AI directly on the drones themselves? That way it doesn't really matter what the network is doing — everything just keeps working.

**Lower-third:** *FieldAgent — fully offline disaster response, powered by Gemma 4*

---

## [0:55 – 1:30]  HOW IT WORKS *(35s)*

**Visual:** Simple architecture diagram animates in — drones (Layer 1) → Edge Ground Station (Layer 2) → operator dashboard (Layer 3). A cloud icon appears, then is crossed out with a red ✕.

**QASIM:** So under the hood, every drone is running Gemma 4 E2B for the vision and reasoning, all on the device itself. Then the bigger E4B model sits at our edge ground station handling the swarm-level coordination. Both completely offline.

**KHALEEL:** We also fine-tuned a victim-detection adapter on real disaster aerial imagery. So when a drone actually spots a survivor, Gemma fires off a structured call and the operator sees it on their dashboard pretty much instantly.

**THAYYIL:** And the part we're really proud of is the validation layer. Every output Gemma generates gets checked against a set of hard rules — so if it hallucinates something, we catch it and make it retry before anything actually ships.

**Visual cut:** function-call JSON appears → red ✕ → corrective re-prompt → green ✓

---

## [1:30 – 2:30]  LIVE DEMO *(60s — voice-over only, screen recording)*

**Visual:** Screen recording of the actual Flutter dashboard. Three drones tracking across the aerial base map.

**IBRAHIM (VO):** Okay, so what you're looking at here is three drones surveying a simulated disaster zone. The whole demo is running with the wifi off — everything's happening locally on our laptop.

**Visual overlay** (top-right, ~2s): macOS/Windows airplane-mode indicator — *real* wifi-off icon, captured for real.

**IBRAHIM (VO):** And there — drone one just picked up a survivor.

**Visual:** C2A adapter fires. Camera frame highlights the victim. Finding card pops on dashboard — severity, GPS, confidence, image.

**THAYYIL (VO):** The cool part is that detection happened entirely on the drone itself. No server, no API call, no internet — just Gemma running on the device.

**Visual:** Operator clicks approve. Card moves to *Approved*.

**IBRAHIM (VO):** Now I'm going to take drone three offline and see how the swarm reacts.

**Visual:** Drone 3 marker turns red. EGS triggers a replan. The validation banner flashes red at the top — *ASSIGNMENT_TOTAL_MISMATCH detected* — then green — *retry succeeded*.

**HAZIM (VO):** And that banner at the top is the part we love — that's Gemma 4 actually catching its own mistake during the replan. The validation layer rejected the first plan, sent it back with the constraint, and the corrected version went out to the remaining drones.

**Visual:** Drones one and two redistribute survey points and continue. Path closes in on the survivor's location.

---

## [2:30 – 2:55]  CLOSE *(25s)*

**Visual:** Cut back to the 5-up team grid. Clean, even framing.

**KHALEEL:** Honestly, working on this has been one of the coolest things I've done. Knowing it could actually help in a real disaster — that means a lot.

**QASIM:** Yeah, our whole bet was that on-device AI is finally ready for safety-critical work. And working with Gemma 4 kind of proved that to us.

**HAZIM:** This is just our v1 too — we'd love to take it further and get it onto real hardware.

**THAYYIL:** Thanks so much for checking out our project, we really appreciate it.

**IBRAHIM:** Yeah that's FieldAgent. Thanks for watching.

**End card:** Project name • GitHub URL • *Built for the Gemma 4 Good Hackathon*

---

# Production Notes

## Speaker assignments

| Segment | Speakers | Role rationale |
|---|---|---|
| Team + Problem (0:25) | Ibrahim → Thayyil → Hazim | Ibrahim opens (project lead). Thayyil + Hazim land the stakes punch. |
| How it works (0:55) | Qasim → Khaleel → Thayyil | Qasim on architecture. Khaleel on the LoRA. Thayyil on validation. |
| Demo VO (1:30) | Ibrahim + Thayyil + Hazim | Ibrahim narrates beats. Thayyil + Hazim drop the credibility lines. |
| Close (2:30) | All five, one line each | Everyone lands. |

Khaleel's segment-3 line is a placeholder — assign to whoever owns the C2A LoRA workstream. Same for any other swap.

## Three flags for capture day

1. **News clips & disaster B-roll must be license-clean.** Pull from Pexels, Coverr, NASA, USGS, or Reuters' free-use archive. Do not lift directly from CNN / BBC / Al Jazeera broadcasts. The rooftop-survivor shot needs to be either stock or staged.
2. **The "airplane mode" overlay must be real.** Actually toggle wifi off on the demo machine and screen-record it. The credibility moment costs nothing and proves the offline claim — judges will look for exactly this.
3. **The wow-moment validation banner uses the deterministic-injection path.** Per `docs/STATUS.md`, natural triggers landed 0/7 on the RTX A2000. Use the `--inject-overcount-once` flag for capture. The validation *behavior* is real; only the trigger is deterministic. Disclose this in the writeup, not the video.

---

# Shot List & Capture Day Plan

## Pre-capture checklist (do the day before)

- [ ] Pull stock disaster B-roll (Pexels / Coverr / NASA) — minimum 6 clips, 5–10s each
- [ ] Pull rooftop-survivor / aerial drone shot (stock or staged)
- [ ] Confirm GitHub repo URL for end card
- [ ] Build architecture-diagram graphic (3 layers + crossed-out cloud)
- [ ] Build function-call JSON → ✕ → ✓ animation graphic
- [ ] Test webcam framing for all 5 — agree on background / lighting / shirt color (avoid clashing logos)
- [ ] Confirm `--inject-overcount-once` flag works on capture machine
- [ ] Smoke-test full demo path on capture machine, wifi off, three drones
- [ ] Pre-record one practice take of every spoken line for pacing

## Capture order (shoot what's hardest first)

### Block A — Demo screen recording (60–90 min)
Hardest to get right. Shoot first while operator is fresh.

1. **Take 1 — clean baseline.** wifi off, three drones, run scenario end-to-end. Even if it's not the keeper, you'll know the timing.
2. **Take 2 — wow-moment.** Same scenario, fire `--inject-overcount-once` at the replan moment. Capture the banner red→green.
3. **Take 3 — backup.** One more clean run for safety.
4. **Cutaway shots.** Zoom-in on the finding card, the airplane-mode indicator, the validation banner. Shoot these isolated for B-roll inserts.

### Block B — Webcam talking heads (45 min)
All 5 in one session if possible. Pin one Zoom-style window per person.

1. Each person reads their line 3× (cold, warm, best). Capture all takes.
2. Capture the 5-up grid silent footage for the 0:25 intro and the 2:30 close.
3. Capture each person nodding / listening for cutaways during voice-over sections.

### Block C — Voice-over (30 min)
Re-record demo VO clean over a quiet mic, even if the original demo audio is fine. Sync in post.

## Edit pass checklist

- [ ] Total runtime ≤ 3:00 (target 2:55)
- [ ] Airplane-mode indicator visible for ≥ 1.5s
- [ ] Validation banner red→green visible for ≥ 2s
- [ ] All five team members appear on camera
- [ ] All five team members speak at least one line
- [ ] End card holds for ≥ 3s with GitHub URL legible
- [ ] Captions burned in (judges may watch muted)
- [ ] Audio levels: dialogue at -12 dB, music bed at -24 dB
- [ ] Color-grade pass on disaster B-roll (cooler, slightly desaturated for tonal contrast vs. the warm webcam shots)

## Upload checklist

- [ ] YouTube upload, **Public** (not Unlisted — judges shouldn't need a link forwarded)
- [ ] Video title: "FieldAgent — Offline Disaster-Response Swarm Powered by Gemma 4"
- [ ] Description includes GitHub repo URL, team names, hackathon track
- [ ] Thumbnail: validation banner (red→green) split-screen with team grid
- [ ] Captions enabled (auto-generated is fine if reviewed for accuracy)
- [ ] Confirm video plays without login from incognito session
- [ ] Direct YouTube link added to Kaggle submission form

---

# Word-count budget (sanity check)

| Segment | Duration | Spoken words | Pace check |
|---|---|---|---|
| Cold open | 12s | 0 | n/a |
| Stakes | 13s | 0 | n/a |
| Team + Problem | 30s | ~75 | ~150 wpm ✓ (casual, conversational) |
| How it works | 35s | ~95 | ~163 wpm — slightly brisk, trim if needed |
| Demo VO | 60s | ~135 | ~135 wpm ✓ (slower deliberate VO over screen) |
| Close | 25s | ~70 | ~168 wpm — tight; if anyone runs long, trim Hazim or Khaleel |
| **Total** | **175s** | **~375** | 5s buffer for transitions; casual delivery is forgiving |

**On the close timing:** five people in 25s is genuinely tight. If a take feels rushed, you've got two outs — extend the close to 30s by trimming the demo VO by 5s (drop the "And there — drone one just picked up a survivor" beat and let the visual carry it), or cut Hazim's close line since he already speaks in the demo VO.
