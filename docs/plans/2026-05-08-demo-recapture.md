# Demo Screenshot Re-capture Plan (post PR #36)

**Owner:** Ibrahim (Person 4 — Frontend + Demo + Comms)
**Date:** 2026-05-08
**Trigger:** PR #36 (Task 8 of fixtures-swap) shipped the static aerial overlay
in the Flutter `map_panel`. Every committed `docs_assets/dashboard-*.png` was
captured before that overlay existed and now misrepresents the as-shipped UI.

## Goal

Re-capture all three demo screenshots so the storyboard, writeup, and any
external reviewer sees the same map panel users will see in the live demo:
a FEMA Mississippi aerial under the grid, drones + findings projected onto
real ground, white-pill drone-id labels, and the off-extents chevron pattern.

**Out of scope:** any video recording, any storyboard edits beyond swapping
the asset paths, any code changes. Pure capture pass.

## Targets

| Asset | Beat | Captures | Verifies |
|---|---|---|---|
| `docs_assets/dashboard-finding-rendered.png` | Beat 1/2 | finding tile in panel + map with aerial + drone markers | full agent → Redis → bridge → Flutter loop, aerial render |
| `docs_assets/dashboard-egs-state-counts.png` | Beat 3 | findings-count chips lit + map with aerial | EGS aggregation path + aerial render |
| `docs_assets/dashboard-egs-severed.png` | Beat 4 | red banner + drone3 STANDALONE badge + map with aerial | offline-mode UI + aerial still renders without bridge data flowing |

## Pre-flight (do once, before any capture)

1. Confirm we're on clean main with PR #36 merged:
   ```bash
   git status   # expect clean
   git rev-parse HEAD   # expect tip of main, descendant of 5ea6acb (PR #36 merge)
   git log --oneline -1 -- frontend/flutter_dashboard/lib/widgets/map_panel.dart
   # expect a commit from PR #36 (4066be7 or 5ea6acb merge)
   ```
2. Confirm aerial asset is byte-equal in both locations:
   ```bash
   uv run python scripts/sync_flutter_base_images.py --check
   # expect "OK: all tracked base images match" (exit 0)
   ```
3. Build Flutter web bundle once (all three captures reuse it):
   ```bash
   cd frontend/flutter_dashboard
   flutter build web --release
   cd -
   ls frontend/flutter_dashboard/build/web/assets/base_images/disaster_zone_v1_base.jpg
   # expect file present (proves pubspec.yaml asset declaration is wired)
   ```
4. Smoke-check the bundled aerial loads at the path map_panel will request:
   ```bash
   ( cd frontend/flutter_dashboard/build/web && python3 -m http.server 18888 --bind 127.0.0.1 ) &
   _SMOKE_PID=$!
   # Poll until the server is actually listening (sleep 1 races on slow boots).
   until curl -sf "http://127.0.0.1:18888/" >/dev/null 2>&1; do sleep 0.2; done
   curl -sI "http://127.0.0.1:18888/assets/assets/base_images/disaster_zone_v1_base.jpg" | head -1
   # expect HTTP/1.0 200 OK   (Flutter prefixes asset paths with assets/)
   kill "$_SMOKE_PID" 2>/dev/null   # kill by PID, not name (avoids nuking unrelated http.servers)
   ```
   If 404, the asset isn't in the bundle — stop and investigate before any capture.

5. Write `scripts/verify_demo_screenshot.py` (one-time, ~10 min). The
   captures' acceptance is otherwise eyeball-only — and the map_panel's
   `errorBuilder` falls back to grid-only if the aerial 404s, which is
   indistinguishable by eye from "aerial loaded but is dark imagery."
   Spec:
   - Args: `--png <path> --map-region x,y,w,h --min-stddev N`
   - Open PNG via PIL, crop to `--map-region`, compute the per-channel
     stddev. The aerial has photographic mid-tone variance (stddev ≥ ~25
     per channel on the 1440x673 capture). Pure grid-only renders
     uniform-dark (stddev < ~10).
   - Default thresholds: `--min-stddev 20`. Calibrate by running once
     against a known-good capture before committing the script itself.
   - Exit 0 if pass, 1 with a report on which channel failed.
   Run after every capture, BEFORE `git add`.

## Capture order (rationale: cheapest setup first)

### Viewport size (applies to ALL three captures)

Committed asset dimensions are inconsistent today: `dashboard-finding-rendered.png`
and `dashboard-egs-state-counts.png` are **1440x673**, while
`dashboard-egs-severed.png` is **2880x1800** (likely a Retina capture
artifact). The storyboard text overlays in After Effects are tuned to a
fixed canvas; silent dimension drift = misaligned overlays = rework.

**Standardize all three at 1440x673.** Before each capture's screenshot
step, insert:

```
mcp__playwright__browser_resize → width: 1440, height: 673
```

This explicitly normalizes `dashboard-egs-severed.png` from 2880x1800
down to the same 1440x673 the other two use. After-Effects template
needs a one-time check that overlays still align on the new severed
dimensions; if they don't, we accept that fixup as part of this pass
(better than three different sizes forever).

### Capture 1 — Beat 4 (severed banner)

Synthetic WS server, no Redis, no agent, no Ollama. Fastest end-to-end.

Follow `docs/runbooks/mcp-dom-verification.md` §"Beat 4 capture path"
verbatim, **adding the resize step** above between §3 (boot) and §4
(Playwright drive). Output: `docs_assets/dashboard-egs-severed.png`.

**New acceptance bullets (in addition to existing runbook §5):**
- Map panel shows the FEMA Mississippi aerial (light-toned suburban satellite
  imagery), not pure dark-grid background.
- The grid lines are still visible *over* the aerial (not under it) — proves
  3-layer Stack render order.
- Drone markers + white-pill ID labels (`drone1`, `drone2`, `drone3`) sit on
  top of both the aerial and the grid.

### Capture 2 — Beat 3 (findings-count chips)

System redis (6379) + EGS + drone agent + bridge + flutter static. Use
the **stand-in path** (`scripts/dev_fake_producers.py --emit=findings`)
for capture determinism — no Ollama warmup gamble.

Follow `docs/runbooks/mcp-dom-verification.md` §"Beat 3 EGS-findings-count
capture" verbatim, with the fake-producers path uncommented and the
1440x673 resize step inserted before screenshot. Output:
`docs_assets/dashboard-egs-state-counts.png`.

**Pre-capture coordination check:** this capture uses system Redis on
port 6379. Before booting EGS, run `redis-cli -p 6379 client list | wc -l`.
If clients > expected, ping #fieldagent-dev — Qasim or Hazim may be
mid-test against the same broker. Don't tear down their work.

**New acceptance bullets:**
- Map panel shows the FEMA Mississippi aerial.
- Polygon outline (zone) renders on top of the aerial.
- At least one drone marker is positioned over the aerial.

### Capture 3 — Beat 1/2 (finding rendered)

Full stack with MOCK Ollama (deterministic finding at ~1 s, no warmup
risk). Follow `docs/runbooks/mcp-dom-verification.md` §"Procedure" §1–§7
verbatim, with the 1440x673 resize step inserted between §4 (boot) and
§5 (Playwright drive). Output: `docs_assets/dashboard-finding-rendered.png`.

**New acceptance bullets (in addition to existing runbook §6):**
- Map panel shows the FEMA Mississippi aerial visible under the grid.
- Drone markers in upper-left (drone1), and across (drone2, drone3) — all
  with their white-pill ID labels readable against the aerial.
- The reported finding pin (victim type) sits on the aerial at a position
  consistent with `disaster_zone_v1.yaml`'s frame_mappings tick window.

## Verification (after each capture)

For each captured PNG, in order:

1. Run programmatic check (gates the eyeball pass):
   ```bash
   uv run python scripts/verify_demo_screenshot.py \
     --png docs_assets/dashboard-foo.png \
     --map-region <x,y,w,h-of-map-panel-in-1440x673> \
     --min-stddev 20
   # exit 0 = aerial pixels look photographic; exit 1 = grid-only fallback
   ```
   First run: calibrate `--map-region` against any one already-good PNG
   by sampling the map area (rough box: x≈760, y≈80, w≈660, h≈480 in
   1440x673 dashboard layout — verify with a quick crop preview).
2. Open it locally (`open docs_assets/dashboard-foo.png`).
3. Eyeball check against the new acceptance bullets above (drone label
   pills readable, off-extents chevrons absent unless expected, AnimatedOpacity
   reached final state — no half-faded image).
4. If anything fails, **do not `git add`** — investigate via:
   ```bash
   # In the Playwright MCP session before tear-down:
   mcp__playwright__browser_console_messages
   # look for asset 404s or NetworkImage errors
   ```
5. If pass, `git add docs_assets/<file>` (explicit — keeps you from
   committing only the ones that pass on a partial-pass run).

## Commit + cleanup

After all three captures pass acceptance:

```bash
git add docs_assets/dashboard-finding-rendered.png \
        docs_assets/dashboard-egs-state-counts.png \
        docs_assets/dashboard-egs-severed.png
git commit -m "docs(assets): re-capture demo screenshots with aerial overlay (PR #36 follow-up)"
git push origin main
```

Update `docs/STATUS.md` Ibrahim row with the re-capture timestamp and
which beats were refreshed.

## Risk + rollback

- **Risk:** a capture surfaces a UI bug we missed in PR #36 review (e.g.
  off-extents chevron firing when it shouldn't, label overlap on dense
  drone clusters, AnimatedOpacity stuck < 1.0).
- **Rollback:** if any capture reveals a bug, do not commit any of the
  three new PNGs. Existing pre-overlay PNGs stay on main; file an issue
  citing this plan; fix the bug under a new branch; re-run this plan.

## Don't do these

- Don't re-capture before GATE 3 (Day 10, May 12). If Kaleel's fine-tune
  lands, the LIVE-path finding tile content (`visual_description`,
  confidence) may shift, requiring another re-capture. The MOCK path
  isolates us from that, but the demo video uses MOCK anyway, so we'd
  redo the LIVE-path one twice.
  → Resolution: capture 1 + 2 (which don't depend on Gemma output) now.
  Defer capture 3 (the MOCK-path finding tile) only if you want to wait;
  otherwise capture all three since MOCK is fine-tune-independent.
- Don't change `dashboard-finding-rendered.png` resolution or aspect
  ratio — the storyboard's text-overlay positions are tuned to the
  current frame.
- Don't tear down redis if other team members are running against it.
  Confirm in Slack first.

## Estimated time

- Pre-flight: 10 min (build + smoke check)
- Verifier script (`scripts/verify_demo_screenshot.py`): 10 min one-time
- Capture 1 (Beat 4): 5 min
- Capture 2 (Beat 3): 10 min
- Capture 3 (Beat 1/2): 10 min
- Verification + commit: 5 min
- **Total: ~50 min** for a clean run; budget 75 min for first attempt
  (verifier calibration may need one extra crop iteration).

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 5 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**ENG REVIEW FINDINGS (2026-05-08):**

| # | Severity | Confidence | Resolution |
|---|----------|-----------|------------|
| 1A | P1 | 8/10 | Added `scripts/verify_demo_screenshot.py` step (programmatic aerial check) |
| 1B | P1 | 10/10 | Added explicit `mcp__playwright__browser_resize → 1440x673` before each capture |
| 2A | P3 | 9/10 | Fixed inline (HEAD reference no longer points at superseded commit) |
| 2B | P3 | 7/10 | Fixed inline (capture PID, poll-until-ready, kill by PID not name) |
| 2C | P3 | 8/10 | Fixed inline (explicit `git add` in verification step) |

**Operational note (informational, not a finding):** Capture 2 uses
system Redis on 6379 → added a teammate-coordination check before
booting EGS.

**Outside voice:** skipped — operational/asset plan, not architecture.
Cross-model challenge has low marginal value for a 50-min screenshot
runbook.

**VERDICT:** ENG CLEARED — ready to execute. All 5 findings resolved
in-plan. No unresolved decisions.
