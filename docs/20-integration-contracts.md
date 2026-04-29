# 20 — Integration Contracts

## Why This Doc Exists

Five people working in parallel only succeed if they build against fixed interfaces. This doc defines every contract between components. **Lock these on Day 1. Do not change after Day 2 except for true bugs.**

If a contract change is required mid-project, treat it as a serious event:
1. Person who needs the change posts in team channel
2. Team agrees in next standup
3. All affected components update simultaneously
4. PR includes contract change + all dependent updates

## What's Locked on Day 1

1. Function-calling schemas (per-drone, EGS, operator)
2. Per-drone state schema
3. EGS state schema
4. ROS 2 topic names and message types
5. WebSocket message schemas
6. File system layout

## Contract 1: Function-Calling Schemas

**Source of truth:** [`09-function-calling-schema.md`](09-function-calling-schema.md)

Located at: `shared/schemas/`

```
shared/schemas/
├── drone_function_calls.json     # report_finding, mark_explored, etc.
├── egs_function_calls.json       # assign_survey_points, replan_mission
└── operator_commands.json        # restrict_zone, recall_drone, etc.
```

Validation code in Python imports these schemas. Frontend imports them too.

## Contract 2: Per-Drone State Schema

**Topic:** `/drones/<id>/state`
**Frequency:** 2 Hz
**Owner:** Person 1 publishes (from PX4 telemetry); Person 2 augments with agent state.

```json
{
  "drone_id": "drone1",
  "timestamp": "2026-05-15T14:23:11.342Z",
  "position": {
    "lat": 34.1234,
    "lon": -118.5678,
    "alt": 25.0
  },
  "velocity": {
    "vx": 5.2,
    "vy": 0.0,
    "vz": 0.1
  },
  "battery_pct": 87,
  "heading_deg": 135,
  "current_task": "survey_zone_a",
  "current_waypoint_id": "sp_005",
  "assigned_survey_points_remaining": 12,
  "last_action": "report_finding",
  "last_action_timestamp": "2026-05-15T14:23:08.119Z",
  "validation_failures_total": 2,
  "findings_count": 4,
  "in_mesh_range_of": ["drone2", "egs"],
  "agent_status": "active"
}
```

`agent_status` ∈ {`active`, `standalone`, `returning`, `offline`, `error`}

## Contract 3: EGS State Schema

**Topic:** `/egs/state`
**Frequency:** 1 Hz
**Owner:** Person 3 publishes; Person 4 consumes.

```json
{
  "mission_id": "demo_run_5",
  "mission_status": "active",
  "timestamp": "2026-05-15T14:23:11.342Z",
  "zone_polygon": [
    [34.1230, -118.5680],
    [34.1240, -118.5680],
    [34.1240, -118.5670],
    [34.1230, -118.5670]
  ],
  "survey_points": [
    {
      "id": "sp_001",
      "lat": 34.1232,
      "lon": -118.5675,
      "assigned_to": "drone1",
      "status": "completed"
    }
  ],
  "drones_summary": {
    "drone1": {"status": "active", "battery": 87},
    "drone2": {"status": "active", "battery": 65},
    "drone3": {"status": "offline", "battery": null}
  },
  "findings_count_by_type": {
    "victim": 4,
    "fire": 2,
    "smoke": 3,
    "damaged_structure": 8,
    "blocked_route": 1
  },
  "recent_validation_events": [
    {
      "timestamp": "2026-05-15T14:22:55.000Z",
      "agent": "drone1",
      "task": "report_finding",
      "outcome": "corrected_after_retry",
      "issue": "duplicate_finding"
    }
  ],
  "active_zone_ids": ["zone_a", "zone_b"]
}
```

## Contract 4: Findings Schema

**Topic:** `/drones/<id>/findings` (drone publishes), `/egs/findings` (EGS aggregates)

```json
{
  "finding_id": "f_drone1_047",
  "source_drone_id": "drone1",
  "timestamp": "2026-05-15T14:23:11.342Z",
  "type": "victim",
  "severity": 4,
  "gps_lat": 34.1234,
  "gps_lon": -118.5678,
  "altitude": 0,
  "confidence": 0.78,
  "visual_description": "Person prone, partially covered by debris...",
  "image_path": "/tmp/findings/drone1_047.jpg",
  "validated": true,
  "validation_retries": 1,
  "operator_status": "pending"
}
```

`operator_status` ∈ {`pending`, `approved`, `dismissed`}

## Contract 5: Task Assignment Schema

**Topic:** `/drones/<id>/tasks`
**Owner:** Person 3 (EGS) publishes; Person 2 (drone agent) consumes.

```json
{
  "task_id": "task_237",
  "drone_id": "drone1",
  "issued_at": "2026-05-15T14:23:00.000Z",
  "task_type": "survey",
  "assigned_survey_points": [
    {"id": "sp_001", "lat": 34.1232, "lon": -118.5675, "priority": "normal"},
    {"id": "sp_002", "lat": 34.1234, "lon": -118.5673, "priority": "normal"}
  ],
  "priority_override": null,
  "valid_until": "2026-05-15T14:38:00.000Z"
}
```

Task types: `survey`, `investigate_finding`, `return_to_base`, `hold_position`.

## Contract 6: Peer Broadcast Schema

**Topic:** `/swarm/broadcasts/<sender_id>`

```json
{
  "broadcast_id": "drone1_b047",
  "sender_id": "drone1",
  "sender_position": {"lat": 34.1234, "lon": -118.5678, "alt": 25.0},
  "timestamp": "2026-05-15T14:23:11.342Z",
  "broadcast_type": "finding",
  "payload": {
    "type": "victim",
    "severity": 4,
    "gps_lat": 34.1234,
    "gps_lon": -118.5678,
    "confidence": 0.78,
    "visual_description": "..."
  }
}
```

Broadcast types: `finding`, `assist_request`, `task_complete`, `entering_standalone_mode`, `rejoining_swarm`.

The `mesh_simulator` filters these based on range; receiving drones subscribe to `/swarm/<their_id>/visible_to_<their_id>` after filtering.

## Contract 7: Operator Command Schemas

### Outbound (Flutter → EGS)

**WebSocket message type:** `operator_command`

```json
{
  "type": "operator_command",
  "command_id": "cmd_42",
  "language": "es",
  "raw_text": "concéntrate en la zona este"
}
```

### Translation response (EGS → Flutter)

```json
{
  "type": "command_translation",
  "command_id": "cmd_42",
  "structured": {
    "command": "restrict_zone",
    "args": {"zone_id": "east"}
  },
  "valid": true,
  "preview_text": "Will restrict mission to zone 'east'",
  "preview_text_in_operator_language": "Restringirá la misión a la zona 'este'"
}
```

### Dispatch confirmation (Flutter → EGS)

```json
{
  "type": "operator_command_dispatch",
  "command_id": "cmd_42"
}
```

## Contract 8: WebSocket Endpoint

**Endpoint:** `ws://localhost:9090`
**Owner:** Person 4 connects; Person 3 hosts via rosbridge_suite.

Messages from EGS to Flutter (every 1 second):

```json
{
  "type": "state_update",
  "timestamp": "2026-05-15T14:23:11.342Z",
  "egs_state": <see Contract 3>,
  "active_findings": [<see Contract 4 schema>],
  "active_drones": [<see Contract 2 schema>]
}
```

Messages from Flutter to EGS (event-driven):

- `operator_command` (see Contract 7)
- `operator_command_dispatch` (see Contract 7)
- `finding_approval` ({type, command_id, finding_id, action: "approve" | "dismiss"})

## Contract 9: ROS 2 Topic Naming

```
# Per-drone topics
/drones/<id>/state              std_msgs/String (JSON)
/drones/<id>/tasks              std_msgs/String (JSON)
/drones/<id>/findings           std_msgs/String (JSON)
/drones/<id>/camera             sensor_msgs/Image
/drones/<id>/cmd                std_msgs/String (JSON, flight commands)

# Swarm topics
/swarm/broadcasts/<id>          std_msgs/String (JSON)
/swarm/<id>/visible_to_<id>     std_msgs/String (JSON, filtered by mesh sim)
/swarm/operator_alerts          std_msgs/String (JSON)

# EGS topics
/egs/state                      std_msgs/String (JSON)
/egs/replan_events              std_msgs/String (JSON)

# Mesh simulator
/mesh/adjacency_matrix          std_msgs/String (JSON, debug only)
```

We use `std_msgs/String` with JSON payloads for everything except camera. This keeps schema versioning simple and lets all five team members work without compiling custom ROS 2 messages.

## Contract 10: File System Layout

```
fieldagent/
├── CLAUDE.md
├── README.md
├── docs/
├── simulation/
│   ├── worlds/disaster_zone_v1.sdf
│   ├── worlds/disaster_zone_v1_groundtruth.json
│   ├── px4_patches/
│   └── ros2_ws/
├── agents/
│   ├── drone_agent/
│   │   ├── __init__.py
│   │   ├── perception.py
│   │   ├── reasoning.py
│   │   ├── validation.py
│   │   ├── action.py
│   │   ├── memory.py
│   │   └── main.py
│   ├── egs_agent/
│   │   ├── __init__.py
│   │   ├── coordinator.py
│   │   ├── command_translator.py
│   │   ├── replanning.py
│   │   └── main.py
│   └── mesh_simulator/
│       └── main.py
├── shared/
│   ├── schemas/
│   ├── prompts/
│   └── utils/
├── frontend/
│   └── flutter_dashboard/
├── ml/
│   ├── data_prep/
│   ├── training/
│   ├── evaluation/
│   └── adapters/                 # output of fine-tuning
├── scripts/
│   ├── launch_swarm.sh
│   ├── launch_agents.sh
│   ├── run_full_demo.sh
│   ├── stop_demo.sh
│   └── run_resilience_scenario.sh
└── docs_assets/
```

## Contract 11: Logging

All logs go to `/tmp/fieldagent_logs/` with this structure:

```
/tmp/fieldagent_logs/
├── drone1_agent.log
├── drone2_agent.log
├── egs_agent.log
├── mesh_sim.log
├── px4_drone1.log
├── px4_drone2.log
├── gazebo.log
└── validation_events.jsonl       # every validation event from any agent
```

`validation_events.jsonl` is the source for the writeup's quantitative claims.

## Contract 12: Configuration

`shared/config.yaml`:

```yaml
mission:
  drone_count: 3
  zone_id: "disaster_zone_v1"
  
inference:
  drone_model: "gemma-4:e2b"
  egs_model: "gemma-4:e4b"
  drone_sampling_hz: 1.0
  ollama_drone_endpoint: "http://localhost:11434"
  ollama_egs_endpoint: "http://localhost:11435"
  
mesh:
  range_meters: 200
  egs_link_range_meters: 500
  heartbeat_timeout_seconds: 10
  
validation:
  max_retries: 3
  
logging:
  base_dir: "/tmp/fieldagent_logs"
  level: "INFO"
```

All processes read from this config. Changes here propagate everywhere. Don't hardcode values that should be config.

## Versioning

These contracts are **v1 (locked April 30, 2026)**.

If a true bug requires a change:
- Increment to v1.1 in this doc
- Update affected schemas
- Notify team in standup
- All affected code updates same day

## Cross-References

- Function calling details: [`09-function-calling-schema.md`](09-function-calling-schema.md)
- Validation patterns: [`10-validation-and-retry-loop.md`](10-validation-and-retry-loop.md)
- Mesh communication details: [`08-mesh-communication.md`](08-mesh-communication.md)
- Each component's design: [`05-per-drone-agent.md`](05-per-drone-agent.md), [`06-edge-ground-station.md`](06-edge-ground-station.md), [`07-operator-interface.md`](07-operator-interface.md)
