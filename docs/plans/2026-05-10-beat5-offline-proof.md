# Plan: Beat 5 — Offline-Proof Scripting

**Owner:** Person 4 (Ibrahim)
**Date drafted:** 2026-05-10 (Day 10 / 8 days to deadline)
**Storyboard target:** `docs/21-demo-storyboard.md` Beat 5 (currently lines 108–120, the closer)
**Dependencies in play:** `sim/scenarios/resilience_v1.yaml` (existing scripted `egs_link_drop` t=120 / `egs_link_restore` t=180); `frontend/flutter_dashboard/lib/main.dart` (`EgsLinkSeveredBanner`, banner triggers on `egs.state` heartbeat staleness >5s); `frontend/flutter_dashboard/lib/widgets/drone_status_panel.dart` (`_StandaloneBadge`, keys off `agent_status == "standalone"`); `agents/egs_agent/scenario_state.py`; `frontend/ws_bridge/tests/test_e2e_playwright_standalone_mode.py` (synth-WS pattern); `docs/runbooks/mcp-dom-verification.md` Beat 4 capture path (model to mirror).

---

## Why this beat exists / why current draft is weak

The pitch is: *"survives total internet failure."* Beat 5 is the only place in the 90-second video where that claim is *demonstrated* rather than asserted. The existing storyboard (lines 108–120) covers it with a terminal pane showing `ifconfig` (no active interface) and `ollama list` (two local models). That is **passive proof**: the screen shows a static state of the world, not the system *operating* under that state.

Two concrete weaknesses with the current draft:

1. **Cause-and-effect is implicit.** The judge sees "no internet" and "models local" but never sees the system *do something* during the no-internet window. There is no on-screen moment that connects "wifi off" to "drone keeps making decisions."
2. **The "reconnect → state syncs" claim in the user's request isn't in the storyboard at all.** That's the strongest single image in this beat (no data lost during outage) and the storyboard currently does not script it.

This plan replaces lines 108–120 with a Beat 5 that has on-screen *action* during the offline window and an explicit "state backfilled" moment on reconnect.

---

## Design decision D1 — what "offline" looks like

**Locked:** `sudo ifconfig en0 down` + `sudo ifconfig awdl0 down` on a recording-friendly terminal pane visible in OBS, paired with a continuously-running external-connectivity probe (`curl https://www.google.com -m 2 -w "%{http_code}\n"` on a 1 Hz loop) on a second terminal pane. The probe flips from `200` (green) to `000` (red, timeout) at the moment the operator drops the interface, and back to `200` when the operator brings it up.

**Why not airplane mode toggle:** Apple Silicon airplane mode is buried behind a chord and produces no on-screen feedback inside a recording — the judge would have to take the operator's word for it. Visible terminal commands + a probe pane that flips color is unambiguous.

**Why `en0` + `awdl0`:** `en0` covers Wi-Fi/Ethernet; `awdl0` covers Apple Wireless Direct Link (AirDrop / continuity), which on some Macs keeps a route alive even with `en0` down. Bringing both down is the belt-and-braces approach. Loopback (`lo0`) stays up — that's what Redis/Ollama/the bridge/Flutter all use, so the demo continues operating.

**What this does NOT do:** it does not prove there's no cellular tether or hotspot fallback. We address this in voiceover ("the laptop has no SIM and is not tethered") rather than on-screen — judges will accept that framing for a 90-second video.

## Design decision D2 — what "state syncs" looks like

**Locked:** lean on the already-scripted `resilience_v1.yaml` events at t=120 (`egs_link_drop`) and t=180 (`egs_link_restore`). During the 60-second drop window, drone3 enters standalone mode, generates a finding, and the EGS does not see it. On link restore, the drone3 standalone badge clears, the EGS LINK SEVERED banner clears, and the drone3-while-standalone finding appears in `egs.state.findings_count_by_type` — visible as a chip increment in the dashboard's findings panel.

This is the strongest single image in the beat: a counter that ticks up *after* the link restores, demonstrating that the data was held during the outage and delivered on reconnect. It is also fully driven by existing scenario events; no new scripted-event types need to land.

**Honesty caveat:** the "drone3 generates a finding while standalone, then it appears on reconnect" loop currently depends on **Kaleel flipping `agent_status` to `"standalone"` at runtime** (TODOS.md "Wire `agent_status` flips in drone state republish"). As of today this is on Kaleel's plate and not yet shipped. See risk R1 below for the fallback.

## Design decision D3 — does the offline window cover the link-drop, or is it concurrent

**Locked:** the operator drops `en0` *before* the scripted `egs_link_drop` event fires, and brings it back up *after* `egs_link_restore`. The full link-drop window is inside the wifi-off window. This way the judge sees:

1. Wifi off → external probe goes red.
2. Inside the wifi-off window: dashboard banner appears (EGS link severed inside the swarm), then disappears (link restored), and counter ticks up.
3. Wifi back on → external probe goes green.
4. *Caption:* "Every decision in that window happened on this laptop. Nothing reached the cloud, because the cloud isn't there."

This sequencing makes the two proofs reinforce each other rather than competing for the judge's attention.

---

## Mechanics — exact on-screen sequence (10s of video)

Beat 5 budget: 1:20–1:30 (10 seconds). Frame-by-frame:

| t (within beat) | Operator action | Dashboard | Terminal A (cmd) | Terminal B (probe) | Caption |
|---|---|---|---|---|---|
| 0.0s | — | normal: 3 drones active, 0 findings | (idle) | `200 200 200` (green) | "All decisions on this laptop." |
| 1.0s | `sudo ifconfig en0 down && sudo ifconfig awdl0 down` | unchanged | (cmd visible) | `200 → 000` (flips red) | "Wi-Fi: off. Cellular: none." |
| 3.0s | — | EGS LINK SEVERED banner appears, drone3 STANDALONE badge lights | (idle) | `000 000 000` | "Inside the swarm: link to drone3 also drops." |
| 5.5s | — | drone3 logs `report_finding` (visible as a console-overlay line; no chip increment yet) | (idle) | `000` | "drone3 keeps reasoning. Alone." |
| 7.0s | — | banner clears; standalone badge clears; victim chip ticks `0 → 1` | (idle) | `000` | "Link restored. Finding backfilled." |
| 8.5s | `sudo ifconfig en0 up && sudo ifconfig awdl0 up` | unchanged | (cmd visible) | `000 → 200` (flips green) | "Network back. Nothing was reached." |
| 10s | — | — | — | — | "FieldAgent. Apache-2.0 on GitHub." |

The closer line + URL plate runs over the final 2 seconds.

---

## Implementation tasks (ordered)

### Task 1 — Capture-rig orchestrator: `scripts/run_beat5_capture.sh`

A shell orchestrator analogous to `scripts/run_hybrid_demo.sh` but locked to `resilience_v1` and tuned for screen-recording rather than tmux. Responsibilities:

- Pick free ephemeral ports for redis / bridge / Flutter HTTP server (mirror the Beat 4 runbook pattern).
- Start redis, EGS (with `REDIS_URL` env override), sim (`waypoint_runner` + `frame_server`), three drone agents (drone1, drone2, drone3), bridge, Flutter static server. Pre-warm Ollama with E2B + E4B `/api/chat` calls before the operator hits record.
- Tee a one-line operator-facing status to stdout: "ready to record — open dashboard at http://127.0.0.1:<FLUTTER>/ ; offline window is t≈120s–180s in scenario time".
- Print the exact `sudo ifconfig` commands to copy/paste into Terminal A.
- Print the exact `while true; do curl ... done` invocation for Terminal B.

The operator runs this once, waits for the "ready to record" line, then drives the recording manually.

**Why a shell script and not a Python orchestrator:** screen-recording sessions are operator-driven; the script just brings up state and gets out of the way. Mirrors the Beat 4 runbook, which is field-tested.

### Task 2 — Connectivity-probe one-liner (no new file)

The probe is just:

```bash
while true; do
  printf "[%(%H:%M:%S)T] %s\n" -1 "$(curl -s -o /dev/null -w "%{http_code}" -m 2 https://www.google.com)"
  sleep 1
done
```

Document this in the runbook section (Task 4); no new committed file.

**Why no Python wrapper:** zero dependencies, runs on any Mac, easy for Hazim or Thayyil to run on a backup machine without a uv install.

### Task 3 — Verifier: `scripts/check_beat5.py`

Programmatic pass/fail without a human eye, mirroring `scripts/check_hybrid_demo.py`. Subscribes to the bridge WebSocket and the drone-agent validation-events log. Asserts:

- A1 — drone3 enters `agent_status == "standalone"` between scenario t=120 and t=130 (10s grace).
- A2 — drone3 publishes at least one Contract-4 finding while standalone (validation_events.jsonl grep, accepted=true, scenario time ∈ [120, 180]).
- A3 — within 5s of `egs_link_restore` (t=180), `egs.state.findings_count_by_type` reflects the drone3-while-standalone finding (chip increment).
- A4 — drone3 returns to `agent_status == "active"` after t=180.

Exit 0 / non-zero for CI integration.

**Why a verifier, not just an eyeball check:** the demo will be re-recorded ~50 times per the storyboard production notes. We need a `pytest`-style green-light per take, and the verifier becomes the regression test for Kaleel's `agent_status` flips landing — first run that passes A1+A2+A4 cleanly is the unblock signal.

### Task 4 — Runbook: append "Beat 5 offline-proof capture path" section to `docs/runbooks/mcp-dom-verification.md`

Mirrors the Beat 3 / Beat 4 sections in that file:

1. Pick free ports + log dir.
2. Pre-warm Ollama (E2B + E4B), confirm 200 OK.
3. Boot order: redis → EGS (with `REDIS_URL` override) → sim → 3 drone agents → bridge → Flutter static server.
4. Operator opens two terminal panes (A: command shell; B: connectivity probe loop).
5. Operator hits record, waits for the recording timeline cue from `run_beat5_capture.sh`'s status line, then runs `sudo ifconfig en0 down && sudo ifconfig awdl0 down` at scenario t≈100s (20s before scripted `egs_link_drop`).
6. Operator brings interfaces back up at t≈190s (10s after scripted `egs_link_restore`).
7. Run `scripts/check_beat5.py` against the same redis port to verify the run is gradeable.
8. Save the screen recording to `docs_assets/beat5-offline-proof-<timestamp>.mp4` (gitignored; final cut goes to the video editor outside the repo).

### Task 5 — Storyboard rewrite: replace lines 108–120 of `docs/21-demo-storyboard.md`

Replace the current Beat 5 block with the frame-by-frame table above (Mechanics section), plus:

- A "Reference assets" bullet pointing at the runbook section from Task 4.
- A "Pre-Flight Checklist" row update — Beat 5's row currently says "Verify on Day 14"; tighten to "Capture-rig: `scripts/run_beat5_capture.sh` — verify Day 12 with Hazim's resilience_v1 polish; capture takes Day 14."

### Task 6 — Synthetic-WS fallback for Beat 4-style capture (R1 mitigation)

If Kaleel hasn't shipped `agent_status` flips by Day 13, drop to a synth-WS playback of the resilience timeline modeled on `frontend/ws_bridge/tests/test_e2e_playwright_standalone_mode.py`'s pattern. The synth-WS replays a pre-canned envelope sequence (link OK → standalone → link OK with chip increment). Capture is visually identical to the live path; voiceover stays honest because the data shape on the wire is identical to what live drone3 would publish.

This task only fires if R1 triggers. Sketch the synth playback file location now (`scripts/beat5_synth_replay.py`) but don't ship until Day 13 if needed.

### Task 7 — Regression test: `frontend/ws_bridge/tests/test_e2e_playwright_beat5_offline_recovery.py`

Synth-WS-driven Playwright e2e, no real network manipulation. Replays the resilience timeline in compressed time (10s instead of 240s) and asserts:

- The `EgsLinkSeveredBanner` appears for the duration of the synthetic standalone window.
- The `drone3` STANDALONE badge appears with stable `Semantics(identifier: 'standalone-badge-drone3')`.
- The findings count chip for the drone3-while-standalone finding type increments after the synthetic restore envelope.

This is the sustaining test that catches dashboard regressions on Beat 5 between now and submission. Lives in CI's `bridge_e2e` job.

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **R1 — Kaleel's `agent_status` flips not shipped by Day 13** | Medium (open TODO; depends on his GATE 3 priorities) | High — Beat 5 unfilmable on the live path | Task 6: synth-WS playback. Honesty-preserved because envelope shape is identical; voiceover frames it as "this is what the dashboard shows when drone3 is standalone" without claiming it's a one-shot live capture. |
| **R2 — `sudo ifconfig en0 down` triggers the password prompt mid-recording** | Medium (default macOS behavior on a fresh shell) | Medium — breaks the recording take | Pre-elevate via `sudo -v` at the top of `run_beat5_capture.sh`, OR document a NOPASSWD sudoers line for `ifconfig` in the runbook (operator-only, demo-machine-only). Choose the latter — `sudo -v` expires in 5 minutes by default, often shorter than scenario t=100. |
| **R3 — `awdl0` doesn't exist on the demo machine** (varies by macOS version) | Low | Low — `ifconfig awdl0 down` errors but doesn't break en0 down | Tolerate the error (`|| true`) in the runbook one-liner; document that some Macs don't have awdl0 and en0 alone is sufficient for the proof. |
| **R4 — Connectivity probe shows `200` even with `en0` down** (cached DNS, browser hold-open, etc.) | Low | High — undermines the whole proof on screen | Use `curl -m 2` (timeout) and a fresh hostname every probe (rotate `google.com` / `cloudflare.com` / `apple.com`) to defeat caches. Test the rig on Day 12 to confirm the flip-to-000 is reliable. |
| **R5 — Recording capture timing drift** (operator hits down at the wrong scenario tick) | Medium | Medium — beat misses the link-drop window | `run_beat5_capture.sh`'s status line should print scenario time once per second so the operator can pace by the clock, not the wall. |
| **R6 — `findings_count_by_type` chip increment isn't visually distinct enough on a fast-cut video** | Medium | Medium — "state backfilled" image fails to land | Add a 1.5s pulse animation to the chip on increment (already exists for finding tiles; check `findings_panel.dart` and extend if needed). Check on Day 11 — if not present, decide pulse vs flash vs growth. |

---

## What this plan does NOT cover

- **Demo video editing.** That's a Day 14–16 task on a different track (DaVinci Resolve, narration, music). This plan delivers the *capture-able take*, not the cut.
- **The Beat 5 closing voiceover line.** Scripted in Day 14 demo prep; the storyboard reserves the slot but the exact wording lands then.
- **Two-machine backup.** That's a separate Day 15 item; Beat 5 is captured on the primary demo box.
- **Kaleel's `agent_status` work.** Listed as a dependency, not a task in this plan. We're either consuming his work (live path) or routing around it (synth path, R1).

## Acceptance criteria

This plan is "done" when:

1. `scripts/run_beat5_capture.sh` brings the full stack up, prints "ready to record" within 30s on the demo machine, and `scripts/check_beat5.py` exits 0 against a complete uninterrupted run of `resilience_v1`.
2. `docs/21-demo-storyboard.md` Beat 5 reads the frame-by-frame table from this plan, with the reference asset row pointing at the new runbook section.
3. `docs/runbooks/mcp-dom-verification.md` has a "Beat 5 offline-proof capture path" section that mirrors the Beat 3 / Beat 4 sections.
4. `frontend/ws_bridge/tests/test_e2e_playwright_beat5_offline_recovery.py` is green in CI.
5. Either: (a) live capture with Kaleel's `agent_status` flips lands at `docs_assets/beat5-offline-proof.mp4` by Day 14; or (b) synth-WS fallback (Task 6) is staged and tested, with the live-vs-synth decision documented in the runbook.

---

## Estimated effort

- Task 1 (orchestrator): 1.5h
- Task 2 (probe one-liner): 0.1h (just docs)
- Task 3 (verifier): 1.5h
- Task 4 (runbook section): 1h
- Task 5 (storyboard rewrite): 0.5h
- Task 6 (synth fallback, contingent): 1.5h if R1 fires
- Task 7 (regression test): 2h

**Total non-contingent: ~6.5h.** Fits a single Day 10 push if uninterrupted.

**Sequencing:** 5 → 1 → 4 → 3 → 7 → 6 (only if R1 fires). Storyboard rewrite first locks the exact frame-by-frame so the orchestrator/verifier targets are unambiguous.
