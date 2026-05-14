# 21 — Demo Storyboard

## Why This Doc Exists

The 1:45 video is what the judge actually watches. Everything else exists to make this video credible. This doc is the locked storyboard. We work backward from this.

## Total Length: 1:45 (internal target) / 3:00 (Kaggle hard cap)

**Page-verified cap (Kaggle, 2026-05-13):** videos must be **≤3 minutes**, must be on YouTube, must be publicly viewable without login (unlisted OK, private not).

**Internal target locked at 1:45 (decision 2026-05-13):** extended from the original 90-second cap to give Beat 5 the room it needs. Beat 5 carries a 60-second in-sim scenario (F1→F8 in the frame table below); compressing that to 10s of edit was the original storyboard's tightest constraint and was costing the strongest visual in the video — the victim-count chip ticking 0 → 1 *after* link restore. The extra 15 seconds go entirely to Beat 5; the other beats keep their original pacing.

## Structure (Six Beats)

```
[0:00 - 0:10]  Beat 1: The Problem
[0:10 - 0:25]  Beat 2: The Academic Anchor
[0:25 - 1:05]  Beat 3: The System in Action
[1:05 - 1:20]  Beat 4: The Resilience Moment
[1:20 - 1:45]  Beat 5: The Offline Proof + Closer  ← 25s (was 10s)
```

## Beat 1: The Problem (0:00 - 0:10)

**Goal:** establish the stakes in 10 seconds, anchored in a named event so the framing isn't generic.

**Visual:** Open on NASA SVS imagery from the **Eaton Fire (Los Angeles, January 2025)** — [`https://svs.gsfc.nasa.gov/5558/`](https://svs.gsfc.nasa.gov/5558/), the same footprint the reference paper benchmarks against. Cut to short B-roll of cell-tower failures / downed infrastructure (Pexels / Pixabay).

**Voiceover/text:** "January 2025. The Eaton Fire collapsed cell coverage across the foothills in the first hour. Cloud-AI drone systems became useless in the same hour they were needed most."

**Title card at end:** *"FieldAgent: Offline drone swarm coordination with Gemma 4."*

This naming aligns with the writeup's §1 framing (`docs/22-writeup-draft.md`) and matches the gating advice in `docs/02-hackathon-context.md` to anchor with a specific event rather than aggregate statistics.

## Beat 2: The Academic Anchor (0:10 - 0:25)

**Goal:** establish credibility by citing the paper.

**Visual:** Side-by-side: paper PDF (Nguyen et al. 2026) on left; our system architecture diagram on right.

**Voiceover/text:** "In January 2026, INRS published the most directly relevant architecture for AI-driven disaster response drones. It works — but it depends on cloud GPT-4.1. We replaced every LLM in their architecture with Gemma 4 running locally. Same architecture. Zero cloud."

**Caption on screen:** *"Reference: Nguyen, Truong, Le 2026 (arXiv 2601.14437)"*

## Beat 3: The System in Action (0:25 - 1:05)

**This is the longest section, 40 seconds.** It carries the technical demonstration.

### Sub-beat 3a: Mission Start (0:25 - 0:35)

**Visual:** Wide shot of the software-only Python simulation rendered in the Flutter dashboard's map panel. Disaster zone with the locked-bbox map background, damaged-building markers, and 2-3 drones beginning their scripted waypoint tracks from their `home` positions in `sim/scenarios/disaster_zone_v1.yaml`.

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

**This is the wow moment.** The technical innovation moment. It must land clearly.

**Visual:** The dashboard's Validation Loop banner mounted under `EgsLinkSeveredBanner` shows:
- **Attempt 1:** red `FAILED` chip + `ASSIGNMENT_TOTAL_MISMATCH` rule id + the actually-shipped corrective text rendered verbatim from `egs_state.replan_in_flight_attempt_log`:
  > *"Your assignments cover 27 points but 25 are available. Reassign so every point is covered exactly once."*
- **Attempt 2:** green `PASSED` chip + no corrective text. Both attempt rows visible side-by-side via `AnimatedSwitcher` fade-in (~800ms settle).

**Caption:** *"Validation loop catches and corrects Gemma 4 hallucinations in real-time."*

**Capture strategy — stochastic-trigger reality:** Gemma 4 E4B does not always hallucinate the overcount on cue. The `wow_moment_v1` scenario (`sim/scenarios/wow_moment_v1.yaml` — 25 awkwardly-clustered survey points, 3 drones, one partially out of mesh range) is engineered to produce over- or under-assignment with measurable frequency, but Phase 5 close-out on M1 16GB recorded one live run where E4B produced an invalid-but-non-overcount assignment (`scripts/check_wow_moment.sh` exit 1). Three capture-day fallbacks, in priority order:

1. **Live trigger.** Run `scripts/check_wow_moment.sh` immediately before each take; exit 0 greenlights, exit 1 reruns. Cheapest path if the model cooperates.
2. **Deterministic synth-WS capture (already on disk).** Both reference PNGs are committed:
   - [`docs_assets/dashboard-validation-wow-failed.png`](../docs_assets/dashboard-validation-wow-failed.png) (56 KB, 1665×720) — Attempt 1 FAILED chip + corrective text
   - [`docs_assets/dashboard-validation-wow-passed.png`](../docs_assets/dashboard-validation-wow-passed.png) (59 KB, 1665×737) — Attempt 1 FAILED + Attempt 2 PASSED side-by-side
   - Insert as still frames during edit with a 0.5–1.0s hold per state. The audience cannot tell the difference between a live banner and a synth-WS-driven banner — same DOM, same UI, same data shape (corrective text rendered verbatim from the same `replan_in_flight_attempt_log` field). Use these on capture day if live trigger fails twice in a row.
3. **Phase 3c `--inject-overcount-once` flag.** If `agents/egs_agent/main.py --inject-overcount-once` ships, run a take with the flag set for a deterministic live capture; disclose in writeup §4.3 as already documented in the plan.

**Reference assets (committed):**
- `docs_assets/dashboard-validation-wow-failed.png` — Attempt 1 red-chip render
- `docs_assets/dashboard-validation-wow-passed.png` — Attempt 1 + Attempt 2 side-by-side render
- `/tmp/gg_wow_moment_capture/wow_moment_passed.png` (59 KB) — the existing Playwright E2E visual-regression reference at `frontend/ws_bridge/tests/test_e2e_playwright_validation_wow.py`

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

**Reference assets (already captured):**
- `docs_assets/dashboard-multilingual-spanish.png` — live Gemma 4 E4B translation of *"Establecer la prioridad de búsqueda de víctimas en crítico."* through the EGS command pipeline into a structured action with `preview_text_in_operator_language` populated. Captured 2026-05-09 against the real (non-mocked) E4B daemon.
- `docs_assets/dashboard-egs-severed.png` — `EGS LINK SEVERED` banner + per-drone `STANDALONE` badge driven by an `egs.state` heartbeat staleness >5 s.

## Beat 5: The Offline Proof — Disconnection-Tolerant Findings (1:20 - 1:45)

**Goal:** seal the offline claim with a load-bearing visual: the operator pulls the network, drone3 keeps flying and produces a finding while severed from the EGS, and on reconnect that finding is reconciled to the EGS — no data lost, no double-count.

**Pacing budget (25s — extended from 10s on 2026-05-13):** F1 steady state (~2s) · F2 wifi-down + scripted `egs_link_drop` (~3s) · F3 banner + STANDALONE badge attach (~3s) · F4 drone3 buffering finding (~4s) · F5 link restore (~2s) · **F6 banner clears + victim-count chip ticks 0 → 1 (~5s, the money shot, hold it)** · F7 `ollama list` offline-proof terminal (~3s) · F8 verifier passes + GitHub URL closer + tagline (~3s).

**Frame-by-frame mechanics** (resilience_v1 scenario, 60 s window from t=120 to t=180; full path validated by `scripts/check_beat5.py` and `agents/egs_agent/tests/test_e2e_link_drop_replay.py`):

| Frame | Scenario t | Visible on screen | Underlying mechanic |
|---|---|---|---|
| F1 | t=100 | Operator pane shows the connectivity-probe loop printing `WAN: up`. Dashboard shows three drones active, EGS chip green, `findings_count_by_type.victim = 0` or low. | Steady state — `mesh_simulator` emits `mesh.link_status link="up" reason="heartbeat"` for drone3 at 1 Hz, drone3's `LinkStateMonitor` reports `is_standalone() == False`, `BufferedPublisher` passes findings through to Redis, EGS counts increment normally. |
| F2 | t=120 | Operator pane: `sudo ifconfig en0 down` runs. Probe loop flips to `WAN: DOWN` within 1-2 s. The sim's scripted timeline fires `egs_link_drop drone3` on `sim.scripted_events` — independently of the wifi state, so the demo proves the offline behavior even if the operator's WAN drop is slightly off. | `sim/waypoint_runner.py` publishes `{type: "egs_link_drop", drone_id: "drone3"}` to `sim.scripted_events`. Mesh sim subscribes, adds `drone3` to `_link_down_overrides`, and emits `mesh.link_status link="down" reason="scripted"` on the shared channel. |
| F3 | t=121-122 | Dashboard banner *"EGS LINK SEVERED — drones operating in standalone mode"* attaches at the top of the body. drone3's row in the Drone Status panel grows the orange `STANDALONE` badge. | `LinkStatusSubscriber` in drone3's runtime receives the down event; `_handle_link_event` flips `LinkStateMonitor` to standalone and reconciles `BufferedPublisher.set_standalone(True)`. The 0.5 s state-republish loop then writes `agent_status: "standalone"` into drone3's next `drones.drone3.state` payload, which the bridge forwards. The dashboard's `MissionState` heartbeat-staleness logic also fires the banner because the EGS-side timestamp ages out — same code path Beat 4 already exercises. |
| F4 | t=130-170 | drone3 keeps moving on the map. At some point its dashboard sidecar logs *"finding produced (buffered)"* — one of the existing accent rows in the per-drone trace panel. Findings count chips on the dashboard do NOT change. | drone3's reasoning step continues to fire. Gemma produces a `report_finding` tool call; `BufferedPublisher.publish` intercepts the `drones.drone3.findings` channel because `is_standalone is True`, appends to the in-memory deque AND to `<log_dir>/drone3_findings_queue.jsonl`. `drones.drone3.findings.delivered` (the EGS-bound channel) remains silent. Per `validation_events.jsonl`, the finding is logged with `outcome: "success_first_try"` — the agent does not know it has been gated; that's the durable-replay buffer's contract. |
| F5 | t=180 | Sim fires `egs_link_restore drone3` on `sim.scripted_events`. Operator (optionally, after F4) runs `sudo ifconfig en0 up`; probe loop returns to `WAN: up`. | Mesh sim removes drone3 from `_link_down_overrides`, re-evaluates the geometric gate (drone3 is still in range), emits `mesh.link_status link="up" reason="scripted"`. |
| F6 | t=181 | Banner clears. `STANDALONE` badge falls off drone3's row. Findings panel grows a new tile with the buffered finding's `finding_id`; `findings-count-victim` chip ticks from N to N+1 (or higher if multiple findings buffered). | `LinkStatusSubscriber` callback flips `LinkStateMonitor` back to active; `BufferedPublisher.set_standalone(False)` drains the deque synchronously into the inner publisher → raw `drones.drone3.findings`. Mesh sim's findings-gate now allows the publish, republishes onto `drones.drone3.findings.delivered`. EGS `process_findings` validates each, registers each `finding_id` in `_seen_finding_ids` (5-min TTL), increments the count once per id. |
| F7 | t=181 (immediately after) | Terminal pane runs `ollama list`; output shows `gemma4:e2b` and `gemma4:e4b` cached locally. *"Every model. Every decision. Every coordination. All local."* | Visual proof of the offline-by-construction claim. With WAN still down (or the airplane-mode sliver visible), the `ollama list` call works because the daemon is bound to `127.0.0.1:11434`. |
| F8 | post-mission | The verifier runs: `uv run python scripts/check_beat5.py --bridge-url ws://127.0.0.1:9090 --validation-log /tmp/gg_beat5_capture/validation_events.jsonl --deadline-s 30`. All six A-assertions PASS in green. For the Day 15 two-machine backup pass, re-verify from artifacts alone (no live bridge needed) via `--ws-replay-log /tmp/gg_beat5_capture/ws_frames.jsonl` — `scripts/ws_recorder.py` writes that file during the live capture run. | A1 standalone entry, A2 finding while standalone, A3 delivery only after restore, A4 EGS count tick within 5 s, A5 return to active, A6 no double-count under replay. See `docs/plans/2026-05-10-beat5-path-a-full.md` §9. |

**Final visual:** the GitHub repo URL on screen.

**Voiceover/text:** "3.6 billion people live in disaster-vulnerable regions. When the towers fall, the swarm keeps going. FieldAgent. Apache-2.0 on GitHub."

**Reference assets:**
- `docs_assets/beat5-offline-proof.mp4` — captured per `docs/runbooks/mcp-dom-verification.md` "Beat 5 offline-proof capture path" against the real running stack (no synth WS). Operator drives wifi-down at scenario t≈100, wifi-up at t≈190; the in-sim `egs_link_drop`/`egs_link_restore` events at t=120/t=180 are the load-bearing offline-proof markers, not the WAN state itself. The connectivity-probe pane is in the frame as additional evidence.
- Apache-2.0 `LICENSE` file lives at the repo root (committed 2026-05-07). The voiceover may name the license explicitly.

> **Buffer-overflow caveat.** The drone-side `FindingBuffer` is bounded at 1 000 entries (`deque(maxlen=1000)`). In standalone windows longer than ~16 minutes (1 000 findings × ~1/min), oldest entries fall off both the in-memory deque and the JSONL drain replay. The Beat 5 capture window is 60 s — three orders of magnitude inside that envelope — but the limit is documented in `docs/plans/2026-05-10-beat5-path-a-full.md` §4 Component 3 (buffer overflow policy) and in `agents/drone_agent/finding_buffer.py`'s module docstring.

## Pre-Flight Checklist — what must ship before this storyboard can be filmed

The storyboard above assumes a fully integrated stack. As of today, several beats depend on components that haven't landed yet. Before scheduling a capture session, verify:

| Beat | Depends on | Owner | Today's state |
|---|---|---|---|
| 3b drone-eye reasoning trace + `report_finding` overlay | `agents/drone_agent/main.py` publishing real findings on `drones.<id>.findings` | Kaleel | ✅ Done. Live Gemma fires `report_finding` on CC0 FEMA Katrina image; 5× verified 2026-05-06 (`docs/sim-live-run-notes.md` Gap #2). DOM render verified end-to-end by `frontend/ws_bridge/tests/test_e2e_playwright_dom_render.py` and MCP capture per `docs/runbooks/mcp-dom-verification.md`; reference asset `docs_assets/dashboard-finding-rendered.png`. |
| 3c "EGS hallucinates 27 of 25 points → caught → corrected" | `agents/egs_agent/replanning.py` retry loop + dashboard `ValidationWowBanner` rendering `replan_in_flight_attempt_log` from `egs_state` | Ibrahim (backend stolen from Qasim 2026-05-12); Qasim (Phase 5 live eval + latency, reassigned 2026-05-13 — needs CUDA box) | ✅ Code shipped 2026-05-12, commit `3b86d9a`. ✅ Reference PNGs captured 2026-05-12 (`docs_assets/dashboard-validation-wow-{failed,passed}.png` via synth-WS Playwright path). ⚠️ Phase 5 live-eval + p50/p95 latency rerun on CUDA box still pending — reassigned to Qasim 2026-05-13 because M1 16GB couldn't carry `gemma4:e4b` at usable speed. Capture-day rerun of `scripts/check_wow_moment.sh` stays on Ibrahim's plate; PNG fallback is the safety net per Sub-beat 3c capture strategy. Plan: `docs/plans/2026-05-12-gate4-wow-moment.md`. |
| 4 `command_translation` showing Spanish input → structured task | EGS Gemma 4 E4B path producing real `preview_text_in_operator_language` (TODOS.md tracks this as a Phase 5+ stub) | Qasim | ✅ Done. Gemma 4 E4B translates commands accurately and handles Flutter dashboard timeouts correctly. Reference asset: `docs_assets/dashboard-multilingual-spanish.png` (captured 2026-05-09 via Playwright MCP against real E4B). |
| 4 `EGS LINK SEVERED` card + "STANDALONE MODE ACTIVE" panel state | Dashboard rendering EGS-offline state | Person 4 (Ibrahim) | ✅ Dashboard side ready 2026-05-07 — banner triggers on egs.state heartbeat staleness >5s, badge keys off `agent_status == "standalone"`. Both have stable `Semantics(identifier: ...)` hooks for Playwright/MCP capture. Awaits Kaleel's runtime `agent_status` flips (TODOS.md "Wire `agent_status` flips") to fully light up under live sim. |
| 4 `egs_link_drop` event firing in sim | `sim/scenarios/resilience_v1.yaml` — already ships `egs_link_drop` at t=120s and `egs_link_restore` at t=180s | Hazim | ✅ Done |
| 5 offline proof terminal + `ollama list` showing two models | Demo box has both Gemma 4 tags pulled per `docs/20-integration-contracts.md` | Person 4 (demo box owner) | Verify on Day 14 |
| 5 disconnection-tolerant findings — drone3 buffers + replays a finding across the 60 s standalone window | Path A-full components 1–6 wired (drone-side buffer, link-state monitor, mesh-sim findings gate, EGS dedup, sim scripted-events publish, counter durability) | Person 4 (Ibrahim) | ✅ Code + tests landed 2026-05-10 (Wave 1/2/3a). Wave 3b ships `agents/egs_agent/tests/test_e2e_link_drop_replay.py` (real-redis e2e), `frontend/ws_bridge/tests/test_e2e_playwright_beat5_offline_recovery.py` (synth-WS Playwright), `scripts/run_beat5_capture.sh` (capture rig), `scripts/check_beat5.py` (programmatic verifier covering A1–A6). Capture runbook in `docs/runbooks/mcp-dom-verification.md` "Beat 5 offline-proof capture path". |

The Pre-Flight Checklist is the operational counterpart to the storyboard. **Do not schedule a capture session until every row has a green check.** If a row is still red on Day 14 (May 16), fall back to the Backup Beat 4 below and / or reduce Beat 3c to the Backup Hallucination Trigger described in `docs/10-validation-and-retry-loop.md` Approach 2 / Approach 3.

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

4. **Edit in DaVinci Resolve** (free) or any video editor familiar to Ibrahim.

5. **For deterministic single-frame demo captures** (e.g., the Beat 3b finding-rendered hero shot), use the procedure in [`docs/runbooks/mcp-dom-verification.md`](runbooks/mcp-dom-verification.md). The MOCK Ollama path produces the same `report_finding` deterministically in ~1 second; the LIVE path uses real Gemma 4 E2B and matches the recorded video. Reference asset already captured: `docs_assets/dashboard-finding-rendered.png`.

### Visual Style

- **Color palette:** dark backgrounds (terminal, sim view) with bright accent colors for the dashboard (greens for success, red for failures)
- **Typography:** sans-serif throughout, bold for emphasis
- **Transitions:** quick cuts (no fades). Hackathon judges have short attention spans.
- **Music:** subtle, urgent, no lyrics. Royalty-free from YouTube Audio Library or similar.
- **Captions:** present throughout for accessibility and silent viewing

### Narration

Narration is optional. If included:
- Ibrahim records (or another team member with a clear voice)
- Quiet room, decent USB mic
- Pace: ~165 words per minute
- Total words: ~289 for 1:45 (was ~245 for 90s — extra ~44 words allocated to Beat 5)

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

A sketched storyboard exists in `docs_assets/storyboard.png` (Ibrahim creates this Day 14). Each beat has 2-4 frame sketches showing what the camera/screen displays.

## Test Audience

Before locking the video, show it to 3 people who don't know the project:

1. Can they explain what the project does? (If no, the pitch is unclear — strengthen Beat 1 / Beat 3a)
2. Did they understand the offline angle? (If no, strengthen Beat 5)
3. Did they notice the validation correction? (If no, slow down Beat 3c — see Sub-beat 3c capture strategy)
4. Was the video too long, too short, or the right length? (Kaggle cap is 3:00; our locked target is 1:45 — Beat 5 was extended from 10s to 25s on 2026-05-13. If "too short to follow," extend further toward 2:00; if "drags in the middle," tighten Beat 3 not Beat 5.)
5. **Did the story land emotionally?** (Kaggle "Video Pitch & Storytelling" is worth 30/100 points. If the answer is "I understood it but didn't feel it," the Beat 1 hook needs more concrete imagery — Eaton Fire stakes, named volunteer, downed cell tower.)

Iterate based on feedback. **Lock by Day 15 (May 17) end of day.** Day 16 (May 18) is GATE 5 + SUBMIT; no video changes after Day 15 except for hard-stop bug fixes.

## Cross-References

- The architecture being demonstrated: [`04-system-architecture.md`](04-system-architecture.md)
- The validation loop that catches the hallucination: [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md)
- The multilingual capability shown: [`07-operator-interface.md`](07-operator-interface.md)
- The resilience scenarios: [`08-mesh-communication.md`](08-mesh-communication.md)
- What goes in the writeup that complements this video: [`22-writeup-outline.md`](22-writeup-outline.md)
