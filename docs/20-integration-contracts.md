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
4. Redis pub/sub channel names
5. WebSocket message schemas
6. File system layout

## Transport (locked April 30, 2026)

The system uses **Redis pub/sub** as the inter-process messaging bus, not ROS 2. A single local `redis-server` (`brew install redis` / `apt install redis-server`) hosts every channel. All five team members run the same `redis-server` on `localhost:6379` and connect via `redis-py`. There is no Gazebo, no PX4 SITL, and no ROS 2 install. See [`13-runtime-setup.md`](13-runtime-setup.md).

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

**Channel:** `drones.<id>.state`
**Frequency:** 2 Hz
**Owner:** Hazim's `sim/waypoint_runner.py` publishes the kinematic fields (position, velocity, heading, battery decay) from the scripted scenario; Kaleel's drone agent overwrites the agent-state fields (`current_task`, `last_action`, `validation_failures_total`, `findings_count`, `agent_status`) on the same channel as a merged record.

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
  "current_task": "survey",
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

**Channel:** `egs.state`
**Frequency:** 1 Hz
**Owner:** Qasim publishes; Ibrahim consumes (via the FastAPI WebSocket bridge mirroring this channel out to Flutter).

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
      "issue": "DUPLICATE_FINDING"
    }
  ],
  "active_zone_ids": ["zone_a", "zone_b"],
  "approved_findings": {
    "f_drone1_042": "approved",
    "f_drone2_007": "dismissed"
  },
  "base_image_path": "sim/fixtures/base_images/disaster_zone_v1_base.jpg",
  "base_image_extents": {
    "lat_min": 33.9990,
    "lat_max": 34.0010,
    "lon_min": -118.5010,
    "lon_max": -118.4990
  }
}
```

**Optional fields (added 2026-05-08, Task 8 of fixtures-swap plan):**

`base_image_path` and `base_image_extents` are optional. They flow `disaster_zone_v1.yaml` → `agents/egs_agent/scenario_state.build_initial_egs_state` → `egs.state` → bridge → Flutter `MissionState`, where the dashboard's `map_panel.dart` renders the aerial as a 0.80-opacity overlay above its procedural-grid fallback (locked design decisions D1/D2/D3 in the plan). Either both fields are present, or both are omitted (both-or-neither validator on the Pydantic side at `sim/scenario.py:Scenario._base_image_path_and_extents_paired`). Scenarios without an aerial (currently `single_drone_smoke`, `resilience_v1`) omit both and the dashboard falls back to the grid.

**Wire-path semantics:** `base_image_path` is repo-rooted (e.g. `sim/fixtures/base_images/...`). The dashboard maps this to its Flutter asset bundle namespace (`assets/base_images/...`) at the rendering boundary via `frontend/flutter_dashboard/lib/widgets/map_panel.dart:_resolveAssetPath`. The two on-disk copies are kept byte-identical by `scripts/sync_flutter_base_images.py` and locked down in CI by `scripts/tests/test_flutter_asset_sync.py`. Don't change the wire format to the Flutter-relative path — the repo-rooted form is what's self-documenting in scenario YAMLs and debug logs.

**Approval registry (added 2026-05-11, Qasim's PR #45 + the bridge stamp in this PR):**

`approved_findings` is an **optional** map of `finding_id → "approved" | "dismissed"`.
It is populated by the EGS coordinator's `process_actions` finding_approval branch
(`agents/egs_agent/coordinator.py:248-281`) as the operator clicks APPROVE or DISMISS
on findings in the dashboard. Initial state seeds the field to `{}`
(`agents/egs_agent/scenario_state.py:77`), so consumers should treat absent, `None`,
and empty-dict identically — the schema field is not in `required`.

This map is the source of truth for the operator's approval decisions. The WS
bridge aggregator (`frontend/ws_bridge/aggregator.py` `snapshot()`) joins it against
`active_findings[]` at snapshot time and stamps `operator_status: "approved"`
(or `"dismissed"`) onto matching finding objects in the outbound `state_update`
envelope — this is what drives the dashboard's grey → green check transition.
Findings not present in the map pass through with whatever `operator_status` the
drone originally published (typically `"pending"`).

Dedup is keyed on `command_id` inside the EGS coordinator (`_seen_approval_command_ids`
set in `EGSCoordinator.__init__`); replayed actions are logged as
`egs.finding_approval duplicate dropped command_id=...` and skipped. Malformed
payloads (missing `finding_id`, action outside `{approve, dismiss}`) are logged at
WARNING and dropped without altering the map.

Approval does NOT trigger replan in v1 — approval is informational. If a future beat
needs "approved victim → auto-dispatch investigate_finding," that lands in a separate
plan. Known long-run footguns: the map itself is unbounded today (no cap or TTL),
and the coordinator's `_seen_approval_command_ids` set is also unbounded — both
acceptable for demo length, both worth addressing post-submission.

## Contract 4: Findings Schema

**Channel:** `drones.<id>.findings` (drone publishes). EGS aggregates findings into the `egs.state` envelope's `findings_count_by_type` and surfaces individual findings to Flutter via the `state_update` WebSocket message; there is no separate `egs.findings` channel in v1.

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

`operator_status` ∈ {`pending`, `approved`, `dismissed`}. As of 2026-05-11, the
drone-published value (typically `"pending"`) is the initial state, but the WS
bridge aggregator overwrites this field on outbound `state_update` frames based on
the EGS-side `egs_state.approved_findings` map in Contract 3 — the operator's
decisions take precedence downstream. The bridge stamps only the enum form;
Contract 4's `additionalProperties: false` means there is no companion `approved: bool`
field on the finding object. Dashboard consumers should read `operator_status`.

## Contract 5: Task Assignment Schema

**Channel:** `drones.<id>.tasks`
**Owner:** Qasim (EGS) publishes; Kaleel (drone agent) consumes.

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

**Channel:** `swarm.broadcasts.<sender_id>`

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

The `mesh_simulator` process subscribes to `swarm.broadcasts.*` (Redis pattern subscribe), filters each message by Euclidean distance against the live `drones.*.state` snapshot, and republishes accepted messages on `swarm.<receiver_id>.visible_to.<receiver_id>`. Receiving drones subscribe to their own visible-to channel.

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
**Owner:** Ibrahim connects; Qasim hosts via a small FastAPI WebSocket app at `frontend/ws_bridge/`. The bridge subscribes to a fixed list of Redis channels (`egs.state`, `drones.*.state`, `drones.*.findings.delivered`) and forwards a single envelope per second to all connected dashboard clients. Operator commands flow back through the same WebSocket and are republished by the bridge onto the corresponding Redis channels.

**Note (2026-05-10, Path A-full):** the bridge migrated its findings subscription from `drones.*.findings` to `drones.*.findings.delivered` so it sees only the EGS-gated stream. The mesh simulator is now the gateway: drones still publish to `drones.<id>.findings`, mesh sim psubscribes, applies the `egs_link_range` haversine gate + scripted-override set, and republishes verbatim to `drones.<id>.findings.delivered`. Drones also subscribe to `mesh.link_status` events to flip their own `BufferedPublisher` standalone bit (buffers findings to JSONL during outage, replays in FIFO on restore). EGS dedupes by `finding_id` so replays don't double-count `findings_count_by_type`. EGS startup gates on a single `mesh.adjacency_matrix` heartbeat — without the mesh sim running, the EGS exits non-zero rather than silently never seeing a finding. See `docs/plans/2026-05-10-beat5-path-a-full.md` for the architecture diagram and full component breakdown.

**Endpoint discovery (Flutter web).** The dashboard's `_wsBridgeUrl()` in `frontend/flutter_dashboard/lib/main.dart` reads `Uri.base.queryParameters['ws']` (kIsWeb-guarded) and falls back to `Channels.wsEndpoint` (`ws://localhost:9090/`). This `?ws=ws://host:port/` override is the canonical way to point the dashboard at a per-test bridge port; e2e tests under `frontend/ws_bridge/tests/` use it via the `flutter_static_server` fixture in `conftest.py`. It is **not** a deployment knob — the production demo always uses the default endpoint.

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

## Contract 9: Redis Channel Naming

```
# Per-drone channels (payload: JSON, validated against the named schema)
drones.<id>.state                drone_state
drones.<id>.tasks                task_assignment
drones.<id>.findings             finding             (drone publishes; mesh_simulator psubscribes)
drones.<id>.findings.delivered   finding             (mesh_simulator republishes after EGS-link gate; EGS + bridge subscribe here)
drones.<id>.camera               (raw JPEG bytes; not JSON-validated)
drones.<id>.cmd                  (sim-internal flight commands; not part of the agent contract)

# Swarm channels
swarm.broadcasts.<id>            peer_broadcast
swarm.<id>.visible_to.<id>       peer_broadcast       (republished by mesh_simulator after range filtering)
swarm.operator_alerts            (free-form, debug-only)

# EGS channels
egs.state                        egs_state
egs.replan_events                (free-form, debug-only)
egs.operator_commands            operator_commands_envelope
egs.command_translations         command_translations_envelope
egs.operator_actions             operator_actions

# Mesh simulator
mesh.adjacency_matrix            (debug only — also serves as the EGS startup healthcheck pulse)
mesh.link_status                 mesh_link_status     (per-drone EGS-link transitions; geometric or scripted; 1 Hz heartbeat)

# Sim
sim.scripted_events              scripted_event       (egs_link_drop / egs_link_restore / drone_failure / etc.)
```

Every contract channel carries a JSON string. Subscribers `redis.pubsub().subscribe(channel)` and parse the message body. The `drones.<id>.camera` channel is the one exception — it carries raw JPEG bytes (the pre-recorded frame for the current simulated tick from `sim/frame_server.py`). Receivers handle camera and JSON channels through different code paths.

**Why dot-notation:** `redis-cli PSUBSCRIBE 'drones.*.state'` works as a glob, which is how the FastAPI WebSocket bridge consumes "all drones" without enumerating IDs. The dot is the conventional Redis channel separator in pub/sub idioms (NATS-style).

## Contract 10: File System Layout

```
gemma-guardian/
├── CLAUDE.md
├── README.md
├── docs/
├── sim/
│   ├── waypoint_runner.py        # publishes drones.<id>.state on a scripted track
│   ├── frame_server.py           # publishes drones.<id>.camera (JPEG) per tick
│   ├── scenarios/
│   │   ├── disaster_zone_v1.yaml # waypoints + frame mappings + scripted failures
│   │   └── disaster_zone_v1_groundtruth.json
│   └── fixtures/
│       └── frames/               # pre-recorded JPEG frames (xBD crops, public aerials)
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
│   │   ├── validation.py        # contracts plan stub (cross-drone dedup); Qasim fleshes out the rest
│   │   ├── coordinator.py
│   │   ├── command_translator.py
│   │   ├── replanning.py
│   │   └── main.py
│   └── mesh_simulator/
│       └── main.py
├── shared/
│   ├── VERSION
│   ├── config.yaml
│   ├── schemas/                 # JSON Schemas (Draft 2020-12)
│   ├── contracts/               # Python loader, Pydantic mirrors, RuleID, generated topic constants
│   ├── prompts/
│   └── tests/
├── frontend/
│   ├── flutter_dashboard/
│   │   └── lib/generated/       # codegen targets (topics.dart, contract_version.dart)
│   └── ws_bridge/
│       └── main.py              # FastAPI app; ws://localhost:9090; mirrors Redis channels
├── ml/
│   ├── data_prep/
│   ├── training/
│   ├── evaluation/
│   └── adapters/                # output of fine-tuning
├── scripts/
│   ├── gen_topic_constants.py
│   ├── launch_swarm.sh          # starts redis-server, sim, agents, ws_bridge, dashboard
│   ├── run_full_demo.sh
│   ├── stop_demo.sh
│   └── run_resilience_scenario.sh
└── docs_assets/
```

## Contract 11: Logging

All logs go to `/tmp/gemma_guardian_logs/` with this structure:

```
/tmp/gemma_guardian_logs/
├── drone1_agent.log
├── drone2_agent.log
├── egs_agent.log
├── mesh_sim.log
├── waypoint_runner.log           # sim/waypoint_runner.py
├── frame_server.log              # sim/frame_server.py
├── ws_bridge.log                 # frontend/ws_bridge/main.py
└── validation_events.jsonl       # every validation event from any agent
```

`validation_events.jsonl` is the source for the writeup's quantitative claims.

**Producer:** `agents/drone_agent` (via `shared.contracts.logging.ValidationEventLogger`).
**Consumer:** `agents/egs_agent` aggregates the last N entries into `egs.state.recent_validation_events`.
**Path:** `/tmp/gemma_guardian_logs/validation_events.jsonl` — note the `gemma_guardian_logs` (not `fieldagent_logs`) directory; this aligns with the `logging.base_dir` field in `shared/config.yaml`.

## Contract 12: Configuration

`shared/config.yaml`:

```yaml
contract_version: "1.0.0"           # must match shared/VERSION

mission:
  drone_count: 3
  scenario_id: "disaster_zone_v1"   # directory under sim/scenarios/

transport:
  redis_url: "redis://localhost:6379/0"
  channel_prefix: ""                # if non-empty, prefixed to every channel (test isolation)

inference:
  drone_model: "gemma4:e2b"     # ollama.com/library/gemma4 — pinned 2026-05-06 after live verification on Apple Silicon
  egs_model: "gemma4:e4b"       # ollama.com/library/gemma4 — pinned 2026-05-06
  drone_sampling_hz: 1.0
  ollama_drone_endpoint: "http://localhost:11434"
  ollama_egs_endpoint: "http://localhost:11434"
  # NOTE (2026-05-09, PR #38): Consolidated to a single local Ollama daemon on :11434
  # serving both the drone (E2B) and EGS (E4B) models. Ollama multiplexes models on one
  # daemon, so a second instance on :11435 is unnecessary in dev / hackathon-demo deployments.
  function_call_path:
    egs: "native_tools"             # uses Ollama tools[] when available
    drone: "structured_output"      # uses Ollama format=<schema> as the safer default
    fallback: "structured_output"

mesh:
  range_meters: 200
  egs_link_range_meters: 500
  heartbeat_timeout_seconds: 10

validation:
  max_retries: 3

logging:
  base_dir: "/tmp/gemma_guardian_logs"
  level: "INFO"
```

All processes read from this config. Changes here propagate everywhere. Don't hardcode values that should be config. Mismatched `contract_version` aborts startup with a clear error.

## Authoritative artifacts

These are the machine-checked sources of truth for the contracts above. If any of these disagrees with this doc, **the artifact wins**; update this doc.

| Concern | Path |
|---|---|
| Wire shapes | [`shared/schemas/*.json`](../shared/schemas/) |
| Shared `$defs` | [`shared/schemas/_common.json`](../shared/schemas/_common.json) |
| Python validators | [`shared/contracts/schemas.py`](../shared/contracts/schemas.py) |
| Pydantic mirrors | [`shared/contracts/models.py`](../shared/contracts/models.py) |
| Rule IDs and corrective templates | [`shared/contracts/rules.py`](../shared/contracts/rules.py) |
| Ollama → canonical adapter | [`shared/contracts/adapters.py`](../shared/contracts/adapters.py) |
| Channel registry (Python) | [`shared/contracts/topics.py`](../shared/contracts/topics.py) (generated) |
| Channel registry (Dart) | [`frontend/flutter_dashboard/lib/generated/topics.dart`](../frontend/flutter_dashboard/lib/generated/topics.dart) (generated) |
| Channel registry source | [`shared/contracts/topics.yaml`](../shared/contracts/topics.yaml) |
| Mission config | [`shared/config.yaml`](../shared/config.yaml) |
| Config loader | [`shared/contracts/config.py`](../shared/contracts/config.py) |
| Contract version constant | [`shared/VERSION`](../shared/VERSION) |
| Validation event log shape | [`shared/schemas/validation_event.json`](../shared/schemas/validation_event.json) |
| Validation event logger | [`shared/contracts/logging.py`](../shared/contracts/logging.py) |

CI fails when `shared/VERSION`, `shared/config.yaml.contract_version`, and `frontend/.../contract_version.dart` disagree, and when generated `topics.py` / `topics.dart` are stale relative to `topics.yaml`. See [`shared/tests/test_version_consistency.py`](../shared/tests/test_version_consistency.py) and [`shared/tests/test_topics_codegen_fresh.py`](../shared/tests/test_topics_codegen_fresh.py).

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
