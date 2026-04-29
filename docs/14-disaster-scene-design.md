# 14 — Disaster Scene Design

## Goal

Design a Gazebo world that:
1. Looks like a disaster zone from above
2. Contains visually unambiguous targets (victims, fires, damaged buildings, blocked routes)
3. Is small enough to be surveyed by 2-3 drones in 5-10 minutes
4. Provides ground-truth labels for evaluation
5. Looks credible enough for the demo video without requiring AAA-game-quality assets

## Scene Specifications

**Size:** 200m × 200m square area.

**Layout:** A grid of 16 building plots (4×4) with the following composition:
- 6 intact buildings
- 4 minor-damage buildings (broken windows, scorched walls)
- 4 major-damage buildings (partial collapse, missing roof)
- 2 destroyed buildings (rubble piles)

**Other features:**
- A grid of roads between buildings (some clear, some blocked)
- 5-7 victim markers placed in/around damaged buildings
- 2-3 active fires (Gazebo plume plugin)
- 3-4 blocked routes (debris meshes, fallen trees)
- Trees, vehicles for visual realism

## Asset Sources

We don't build assets from scratch. We use:

1. **Gazebo built-in models** for basic shapes (buildings, vehicles)
2. **Gazebo Fuel** (`https://app.gazebosim.org/fuel`) — public model repository with free-to-use assets:
   - Search "damaged building," "rubble," "destroyed house"
   - Search "construction debris," "wreckage"
3. **Custom-modified models** when needed:
   - Take an intact building mesh, manually distort/rotate parts in Blender for a "damaged" version
   - Add scorched textures via a single OBJ texture swap

## Victim Markers

**Critical decision:** how do we represent victims?

**Option A: Realistic mannequins (NOT RECOMMENDED).**
- Photorealistic but Gemma 4 may not detect them reliably
- Sim-to-real gap: video-game humans don't look like real disaster victims

**Option B: AprilTag markers (RECOMMENDED).**
- Bright, unambiguous, machine-readable
- Each tag encodes a unique ID we use for ground-truth evaluation
- Frame as "real deployment would use thermal imaging or ML detection; for the demo we use AprilTags as deterministic targets"

**Option C: Brightly-colored geometric shapes.**
- A bright red 1m × 1m square placed on the ground
- Even simpler than AprilTags
- Less realistic but reliably detectable

**We use Option B with a fallback to Option C if AprilTag plugins are flaky.**

The demo narrator can say: "Each marker represents a person needing rescue. The drone identifies them and the operator dispatches help." Judges will accept this framing.

## Fire and Smoke

Gazebo's built-in plume plugin produces visible smoke/fire effects from above.

```xml
<plugin name="gz::sim::systems::Plume" filename="gz-sim-plume-system">
  <position>50 30 0</position>
  <intensity>medium</intensity>
</plugin>
```

For the demo, 2-3 fires of varying intensity. The drone classifies them by severity.

**Fire spread (mocked):** at scripted times during the demo, additional fire plumes spawn. The EGS detects this via a separate "satellite update" event and triggers replanning.

## World File Structure

```
simulation/worlds/
├── disaster_zone_v1.sdf          # main world file
├── models/
│   ├── damaged_building_a/
│   ├── damaged_building_b/
│   ├── rubble_pile/
│   ├── debris_road_block/
│   └── victim_marker_apriltag/
├── plugins/                       # custom plugins if needed
└── README.md                      # how to load this world
```

## SDF World Sketch

(Full file is too long for this doc — this is the structure.)

```xml
<?xml version="1.0" ?>
<sdf version="1.10">
  <world name="disaster_zone">
    <physics name="default" default="true" type="ode">
      <max_step_size>0.001</max_step_size>
      <real_time_factor>1.0</real_time_factor>
    </physics>
    
    <plugin filename="gz-sim-physics-system" .../>
    <plugin filename="gz-sim-sensors-system" .../>
    <plugin filename="gz-sim-scene-broadcaster-system" .../>
    
    <!-- Lighting: post-disaster overcast -->
    <scene>
      <ambient>0.5 0.5 0.5 1</ambient>
      <sky>
        <clouds><speed>0</speed></clouds>
      </sky>
    </scene>
    
    <!-- Ground -->
    <include><uri>model://ground_plane</uri></include>
    
    <!-- Building grid -->
    <include name="bldg_a1">
      <uri>model://intact_building_v1</uri>
      <pose>10 10 0 0 0 0</pose>
    </include>
    <include name="bldg_a2">
      <uri>model://damaged_building_a</uri>
      <pose>30 10 0 0 0 0</pose>
    </include>
    <!-- ... 14 more buildings ... -->
    
    <!-- Victims -->
    <include name="victim_1">
      <uri>model://apriltag_marker</uri>
      <pose>32 12 0.05 0 0 0</pose>
    </include>
    <!-- ... more victims ... -->
    
    <!-- Fires -->
    <plugin filename="gz-sim-plume-system">
      <position>50 30 0</position>
      <intensity>0.7</intensity>
    </plugin>
    
    <!-- Blocked routes -->
    <include name="debris_1">
      <uri>model://debris_road_block</uri>
      <pose>20 25 0 0 0 0</pose>
    </include>
    
    <!-- Drone spawn points: handled by PX4 SITL launch -->
  </world>
</sdf>
```

## Ground Truth File

Alongside the world file, we maintain a JSON ground-truth manifest:

```json
{
  "world_name": "disaster_zone_v1",
  "extents": {"x_min": 0, "x_max": 200, "y_min": 0, "y_max": 200},
  "victims": [
    {"id": "v01", "lat": 34.1232, "lon": -118.5670, "x": 32, "y": 12, "in_or_near": "bldg_a2"},
    {"id": "v02", "lat": 34.1234, "lon": -118.5675, "x": 70, "y": 35, "in_or_near": "bldg_b3"}
  ],
  "fires": [
    {"id": "f01", "lat": 34.1240, "lon": -118.5680, "x": 50, "y": 30, "intensity": "medium"}
  ],
  "damaged_structures": [
    {"id": "ds_a2", "lat": ..., "lon": ..., "x": 30, "y": 10, "damage_level": "minor_damage"},
    {"id": "ds_a3", "lat": ..., "lon": ..., "x": 50, "y": 10, "damage_level": "destroyed"}
  ],
  "blocked_routes": [
    {"id": "br01", "lat": ..., "lon": ..., "x": 20, "y": 25, "blockage_type": "debris"}
  ]
}
```

**Used for:**
- Evaluation: did the drones actually find all the victims?
- Demo narration: precise counts ("the system identified 5 of 7 victims")
- Replan triggers: "a new fire spawns at (75, 75)" is a scripted event

## GPS Mapping

PX4 simulates GPS in absolute lat/lon. We pick a fictional location for the demo:

- Origin: 34.0000, -118.5000 (a coordinate in the LA area, fits the wildfire narrative)
- 1 meter ≈ 0.0000089 degrees latitude / longitude (rough conversion)

This is configured in PX4's `PX4_HOME_LAT` / `PX4_HOME_LON` environment variables.

## Building the Scene (Person 5's Week 1 Work)

Day 1-3:
- Browse Gazebo Fuel for assets
- Download intact + damaged building models
- Test loading them in a basic Gazebo world

Day 4-5:
- Place buildings in 4×4 grid
- Add roads (just textured ground polygons)
- Add victims (AprilTags or color markers)

Day 6-7:
- Add fires and smoke
- Add debris / blocked routes
- Validate from drone altitude (camera view from 25m up)
- Generate ground-truth manifest JSON

Day 8 onwards:
- Iterate based on what the drone agent actually identifies
- Maybe simplify scenes if Gemma 4 struggles
- Maybe add visual cues if confidence is too low

## Validation: Does Gemma 4 See It?

Before integrating with the agent loop, Person 5 manually:
1. Takes 20 screenshots from drone-eye view at 25m altitude
2. Sends each to Gemma 4 base model with the system prompt
3. Verifies the model identifies the right targets with reasonable confidence

If Gemma 4 base model fails (e.g., misclassifies all rubble piles as intact buildings), the scene is too ambiguous. Add visual cues (e.g., bright red "X" on destroyed buildings) and document that the scene uses **explicit visual markers as a sim-to-real abstraction**.

## What Could Go Wrong

| Failure | Mitigation |
|---|---|
| Damaged building meshes look like normal buildings | Add visual markers, exaggerate damage textures |
| Fire plumes too subtle from above | Increase intensity, add visible flames at base |
| AprilTags don't render correctly | Fall back to colored squares |
| Scene too dense, drones collide | Increase building spacing |
| Scene too sparse, drones run out of survey points | Add more buildings, victims |
| Gazebo crashes loading complex scene | Reduce mesh complexity, use simpler shapes |

## Iterating

The scene is iterative. Don't lock it in Week 1. Adjust based on:
- What Gemma 4 reliably identifies
- How long missions take
- Whether the demo video looks good

Lock the final scene by Day 16 (May 14). After that, only fix bugs.

## Cross-References

- Multi-drone spawning in this world: [`15-multi-drone-spawning.md`](15-multi-drone-spawning.md)
- How agents see this scene: [`05-per-drone-agent.md`](05-per-drone-agent.md)
- Demo storyboard: [`21-demo-storyboard.md`](21-demo-storyboard.md)
