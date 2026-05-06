# 14 — Disaster Scene Design

## Goal

Design a software-simulated disaster scenario that:
1. Looks like a disaster zone from above (pre-recorded aerial/satellite imagery)
2. Contains visually unambiguous targets (victims, fires, damaged buildings, blocked routes)
3. Is small enough to be surveyed by 2-3 drones in 5-10 minutes of simulated time
4. Provides ground-truth labels for evaluation
5. Looks credible enough for the demo video without requiring 3D rendering

## Scenario-Driven Simulation Overview

Instead of a Gazebo world file, the disaster scene is defined by a **scenario YAML** at
`sim/scenarios/<name>.yaml`. The scenario enumerates:
- Drone home positions (lat/lon/alt)
- Scripted waypoint tracks per drone
- Time-keyed frame mappings (which JPEG to serve to which drone at which simulated tick)
- Scripted events (drone failure at T+45s, fire-spread polygon update at T+60s, etc.)

`sim/waypoint_runner.py` reads the scenario and publishes `drones.<id>.state` on Redis at 2 Hz.
`sim/frame_server.py` reads the same scenario and publishes `drones.<id>.camera` (raw JPEG bytes)
at 1 Hz, serving the pre-recorded frame keyed to the current tick.

Camera frames are **pre-recorded disaster imagery** — xBD post-disaster crops and public-domain
aerial/satellite photography — stored under `sim/fixtures/frames/`. No real-time rendering.

## Scenario File Format

```yaml
# sim/scenarios/disaster_zone_v1.yaml
scenario_id: disaster_zone_v1
origin:
  lat: 34.0000
  lon: -118.5000
area_m: 200          # 200m × 200m notional survey grid

drones:
  - drone_id: drone1
    home: {lat: 34.0001, lon: -118.5001, alt: 0}
    waypoints:
      - {id: sp_001, lat: 34.0002, lon: -118.5002, alt: 25}
      - {id: sp_002, lat: 34.0004, lon: -118.5002, alt: 25}
      # ... more waypoints ...
    speed_mps: 5

  - drone_id: drone2
    home: {lat: 34.0001, lon: -118.4990, alt: 0}
    waypoints:
      - {id: sp_010, lat: 34.0002, lon: -118.4991, alt: 25}
      # ...
    speed_mps: 5

frame_mappings:
  # drone_id → list of {tick_range: [start, end], frame_file: <filename in sim/fixtures/frames/>}
  drone1:
    - {tick_range: [0, 30],   frame_file: "xbd_hurricane_block_a_01.jpg"}
    - {tick_range: [31, 60],  frame_file: "xbd_hurricane_block_a_02.jpg"}
    - {tick_range: [61, 120], frame_file: "xbd_wildfire_structure_01.jpg"}
  drone2:
    - {tick_range: [0, 60],   frame_file: "xbd_hurricane_block_b_01.jpg"}
    - {tick_range: [61, 120], frame_file: "xbd_hurricane_victim_marker_01.jpg"}

scripted_events:
  - {t: 45,  type: drone_failure,      drone_id: drone1, detail: "battery_depleted"}
  - {t: 60,  type: zone_update,        detail: "fire_spread_polygon_expands"}
  - {t: 300, type: mission_complete}
```

The `t` field is simulated seconds from mission start. `sim/waypoint_runner.py` drives the clock;
time advances in wall-clock real-time at 1× speed by default (configurable).

## Scene Composition

**Notional area:** 200m × 200m (matches the ground-truth coordinate space used in the paper).

**Frame library targets — what's in `sim/fixtures/frames/`:**
- 6 frames of intact or lightly-damaged structures (xBD "no-damage" / "minor-damage" crops)
- 4 frames with clearly damaged or destroyed structures ("major-damage" / "destroyed" crops)
- 3-4 frames with visible victims or bright victim markers
- 2-3 frames with fire / smoke (xBD "fire" class, or public wildfire aerials)
- 2-3 frames with blocked roads or debris

**Visual strategy:** xBD post-disaster satellite/aerial imagery is more visually compelling than
synthetic 3D rendering, and is the same data the vision fine-tuning pipeline trains on. This
eliminates sim-to-real gap entirely for the vision task.

## Victim Representation

Because camera frames are real aerial imagery rather than a 3D scene, victim representation
follows the imagery reality:

**Option A: xBD frames that genuinely show people / rescue markers** (preferred for credibility).
- Source frames from xBD "building" damage tiles that incidentally capture personnel or markers.
- Demo narration: "Each highlighted region represents a casualty location derived from post-disaster
  aerial imagery."

**Option B: Composite frames** — overlay a bright red 1m × 1m square marker on a real base image
at a known pixel position. Simpler to guarantee detection; less realistic.

**We use Option A when source material is available; fall back to Option B for any victim
waypoints where Option A frames lack a clear target.** The fallback is documented in the
`frame_mappings` comment for that tick range.

## Fire and Smoke

Use xBD "fire" class tiles or public-domain post-wildfire aerial photographs.

**Fire spread (scripted event):** at T+60s the scenario emits a `zone_update` event. The EGS
receives this as a scripted "satellite update" and triggers replanning. The polygon expansion is
defined in the ground-truth file and referenced from the event field, not rendered visually.

## Scenario File Structure

```
sim/
├── waypoint_runner.py
├── frame_server.py
├── scenarios/
│   ├── disaster_zone_v1.yaml
│   └── disaster_zone_v1_groundtruth.json
└── fixtures/
    └── frames/
        ├── xbd_hurricane_block_a_01.jpg
        ├── xbd_hurricane_block_a_02.jpg
        ├── xbd_hurricane_block_b_01.jpg
        ├── xbd_wildfire_structure_01.jpg
        ├── xbd_hurricane_victim_marker_01.jpg
        └── ...
```

## Ground Truth File

```json
{
  "scenario_id": "disaster_zone_v1",
  "extents": {"lat_min": 33.9990, "lat_max": 34.0010, "lon_min": -118.5010, "lon_max": -118.4990},
  "victims": [
    {"id": "v01", "lat": 34.0002, "lon": -118.5002, "frame_file": "xbd_hurricane_victim_marker_01.jpg", "in_or_near": "block_a"},
    {"id": "v02", "lat": 34.0004, "lon": -118.4991, "frame_file": "xbd_hurricane_block_b_01.jpg",      "in_or_near": "block_b"}
  ],
  "fires": [
    {"id": "f01", "lat": 34.0006, "lon": -118.5003, "frame_file": "xbd_wildfire_structure_01.jpg", "intensity": "medium"}
  ],
  "damaged_structures": [
    {"id": "ds_a2", "lat": 34.0002, "lon": -118.5002, "frame_file": "xbd_hurricane_block_a_02.jpg", "damage_level": "major_damage"},
    {"id": "ds_a3", "lat": 34.0004, "lon": -118.5002, "frame_file": "xbd_hurricane_block_a_02.jpg", "damage_level": "destroyed"}
  ],
  "blocked_routes": [
    {"id": "br01", "lat": 34.0003, "lon": -118.5001, "frame_file": "xbd_hurricane_block_a_01.jpg", "blockage_type": "debris"}
  ],
  "scripted_events": [
    {"t": 45,  "type": "drone_failure",  "drone_id": "drone1"},
    {"t": 60,  "type": "fire_spread",    "new_polygon": [[34.0005, -118.5005], [34.0008, -118.5005], [34.0008, -118.5001], [34.0005, -118.5001]]}
  ]
}
```

**Used for:**
- Evaluation: did the drones actually find all the victims?
- Demo narration: precise counts ("the system identified 5 of 7 victims")
- Replan triggers: the scripted `fire_spread` event at T+60s matches the EGS zone-update event

## GPS / Coordinate Mapping

The scenario uses absolute lat/lon throughout. The origin is `34.0000, -118.5000` (LA area,
matches the wildfire narrative). Waypoints, findings, and ground-truth entries all use the same
coordinate space. `sim/waypoint_runner.py` computes drone position by linear interpolation between
waypoints at the configured speed; there is no flight dynamics simulation.

1 meter ≈ 0.0000089° latitude/longitude (rough conversion, sufficient for a 200m grid).

## Authoring Workflow (Hazim + Thayyil, paired)

A new scenario lands in three steps; each step has a stable artifact, so the
work parallelises across the pair.

**Step 1 — Skeleton (mostly Hazim).** Set up the Pydantic-validated YAML
under `sim/scenarios/<name>.yaml` with drone home positions, waypoint
tracks, and `speed_mps`. Smoke-load it with `sim.scenario.load_scenario`
(the test harness in `sim/tests/test_scenario_fixtures.py` is the canary).

**Step 2 — Frame mappings + ground truth (mostly Thayyil).** Curate xBD
crops or public-domain aerials into `sim/fixtures/frames/` (filenames
preserved if a swap is replacing existing placeholders — see
[`sim/tests/test_frames_directory.py`](../sim/tests/test_frames_directory.py)
for the JPEG-sanity guard). Wire `frame_mappings.<drone_id>` to the
scripted waypoint timeline. Author `<name>_groundtruth.json` with victims,
fires, damaged structures, and blocked routes consistent with the imagery.

**Note (2026-05-06):** The fixture `sim/fixtures/frames/placeholder_victim_01.jpg` is no longer a placeholder — it's a CC0 FEMA Hurricane Katrina aerial of a destroyed Mississippi school; provenance in [`sim/fixtures/frames/LICENSES.md`](../sim/fixtures/frames/LICENSES.md). The filename is preserved per the stability contract, so the three scenario YAMLs (`disaster_zone_v1`, `resilience_v1`, `single_drone_smoke`) and their ground-truth manifests still reference it. Live Gemma `report_finding` on this image is verified in [`docs/sim-live-run-notes.md`](sim-live-run-notes.md) Gap #2.

**Step 3 — Scripted events (paired).** Add `scripted_events` for the
narrative beats (drone failures, fire spread, EGS link drops, mission
complete). Cross-check timing against the geometry: e.g. the
`resilience_v1` scenario's t=30 `drone_failure` lands a few seconds
*after* the geometric mesh dropout at t≈18s, which the writeup can either
narrate or stay silent on.

Reference scenarios already shipped:

- [`disaster_zone_v1.yaml`](../sim/scenarios/disaster_zone_v1.yaml) —
  3-drone everyday demo on a 200×200m grid.
- [`resilience_v1.yaml`](../sim/scenarios/resilience_v1.yaml) — 3-drone
  fan-out tuned so mesh dropout, EGS link loss, and scripted drone
  failure all fire inside a 240s run; substrate for Phase D / E
  rehearsals. See [`docs/sim-live-run-notes.md`](sim-live-run-notes.md)
  for the wall-clock validation.
- [`single_drone_smoke.yaml`](../sim/scenarios/single_drone_smoke.yaml) —
  fast CI / smoke fixture.

When iterating on a live scenario:

- Start with `scripts/launch_swarm.sh <scenario> --duration=N` against a
  real Redis broker — the WaypointRunner and FrameServer self-terminate
  cleanly at the deadline.
- Use `sim/manual_pilot.py --drone-id droneN` in a side pane to type
  findings/broadcasts into the live channels by hand.
- Fold any new constraints surfaced during iteration back into the
  scenario YAML or the `_groundtruth.json` manifest before the next run.

## Validation: Does Gemma 4 See It?

Before integrating with the full agent loop, Kaleel manually:
1. Takes 20 frames from `sim/fixtures/frames/` (the same files the frame server will serve)
2. Sends each to Gemma 4 base model with the system prompt from `shared/prompts/`
3. Verifies the model identifies the right targets with reasonable confidence

If Gemma 4 base model fails (e.g., misclassifies all rubble as intact structures), the frame is
too ambiguous. Replace it with a clearer xBD tile or add a composite marker overlay and document
the substitution in the frame mapping comment.

## What Could Go Wrong

| Failure | Mitigation |
|---|---|
| xBD frames too low-resolution | Source higher-resolution tiles from the same dataset; supplement with public aerial photography |
| Gemma 4 misclassifies all frames similarly | Diversify frame library; check prompt framing in `shared/prompts/` |
| `frame_server.py` clock drifts from `waypoint_runner.py` | Both processes share the simulated-tick counter via Redis key `sim.tick`; frame server reads it on each publish |
| Scripted events fire at wrong simulated time | Unit-test event scheduling in `waypoint_runner.py` before integration |
| Frame files missing from `sim/fixtures/frames/` | Fail-fast in `frame_server.py` startup: validate all referenced frame files exist before subscribing |

## Iterating

Scenarios are iterative — adjust based on:

- What Gemma 4 reliably identifies (frame selection, mapping density).
- How long missions take (waypoint density, `speed_mps`).
- Whether the demo video looks good (camera angles, frame diversity).

Once the scenario is committed to the demo storyboard, freeze it. After
that point, only fix bugs in scripted-event timing or ground-truth
consistency — don't reshape the geometry mid-recording. The submission
checklist ([`docs/23-submission-checklist.md`](23-submission-checklist.md))
is the canonical source for the freeze date.

## Cross-References

- Redis channel contracts (camera, state): [`20-integration-contracts.md`](20-integration-contracts.md) Contract 9
- How agents consume frames: [`05-per-drone-agent.md`](05-per-drone-agent.md)
- Demo storyboard: [`21-demo-storyboard.md`](21-demo-storyboard.md)
