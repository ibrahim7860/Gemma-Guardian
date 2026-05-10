# Beat 5 Video Capture Plan

**Owner:** Ibrahim (Person 4 — Frontend + Demo + Comms)
**Date drafted:** 2026-05-10
**Target capture day:** Day 12 (Wednesday May 14), with Day 13–14 as catch-up windows
**Submission deadline:** Sunday May 18, 23:59 UTC
**Trigger:** PR #41 shipped Path A-full infrastructure that makes Beat 5 filmable. PR #42/#43 patched the EGS-coords trap that would have left the demo dashboard blank. The plumbing is done. This plan is the execution plan for the actual screen recording.

## Goal

Produce `docs_assets/beat5-offline-proof.mp4` — a single ~30 s screen-capture clip that, when cut into the 1:20–1:30 slot of the submission video, shows:

1. The dashboard severs from EGS (banner + STANDALONE badge attach on drone3).
2. drone3 keeps flying, produces a `report_finding` while severed (visible only in the per-drone reasoning trace, NOT in the EGS-side findings count).
3. On reconnect, the buffered finding is replayed; the EGS `findings_count_by_type.victim` chip ticks once; the banner clears; the badge falls off.
4. A terminal pane shows `WAN: DOWN` during the standalone window and `ollama list` showing both Gemma 4 tags cached locally — sealing the offline-by-construction claim.

The clip must satisfy `scripts/check_beat5.py` A1–A6 PASS in the same recorded run. Without that, the take is not usable.

**Out of scope:** the rest of the 90 s submission video (Beats 1–4), the writeup, README, Kaggle form. Those are separate Day 14–16 work.

## What's in scope

- One usable take of the Beat 5 mechanic recorded as a screen capture, plus 2–4 backup takes.
- Verification that the chosen take passes `check_beat5.py`.
- Light post-capture trim to ~30 s ready for the editor (Day 14–16) to splice. No effects, no music, no titles — those happen at edit time.
- A second-machine backup of the raw `.mov` / `.mp4` files plus the `$DEMO_DIR` artifacts (`validation_events.jsonl`, mesh.log, drone logs) per the two-machine backup line item in plan §11 of `docs/plans/2026-05-10-beat5-path-a-full.md`.

## What's NOT in scope

- The video edit itself (Days 14–16, separate plan).
- Capturing Beats 1–4 (already have reference screenshots; full video capture pass for those beats is its own session).
- Any further code changes to the buffer / link / mesh-gate path. If something breaks during capture, fall back to a previously-validated commit, not a new fix.
- Multilingual command path footage (Beat 4) — separately captured, already a green item.

## Prerequisites — must be GREEN before scheduling capture

A capture session is expensive: 4-minute scenario tick + retakes + verification. Don't sit down to film unless every box below is checked.

| # | Prereq | Verify by | Owner |
|---|---|---|---|
| 1 | All Path A-full code merged on main | `git log --oneline -10` shows 297bea4 (PR #41), e0aa2f3 (#42), 479de1b (#43) | Ibrahim ✅ |
| 2 | Both Gemma 4 tags pulled and warm | `ollama list` lists `gemma4:e2b` and `gemma4:e4b`; both respond to a `/api/chat` ping in <2 s once warm | Ibrahim, on demo machine |
| 3 | `pytest agents/egs_agent/tests/test_e2e_link_drop_replay.py -v` PASS | Real-redis e2e for the wire-level invariants | Ibrahim |
| 4 | `pytest frontend/ws_bridge/tests/test_e2e_playwright_beat5_offline_recovery.py -m e2e -v` PASS | Synth-WS dashboard render check | Ibrahim |
| 5 | `pytest frontend/ws_bridge/tests/test_e2e_playwright.py frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py -m e2e -v` PASS | CI Playwright sweep, regression guard for the mesh-sim coords fix | Ibrahim |
| 6 | `bash scripts/run_beat5_capture.sh --dry-run` (or full run) on the demo machine ends with `check_beat5.py` A1–A6 PASS | End-to-end smoke pass on the actual hardware before recording | Ibrahim |
| 7 | resilience_v1 scenario fires `egs_link_drop` at t=120 and `egs_link_restore` at t=180 | `grep egs_link sim/scenarios/resilience_v1.yaml` matches | Hazim ✅ (already shipped) |
| 8 | OBS Studio (or QuickTime Screen Recording) installed and tested on demo machine | (a) Test recording of 60 s, output plays cleanly. (b) `df -h ~/Movies` shows ≥10 GB free on the takes output volume — ProRes 1080p60 at 4 min/take ≈ 1.6 GB; planning for 5 takes ≈ 8 GB. (c) Inspect the test recording for dropped frames (OBS: Tools → Stats; QuickTime: visual sanity check). Silent drop = silent demo-day pain. | Ibrahim |
| 9 | Apache-2.0 LICENSE file at repo root | `ls LICENSE` | Ibrahim ✅ |
| 10 | drone3 fires `report_finding` reliably during the t∈[120,180] standalone window | Day 11: run the full stack against `resilience_v1` 3 times in a row. After each run, `grep '"drone_id":"drone3"' $LOG_DIR/validation_events.jsonl` must show at least one `report_finding` with a timestamp inside the standalone window. Acceptance: 3/3 hits. 2/3 = re-tune drone3's frame mapping in `sim/scenarios/resilience_v1.yaml` before Day 12. ≤1/3 = fall back to `scripts/ollama_mock_server.py` for the take (flag in plan §"Failure modes"). | Ibrahim, with Kaleel on call if frame mapping needs to change. STATUS: live `report_finding` is verified on drone1 against a FEMA Katrina image (2026-05-06, 5× runs) — drone3 specifically is the gap this check closes. |

If any of 1–10 fails, do not record. Diagnose, fix, re-verify. Capture sessions on a broken stack waste a half-day.

### Between-take prewarm rule

Ollama model state goes stale. Once the first call lands, both models stay warm for roughly 5 minutes of idleness. If a take fails and the operator spends >5 minutes diagnosing (reading logs, restarting the stack, re-running `check_beat5.py`), the first E4B call in the NEXT take may pay the ~99 s Apple Silicon cold-load penalty inside the recorded window. That penalty bleeds into the offline-proof timeline and can cost A2 (drone3 `report_finding` missing because Gemma didn't respond yet).

**Rule:** any time more than 5 minutes pass between the last successful pacer tick and the start of a new take, re-run the prewarm one-liner from §"Pre-capture dry run" step 2 before launching the rig. The capture rig does NOT currently enforce this; it's on the operator. (See TODOS.md for the deferred auto-reprewarm idea.)

## Demo machine choice

The capture must happen on **one fixed machine** for the whole submission video. The team's stack is cross-platform but Ollama cold-load times differ by 10×+ across CPU/GPU. Capturing Beat 5 on machine A and Beat 4 on machine B will show font/color/rendering drift in the final cut.

**Recommended:** Ibrahim's primary dev machine (Apple Silicon, macOS), the one already used to capture `dashboard-finding-rendered.png` / `dashboard-egs-severed.png` / `dashboard-beat5-phase3-restored.png`. That machine is already known-good for the dashboard render and runs both Gemma 4 tags via Ollama Metal.

**Risk:** Apple Silicon E4B cold-load is ~99 s per the runbook ("Recovering from common failures" section). Pre-warming both models before hitting record is non-negotiable. The capture rig does this automatically; verify the prewarm log shows both tags responded before the READY banner.

**Backup plan:** if the primary demo machine has a hardware issue on Day 12, fall back to the team Linux box (Hazim has CUDA + Ollama tested). Re-run prereqs 2–6 on that box first; do NOT use a half-tested fallback.

## Pre-capture dry run (Day 12 morning — 60 min)

Before the recorded take, do a full dry run to surface any environment drift since the last green test sweep.

1. Open a fresh terminal on the demo machine. Confirm `git status` clean, `git rev-parse HEAD` matches origin/main.
2. `ollama list`, then warm both models:
   ```bash
   for M in gemma4:e2b gemma4:e4b; do
     time curl -fsS -X POST http://127.0.0.1:11434/api/chat \
       -H 'content-type: application/json' \
       -d "{\"model\":\"$M\",\"stream\":false,\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}]}" > /dev/null
   done
   ```
   First call may take 60–120 s, second should be <2 s. If the cold load takes >180 s, retry; consistent failure means re-pull the model.
3. Run the prereq pytest sweep (items 3, 4, 5 of the table). If anything red, fix before proceeding.
4. Run the full capture rig WITHOUT recording:
   ```bash
   bash scripts/run_beat5_capture.sh
   ```
   Watch the pacer print `scenario_tick=` lines from 0 to 240. At t≈100 drop wifi (pane A), at t≈190 bring it back. Pane B's connectivity-probe must show `WAN: DOWN` for the gap. Dashboard must show banner attach at t=120, finding tile appear at t=181, banner clear at t=181.
5. After the run, execute `scripts/check_beat5.py` and confirm A1–A6 PASS. If anything fails, reference the runbook §6 troubleshooting table, fix, retry. Do not record until a clean dry run passes.
6. Tear down: `bash scripts/run_beat5_capture.sh --teardown`.

## Capture session (Day 12 afternoon — 90 min)

### Recorder setup

- **OBS Studio:** display capture of the demo machine's primary monitor at 1920×1080 (or native if higher), 30 fps minimum, 60 fps preferred for crisp dashboard animation. Audio: system audio OFF (the demo video is silent + voiceover-overdubbed). Output format `.mov` (ProRes if disk allows) or `.mp4` H.264 at 8–12 Mbps. File destination: `~/Movies/beat5_takes/take_NN.mov`.
- **Window layout (locked):**
  - Top-left: dashboard browser tab at `http://127.0.0.1:$FLUTTER_PORT/?ws=ws://127.0.0.1:$BRIDGE_PORT`. Resize to ~70% of display.
  - Top-right: terminal pane B (connectivity probe loop). Font size large enough to read on a 1080p video frame (16–18 pt minimum).
  - Bottom-right: terminal pane A (wifi-drop / wifi-restore commands plus a final `ollama list` at the very end).
  - The pacer print loop runs in a third pane that stays visible — viewers don't need to read it but the editor uses it as the timing reference for cuts.
- **Cursor:** make the system cursor large and high-contrast; viewers will track it during the wifi-drop moment.
- **Notifications:** turn on Do Not Disturb; quit Slack, Mail, browser notifications.

### Take procedure

For each take (plan for 3–5 takes, keep the cleanest):

1. `bash scripts/run_beat5_capture.sh` — wait for the READY banner. Pacer is now ticking.
2. Hit OBS Start Recording the moment pacer prints `scenario_tick=80s` (gives you 20 s of "steady state" headroom before the drop).
3. At pacer `scenario_tick=100s`, paste the wifi-drop command in pane A and hit enter. Watch pane B flip to `WAN: DOWN` within 1–2 s.
4. Hold steady. At pacer `scenario_tick=120s`, the in-sim `egs_link_drop` fires → banner attaches, drone3 STANDALONE badge attaches. This is the load-bearing moment; do not move the cursor.
5. From t=120 → t=180, drone3 keeps moving on the map. At some point the per-drone reasoning trace shows `finding produced (buffered)`. The findings-count chip does NOT change. This silence is the proof.
6. At pacer `scenario_tick=190s`, run wifi-up in pane A. Pane B returns to `WAN: up`. The in-sim `egs_link_restore` already fired at t=180 — banner cleared, badge dropped, finding tile appeared, victim chip ticked. Captured.
7. After pacer hits `scenario_tick=210s`, pane A: run `ollama list`. Output prints both tags cached locally. This is the offline-by-construction seal.
8. Stop OBS recording at pacer `scenario_tick=215s` (5 s of trailing footage for clean edit cut).
9. Run `scripts/check_beat5.py`. If A1–A6 PASS, save the take. If not, discard the file (rename `.mov` to `.bad.mov` so it's clearly not the keeper).
10. Tear down with `--teardown`. Repeat for next take.

Plan for 5 takes. Keep all that pass `check_beat5.py`. Pick the best two for hand-off (one primary, one backup).

### What "best" means

Among passing takes, prefer:
- **No cursor jitter** during t=120 → t=130 (banner attach) and t=180 → t=185 (replay tick).
- **Pane B probe loop visible** at the moment the operator hits wifi-drop.
- **Sharpest dashboard render** (no animation tearing on the banner attach — Apple Silicon at 60 fps on retina display is usually fine).
- **Cleanest `ollama list` output** (no shell prompt clutter, output centered in the terminal pane).

If two takes pass and look equally clean, prefer the later take — operator's pacing tends to settle by take 3.

## Verification & artifact bundle

For the chosen primary take, capture and commit (or upload alongside the video):

- `docs_assets/beat5-offline-proof.mp4` (the cut clip, ~30 s, trimmed from raw take to the t=80 → t=215 window).
- `$DEMO_DIR/validation_events.jsonl` (proves Gemma actually fired `report_finding` while standalone, ties the visual to the validation log).
- `$DEMO_DIR/mesh.log` (proves the link-state transitions on `mesh.link_status`).
- `$DEMO_DIR/drone3.log` (proves the drone-side BufferedPublisher buffered + drained).
- A copy of `scripts/check_beat5.py` output (text or screenshot of A1–A6 all PASS).

The trim itself is a single ffmpeg call — pad takes 5 s on either side, cut to 30 s:

```bash
ffmpeg -ss 80 -i ~/Movies/beat5_takes/take_03.mov -t 135 -c:v copy docs_assets/beat5-offline-proof.mp4
```

(Adjust `-ss` and `-t` against the take's pacer-aligned start. The editor on Days 14–16 will retrim with effects/transitions; this is the rough cut.)

## Failure modes & contingency

| Symptom | Likely cause | Recovery |
|---|---|---|
| `check_beat5.py` A2 fails: no drone3 `report_finding` in the standalone window | Gemma E2B didn't produce a tool call inside t∈[120,180] (cold load, prompt drift, stochastic) | Re-run. If 3 takes in a row fail A2, fall back to the mock Ollama path: `GG_OLLAMA_URL=http://127.0.0.1:<mock_port>` + `scripts/ollama_mock_server.py` (deterministic finding emission). Note in the writeup that the take uses a deterministic stub for repeatability. |
| Banner doesn't attach at t=120 | Mesh sim wasn't running (port collision) OR drone3 didn't subscribe to `mesh.link_status` | Check `$DEMO_DIR/mesh.log` for "subscribed" lines. Tear down, retry — usually a port left in TIME_WAIT from a prior run. |
| Banner attaches but finding tile never appears at t=181 | Mesh sim's `_link_down_overrides` didn't relax (no `egs_link_restore` received) OR BufferedPublisher didn't drain | Check `$DEMO_DIR/mesh.log` for "egs_link_restore" + drone3.log for "draining buffer". Most common cause: stale Redis state; teardown + retry. |
| Banner attaches at t=125 instead of t=120 (5 s late) | EGS heartbeat-staleness path fired before the explicit `mesh.link_status` event arrived | Cosmetic; still passes A1. The viewer won't notice 5 s drift; keep the take. |
| Pane B probe loop says `WAN: up` during the standalone window | Operator's wifi-drop didn't actually cut WAN (VPN, alternate interface, Bluetooth tether) | Disable any secondary network interface before the take. macOS: System Settings → Network → drop everything but Wi-Fi to "Inactive". |
| Demo machine hard-crashed mid-take | Memory pressure from holding two Gemma 4 models + Flutter web build + OBS | Restart, repull models, restart OBS at lower fps (30 fps), re-run prereqs. |

If three consecutive takes fail the same A-assertion, stop. Diagnose the root cause from logs before burning more time. Pull in Hazim if the failure is sim-side, Kaleel if the failure is in drone-agent reasoning.

## Hand-off to video edit (Day 14)

Deliverables to the editor (Ibrahim wears both hats — capture and edit — but write down the contract anyway):

1. `docs_assets/beat5-offline-proof.mp4` (rough cut, ~30 s).
2. The full raw take if longer than 30 s (so the editor can re-trim if the cut needs to be tightened to 10 s for the 1:20–1:30 slot).
3. The `validation_events.jsonl` excerpt covering the standalone window, in case a sub-shot needs the actual log text overlaid.
4. The voiceover line for Beat 5 (already in `docs/21-demo-storyboard.md`): *"3.6 billion people live in disaster-vulnerable regions. When the towers fall, the swarm keeps going. FieldAgent. Apache-2.0 on GitHub."*
5. A note flagging the load-bearing visual moments at t=120 (banner attach) and t=181 (finding tile attach) so the editor knows where to hold and where to cut.

## Backup strategy (Day 15 with Thayyil)

After a clean primary take is in hand:

1. Copy the raw take + the `$DEMO_DIR` artifacts + `docs_assets/beat5-offline-proof.mp4` to a second machine (Thayyil's box per plan §11).
2. Run `scripts/check_beat5.py` against the *artifacts* on the second machine to prove the run reproduces from logs alone (no Redis required for the assertion check — it parses JSONL).
3. Commit `docs_assets/beat5-offline-proof.mp4` to the repo (LFS not required at <30 s clip / <50 MB H.264). The raw take stays on local disk + cloud backup; only the trimmed cut goes in git.

## Schedule

| Day | Block | Activity |
|---|---|---|
| Day 12 (Wed May 14) AM | 60 min | Pre-capture dry run on demo machine. Verify all 9 prereqs. |
| Day 12 (Wed May 14) PM | 90 min | Capture session: 3–5 takes, pick best primary + backup. |
| Day 12 (Wed May 14) PM | 30 min | Trim primary to ~30 s, run `check_beat5.py` against the take's logs, save artifacts. |
| Day 13 (Thu May 15) | as needed | Re-capture if Day 12 didn't yield a clean take. |
| Day 14 (Fri May 16) | embedded in video edit block | Splice into the 90 s submission video. |
| Day 15 (Sat May 17) | with Thayyil | Two-machine backup of raw take + artifacts + final clip. |

If Day 12 yields a clean primary on take 1 or 2, Day 13 becomes catch-up time for any other beat that needs reshooting.

## Acceptance criteria (the definition of "done")

- `docs_assets/beat5-offline-proof.mp4` exists, plays cleanly, ~30 s.
- The clip's underlying take passes `scripts/check_beat5.py` A1–A6.
- The cut visually shows: banner attach (t=120), drone3 STANDALONE badge attach (t=120–121), `WAN: DOWN` in pane B for the gap, finding tile attach + victim chip increment (t=181), banner/badge clear (t=181), `ollama list` showing both Gemma 4 tags (t=210+).
- Raw take and `$DEMO_DIR` artifacts archived on a second machine. The backup-machine `check_beat5.py --ws-replay-log $LOG_DIR/ws_frames.jsonl --validation-log $LOG_DIR/validation_events.jsonl` invocation reproduces A1–A6 PASS from artifacts alone, confirming the take is reconstructable without a live bridge.
- Editor has the file path, voiceover line, and load-bearing-moment timestamps in writing.
- **Two-pair-of-eyes review:** the operator AND one teammate (Hazim, Thayyil, Kaleel, or Qasim — whoever is reachable) watch the chosen take end-to-end before declaring it final. Both must agree the banner-attach moment (t=120) and the finding-tile-attach moment (t=181) read clearly to a first-time viewer. Subjective UX moments are invisible to `check_beat5.py`; this catches cursor jitter, banner-attach tearing, and "I can't tell what just happened" framing that an exhausted operator stops seeing after 3 takes.

When all six are true, this plan is closed and Beat 5 is ready for the final video edit pass.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | ISSUES_OPEN | 7 issues, 1 critical gap (missing regression test for `--egs-lat`/`--egs-lon` in `scripts/launch_swarm.sh`) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 7 decisions awaiting user picks (Issues 1–7 + 1 TODO).
**VERDICT:** NOT CLEARED — eng review found 7 issues, including 1 critical regression-test gap. Resolve before scheduling Day 12 capture.
