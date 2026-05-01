# 21 — Demo Storyboard

## Why This Doc Exists

The 90-second video is what the judge actually watches. Everything else exists to make this video credible. This doc is the locked storyboard. We work backward from this.

## Total Length: 90 Seconds

Hard cap. Judges have hundreds of submissions. Going over loses attention.

## Structure (Six Beats)

```
[0:00 - 0:10]  Beat 1: The Problem
[0:10 - 0:25]  Beat 2: The Academic Anchor
[0:25 - 1:05]  Beat 3: The System in Action
[1:05 - 1:20]  Beat 4: The Resilience Moment
[1:20 - 1:30]  Beat 5: The Offline Proof + Closer
```

## Beat 1: The Problem (0:00 - 0:10)

**Goal:** establish the stakes in 10 seconds.

**Visual:** B-roll of disaster aftermath (free stock footage from Pexels / Pixabay — wildfire, hurricane wreckage, downed power lines).

**Voiceover/text:** "After every major disaster, communication infrastructure fails in the first hour. Cloud-AI drone systems become useless when they're needed most."

**Title card at end:** *"FieldAgent: Offline drone swarm coordination with Gemma 4."*

## Beat 2: The Academic Anchor (0:10 - 0:25)

**Goal:** establish credibility by citing the paper.

**Visual:** Side-by-side: paper PDF (Nguyen et al. 2026) on left; our system architecture diagram on right.

**Voiceover/text:** "In January 2026, INRS published the strongest architecture for AI-driven disaster response drones. It works — but it depends on cloud GPT-4.1. We replaced every LLM in their architecture with Gemma 4 running locally. Same architecture. Zero cloud."

**Caption on screen:** *"Reference: Nguyen, Truong, Le 2026 (arXiv 2601.14437)"*

## Beat 3: The System in Action (0:25 - 1:05)

**This is the longest section, 40 seconds.** It carries the technical demonstration.

### Sub-beat 3a: Mission Start (0:25 - 0:35)

**Visual:** Wide shot of the software-only Python simulation. Disaster zone with damaged buildings, debris, victims. 2-3 drones launching from ground station.

**Caption:** *"3 simulated drones, each running Gemma 4 E2B. Edge ground station running Gemma 4 E4B. No internet."*

### Sub-beat 3b: The Agentic Loop (0:35 - 0:55)

**Split-screen layout:**

Left side: Drone-eye camera view in the software sim. Drone flies over a damaged building. Spots a victim marker.

Right side: Live overlay showing:
- Gemma 4's reasoning trace
- The function call output:
  ```
  report_finding(
    type="victim",
    severity=4,
    confidence=0.78,
    visual_description="Person prone, partially covered by debris..."
  )
  ```

**Caption flashes:** *"Gemma 4 vision → reasoning → function call → broadcast"*

Then immediately: another drone receives the broadcast, the dashboard ticker shows "drone2 reasoning: should I investigate? Yes — closer position, sufficient battery." Drone 2 redirects.

### Sub-beat 3c: The Hallucination Catch (0:55 - 1:05)

**This is the wow moment.** Carefully engineered to reliably trigger.

**Visual:** EGS replanning event. Side panel shows:
- First attempt: assignment includes 27 points (only 25 exist). VALIDATION FAILED in red.
- Corrective prompt visible: *"You are hallucinating, creating more survey points than required..."*
- Second attempt: 25 points, balanced. VALIDATION PASSED in green.

**Caption:** *"Validation loop catches and corrects Gemma 4 hallucinations in real-time."*

This is the technical innovation moment. It must land clearly.

## Beat 4: The Resilience Moment (1:05 - 1:20)

**Goal:** prove the architecture survives failures.

**Visual:** Operator types in Spanish: *"drone 2, regresa a la base"*

Dashboard shows Gemma 4's translation:
```
recall_drone(
  drone_id="drone2",
  reason="ordered"
)
```

Drone 2 returns. Drone 3 immediately picks up drone 2's survey points (replanning visible).

Then the dramatic moment: a card appears: *"EGS LINK SEVERED."* The dashboard shows EGS as offline. But the drones keep flying. The drone status panels show "STANDALONE MODE ACTIVE."

**Caption:** *"Multilingual operator commands. Continued operation when the EGS goes offline."*

## Beat 5: The Offline Proof + Closer (1:20 - 1:30)

**Goal:** seal the offline claim and end strong.

**Visual:** Cut to a terminal window. Run `ifconfig` (or `ip addr`). Show no active network interface (or airplane mode visible). Then `ollama list` showing Gemma 4 E2B and E4B running locally.

**Caption:** *"Every model. Every decision. Every coordination. All local."*

**Final visual:** the GitHub repo URL on screen.

**Voiceover/text:** "3.6 billion people live in disaster-vulnerable regions. When the towers fall, the swarm keeps going. FieldAgent. Open source. Apache 2.0."

## Backup Beat 4 (If EGS-link-severed scenario doesn't work cleanly)

If the standalone-mode demo is too flaky, replace Beat 4 with:

**Visual:** Drone 3 simulates GPS failure (scripted event). Drone 3 returns to base. EGS replans. Drone 1 + Drone 2 absorb drone 3's survey points. Validation loop runs cleanly during the replan.

**Caption:** *"Drone failures trigger automatic replanning. Validation ensures no data is lost."*

This is less impressive but more reliable to capture.

## Production Notes

### Capture Methodology

1. **Run the full demo scenario at least 50 times.** This is non-negotiable. Out of 50 runs, find the 2-3 cleanest.

2. **Multi-camera capture:**
   - Screen recording of the software sim (full screen)
   - Screen recording of dashboard (full screen)
   - Screen recording of terminal showing logs
   - Audio of any narration

3. **Use OBS Studio** (free, supports multi-source recording, scene composition).

4. **Edit in DaVinci Resolve** (free) or any video editor familiar to Person 4.

### Visual Style

- **Color palette:** dark backgrounds (terminal, sim view) with bright accent colors for the dashboard (greens for success, red for failures)
- **Typography:** sans-serif throughout, bold for emphasis
- **Transitions:** quick cuts (no fades). Hackathon judges have short attention spans.
- **Music:** subtle, urgent, no lyrics. Royalty-free from YouTube Audio Library or similar.
- **Captions:** present throughout for accessibility and silent viewing

### Narration

Narration is optional. If included:
- Person 4 records (or another team member with a clear voice)
- Quiet room, decent USB mic
- Pace: ~165 words per minute
- Total words: ~245 for 90 seconds

If no narration, captions carry the information. Captions are mandatory either way.

### Mandatory Visual Elements

Every video must contain:

- [ ] Real software sim footage (not just slideshow)
- [ ] Dashboard rendering live state
- [ ] Gemma 4's structured output visible on screen at least once
- [ ] Validation correction event visible
- [ ] Multilingual command moment
- [ ] Offline proof (terminal showing no internet)
- [ ] Citation of the reference paper
- [ ] GitHub URL at the end

### "Simulation" Disclosure

We do not hide that this is simulation. A subtle caption in the bottom corner during sim footage: *"Software simulation"*. Hackathon judges respect this transparency.

Frame the simulation positively: *"This code runs unchanged on real Jetson Orin hardware. We simulate to safely demonstrate disaster scenarios at scale."*

### Forbidden Visual Elements

- No fake / mocked screens we don't actually have
- No claims of accuracy/performance we haven't measured
- No "AI" buzzword overuse
- No music with lyrics that distract from the message
- No "this could change the world" overreach (let the judges think that)

## Storyboard Frame-by-Frame Reference

A sketched storyboard exists in `docs_assets/storyboard.png` (Person 4 creates this Day 14). Each beat has 2-4 frame sketches showing what the camera/screen displays.

## Test Audience

Before locking the video, show it to 3 people who don't know the project:

1. Can they explain what the project does? (If no, the pitch is unclear)
2. Did they understand the offline angle? (If no, strengthen Beat 5)
3. Did they notice the validation correction? (If no, slow down Beat 3c)
4. Was 90 seconds too long? (If yes, cut Beat 4 down)

Iterate based on feedback. Lock by Day 17 (May 17). No more changes after Day 17.

## Cross-References

- The architecture being demonstrated: [`04-system-architecture.md`](04-system-architecture.md)
- The validation loop that catches the hallucination: [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md)
- The multilingual capability shown: [`07-operator-interface.md`](07-operator-interface.md)
- The resilience scenarios: [`08-mesh-communication.md`](08-mesh-communication.md)
- What goes in the writeup that complements this video: [`22-writeup-outline.md`](22-writeup-outline.md)
