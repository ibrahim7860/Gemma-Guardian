# Sim Reproduction Guide — cold-start to full demo

Phase G v1 draft (Hazim, co-write target with Thayyil). The goal of this doc
is a single linear path that takes an outside tester from a fresh box to a
running multi-drone demo with no prior project context. If you are already
set up for development, you want [`13-runtime-setup.md`](13-runtime-setup.md)
and [`15-multi-drone-spawning.md`](15-multi-drone-spawning.md) instead.

The exit criterion for Phase G is an outside tester running this guide cold
and reaching the "Full resilience scenario" demo without us at the keyboard.
File issues against any step that fails for you.

## 1. OS prerequisites

The stack is cross-platform: Linux, macOS, or Windows 11 + WSL2. There is no
Gazebo, no PX4, no ROS 2 — the "drones" are Python processes coordinating via
Redis. See [`CLAUDE.md`](../CLAUDE.md) for the full cross-platform stance.

| Component | Version | Notes |
|---|---|---|
| Python | 3.11+ | 3.13 / 3.14 also work (uv picks the latest available on your box; Hazim's WSL2 box is 3.13.5 via pyenv, Ibrahim's M1 cold-run was 3.14.4) |
| Redis | 7+ | `brew install redis` / `apt install redis-server` |
| Ollama | latest | https://ollama.com/download |
| tmux | any | required by `scripts/launch_swarm.sh` (or use `--dry-run`) |
| uv | latest | https://astral.sh/uv |

Install per-platform per [`13-runtime-setup.md`](13-runtime-setup.md). On
WSL2 distros without systemd, start Redis with `sudo service redis-server
start` rather than `systemctl` (covered in §13).

### Gemma 4 model tags (pinned)

Per Contract 12 in [`20-integration-contracts.md`](20-integration-contracts.md):

```bash
ollama pull gemma4:e2b      # drone agent — pinned 2026-05-06
ollama pull gemma4:e4b      # EGS coordinator — pinned 2026-05-06
```

Do not substitute other tags. The contract is the source of truth for these;
if `ollama pull` fails, confirm the tag at https://ollama.com/library/gemma4
and update the contract before changing any code.

## 2. Clone and install Python dependencies

```bash
git clone <repo-url> gemma-guardian
cd gemma-guardian
```

The repo uses [`uv`](https://docs.astral.sh/uv/) with a single root
`pyproject.toml` and a committed `uv.lock`. There are no per-role
`requirements.txt` files; do not create any. CI runs `uv sync --frozen`.

For a cold-start full demo, the one-command path is:

```bash
bash scripts/setup.sh                 # uv sync --all-extras + prereq check
bash scripts/setup.sh --pull-models   # add Gemma 4 pulls (§1) in the same step
bash scripts/setup.sh --help          # all flags
```

`setup.sh` hard-checks that `uv` is on PATH, soft-warns on missing
`redis-cli` / `ollama` / `tmux` (those are runtime, not install-time), and
delegates to the same `uv sync` invocations documented below. If you'd
rather drive `uv sync` yourself, pick the slice that matches what you want
to run:

```bash
# Sim only (waypoint runner, frame server, mesh simulator)
uv sync --extra sim --extra mesh --extra dev

# Full graph — drones, EGS, bridge, ML.
uv sync --all-extras
```

Activate the venv directly if you prefer not to prefix everything with
`uv run`:

```bash
source .venv/bin/activate          # macOS / Linux / WSL2
# .venv\Scripts\activate            # Windows PowerShell
```

If your shell already has another project's `.venv` activated, run
`deactivate` first — `uv sync` prints a confusing
`VIRTUAL_ENV=... does not match the project environment path .venv`
warning otherwise and falls back to the on-disk venv path (correct, but
unsettling).

You don't strictly need to activate before running the `scripts/*.sh`
launchers in §4 — those auto-detect `.venv/bin/activate` and source it
inside the tmux subshells they spawn. Activating in your shell is still
useful for running individual commands like `pytest` or `ruff` without
the `uv run` prefix.

## 3. First-run validation: pytest

Before launching anything, confirm the install is healthy:

```bash
PYTHONPATH=. uv run python -m pytest sim/ agents/mesh_simulator/ scripts/tests/ -v
```

This is the same set CI runs in the `sim_mesh` job
([`.github/workflows/test.yml`](../.github/workflows/test.yml)). Everything
should pass against `uv sync --extra sim --extra mesh --extra dev`. If any
test fails on a clean checkout, stop and file an issue — that's a Phase G
blocker.

If you ran `uv sync --all-extras`, you can also exercise the bridge and
shared-contracts tests:

```bash
PYTHONPATH=. uv run python -m pytest shared/ frontend/ws_bridge/tests/ -m "not e2e" -v
```

The Playwright e2e suite (`-m e2e`) needs a built Flutter web bundle and
Chromium; skip it on first run.

## 4. Three escalating one-command demos

Each demo is one bash command from the repo root. Run them in order — if (a)
fails, (b) and (c) will fail the same way.

Make sure Redis is running before each one (`redis-cli ping → PONG`). If the
broker is already running as a system service, `launch_swarm.sh` reuses it;
otherwise the script daemonizes its own and writes
`$LOG_DIR/.gg_started_redis` so `stop_demo.sh` knows which broker is safe to
shut down (Contract: see anomaly #3 below).

`scripts/run_full_demo.sh [scenario]` is an umbrella over `launch_swarm.sh`
that adds log tailing and Ctrl-C cleanup; all flags below forward verbatim
(`--drones=...`, `--duration=N`, `--dry-run`). The README and submission
checklist both point users at this script — the per-scenario invocations
in (a)/(b)/(c) below are the equivalent direct calls if you want finer
control over what gets launched.

### a. Single-drone smoke (~30 seconds wall time)

```bash
bash scripts/launch_swarm.sh single_drone_smoke --drones=auto --duration=30
```

What this exercises:

- `sim/waypoint_runner.py` publishes `drones.drone1.state` at 2 Hz.
- `sim/frame_server.py` publishes `drones.drone1.camera` (raw JPEG bytes) at
  1 Hz.
- `agents/mesh_simulator/main.py` publishes `mesh.adjacency_matrix` (single
  drone → empty neighbour list).
- `--duration=30` propagates to the sim runners only; they self-terminate
  after 30 s with `[waypoint_runner] reached --duration=30.0s; exiting
  cleanly.` (drone agents and EGS do not accept `--duration`).
- Components that haven't been built yet for your role (e.g. drone agent,
  EGS) are logged as `[skip] <window> — <path> not present yet` rather than
  failing the launch. That's intentional and is what lets the sim run before
  the rest of the stack is wired.
- **On a fully-built repo** (`uv sync --all-extras` already run), this ALSO
  launches `agents/egs_agent/main.py`, the per-drone `agents/drone_agent`,
  and the `ws_bridge` uvicorn server. Each will attempt to connect to
  Ollama for Gemma 4 — pull `gemma4:e2b` and `gemma4:e4b` first (see
  "Gemma 4 model tags" above in §1) or agent boot logs a clear Ollama
  healthcheck warning and the run still proceeds, just without
  perception output.
- **`shared/config.yaml` `mission.drone_count` must match the scenario's
  drone count.** The default `drone_count: 3` aligns with
  `disaster_zone_v1` / `resilience_v1`. Before running
  `single_drone_smoke` (1 drone), edit `mission.drone_count: 1` in
  `shared/config.yaml` or `waypoint_runner` will exit with a clear
  reconcile-the-two error.

After the runners self-terminate, tear down with:

```bash
bash scripts/stop_demo.sh
```

### b. Hybrid 3-drone demo (real sim + fake EGS/findings)

```bash
bash scripts/run_hybrid_demo.sh disaster_zone_v1
```

This is the recommended demo for the bridge cutover window — it pairs the
real sim (`drones.<id>.state` from `sim/waypoint_runner.py`) with
`scripts/dev_fake_producers.py` instances that mock `egs.state` and per-drone
`drones.<id>.findings` until Qasim/Kaleel ship the real publishers. The
WebSocket bridge launches via uvicorn on `:9090`.

Drop the fakes once the real producers exist:

```bash
# Once Qasim ships real EGS state on egs.state
bash scripts/run_hybrid_demo.sh disaster_zone_v1 --no-fake-egs

# Once Kaleel ships real findings on drones.<id>.findings
bash scripts/run_hybrid_demo.sh disaster_zone_v1 --no-fake-findings

# Post-migration: real everywhere
bash scripts/run_hybrid_demo.sh disaster_zone_v1 --no-fake-egs --no-fake-findings
```

Verification (waits for one `state_update` envelope on the bridge and asserts
all scenario drones plus at least one finding are present):

```bash
PYTHONPATH=. uv run python scripts/check_hybrid_demo.py
```

Stop:

```bash
bash scripts/stop_demo.sh hybrid_demo
```

### c. Full resilience scenario (~4 minutes wall time)

```bash
bash scripts/run_resilience_scenario.sh
```

This is a thin wrapper around `launch_swarm.sh` that injects
`--duration=240` (matching the scripted `mission_complete` event in
`sim/scenarios/resilience_v1.yaml`) and pins the scenario to `resilience_v1`.
All other flags forward verbatim, e.g. `--drones=drone2,drone3` or
`--dry-run`.

What `resilience_v1` exercises:

- 3 drones start within ~25 m of each other (full-mesh) and fan radially
  outward at 5 m/s.
- By t≈18 s `drone1`↔`drone3` drop out of mesh range
  (`mesh.range_meters: 200` in `shared/config.yaml`).
- By t≈98 s `drone1` and `drone3` exit EGS link range
  (`mesh.egs_link_range_meters: 500`).
- Scripted events fire `drone_failure`, `fire_spread`, `egs_link_drop`,
  `egs_link_restore`, and `mission_complete` over the 240 s run.

Tear down (default tmux session is `fieldagent`):

```bash
bash scripts/stop_demo.sh
```

## 5. Per-layer health checks

While a demo is running, check each layer independently. All log paths
default to `/tmp/gemma_guardian_logs/` and honor `GG_LOG_DIR` (override via
`GG_LOG_DIR=/path/to/logs bash scripts/launch_swarm.sh ...`).

### Redis

```bash
redis-cli ping                                   # → PONG
redis-cli pubsub channels 'drones.*'             # active drone channels
redis-cli psubscribe 'drones.drone1.state'       # tail one drone's state
```

### Logs on disk

```bash
ls $GG_LOG_DIR 2>/dev/null || ls /tmp/gemma_guardian_logs/
# Expected files (per Contract 11):
#   waypoint_runner.log    sim/waypoint_runner.py stdout/stderr
#   frame_server.log       sim/frame_server.py
#   mesh.log               agents/mesh_simulator/main.py
#   egs.log                agents/egs_agent/main.py (if present)
#   drone1.log, drone2.log, drone3.log   per-drone agent
#   ws_bridge.log          frontend/ws_bridge/main.py via uvicorn
#   redis.log              only when launch_swarm.sh daemonized its own redis
#   validation_events.jsonl  every Algorithm-1 validation event
#   .gg_started_redis      ownership sentinel (see §6 anomaly 3)
```

`validation_events.jsonl` is the source for the writeup's quantitative
claims; each line conforms to `shared/schemas/validation_event.json`.

### Tmux

```bash
tmux ls                                          # 'fieldagent' or 'hybrid_demo'
tmux attach -t fieldagent                        # ctrl-b d to detach
```

Each process has its own window — `waypoint`, `frames`, `mesh`, `egs`,
`drone1`, `drone2`, `drone3`, `ws_bridge`. Components that were absent at
launch time were logged as `[skip]` and have no window.

### Dashboard (Flutter web)

`scripts/launch_swarm.sh` and `scripts/run_hybrid_demo.sh` only start the
WebSocket bridge on `ws://localhost:9090/`. To see the operator UI itself,
start the Flutter dev server in a separate pane (assumes
`uv sync --extra ws_bridge --extra dev` and `flutter` on PATH):

```bash
bash scripts/run_dashboard_dev.sh
```

This launches the bridge, fake producers, an actions logger, and the Flutter
web dev server on `http://localhost:8000`. To point the dashboard at a
non-default bridge port, append `?ws=...`:

```
http://localhost:8000/?ws=ws://127.0.0.1:9091/
```

(`_wsBridgeUrl()` in `frontend/flutter_dashboard/lib/main.dart` reads the
query parameter; documented in
[`frontend/flutter_dashboard/README.md`](../frontend/flutter_dashboard/README.md).)

The dashboard renders four panels: Map, Drone Status, Findings, Command. On
a healthy hybrid demo run all four populate within ~5 s of the page loading.

## 6. Common failures and fixes

These are drawn from [`docs/sim-live-run-notes.md`](sim-live-run-notes.md)
and the regressions covered by `scripts/tests/test_launch_scripts.py`. Do
not invent failure modes for this section — if you hit something not listed
here on a cold run, file it as a Phase G blocker so we can add it.

### Redis is down

```
redis.exceptions.ConnectionError
```

Fix: `redis-cli ping` should return `PONG`. On WSL2 distros without systemd,
use `sudo service redis-server start` (per
[`13-runtime-setup.md`](13-runtime-setup.md) §"Linux (Ubuntu 22.04 / 24.04 /
Debian)"). On macOS, `brew services start redis`. On Windows-native,
`Start-Service Redis`.

### `redis-cli ping` returns "Connection refused" after `stop_demo.sh`

Fixed in [`feature/sim-live-run-followups`](sim-live-run-notes.md). The
script now only shuts down Redis when `launch_swarm.sh` left a
`$LOG_DIR/.gg_started_redis` sentinel — i.e. when we daemonized the broker
ourselves. On WSL2 boxes where Redis is a long-lived `service` you started
manually, the sentinel is absent and `stop_demo.sh` leaves it alone.
Regression coverage: `test_stop_demo_leaves_redis_alone_when_sentinel_absent`
and `test_launch_swarm_no_sentinel_when_redis_already_running` in
[`scripts/tests/test_launch_scripts.py`](../scripts/tests/test_launch_scripts.py).

### `--drones=droneN` exits with "requested drone … is not in scenario"

```
[error] requested drone 'drone7' is not in scenario 'disaster_zone_v1'
        (available: drone1,drone2,drone3)
```

Working as intended: every requested id must appear in the scenario YAML's
`drones[].drone_id` list, otherwise the launcher would silently start a
drone agent against a `--drone-id` the sim never publishes for.
Use `--drones=auto` (the default) to derive the roster from the scenario, or
fix the typo in your CSV. Regression coverage:
`test_launch_swarm_explicit_drones_unknown_id_is_rejected`.

### `frontend/ws_bridge/main.py` exits immediately, no server on :9090

Symptom: bridge window in tmux closes within a second; `lsof -i :9090`
empty. Cause: invoking the module as a script — `frontend/ws_bridge/main.py`
only constructs the FastAPI app and exits with no embedded server. Both
`launch_swarm.sh` and `run_hybrid_demo.sh` now spawn it as
`python3 -m uvicorn frontend.ws_bridge.main:app --port 9090`. Regression
coverage: `test_launch_swarm_bridge_invocation_uses_uvicorn`.

If you wrote your own launcher, mirror the uvicorn invocation.

### `agents/drone_agent/main.py` ImportError on relative imports

This is a known issue when running the drone agent as a bare script. Use the
package form instead, exactly as `launch_swarm.sh` does:

```bash
python3 -m agents.drone_agent --drone-id drone1 --scenario disaster_zone_v1
```

The script-form failure is flagged for Kaleel in
[`docs/sim-live-run-notes.md`](sim-live-run-notes.md) as out of Hazim scope.

### Ollama: first inference times out (`httpx.ReadTimeout`)

Cold-loading the 7.2 GB `gemma4:e2b` model plus the first vision+tools call
exceeds 30 s on Apple Silicon CPU. The agent's default timeout is 120 s
(see `agents/drone_agent/reasoning.py`). If you still hit a timeout on a
slower box, pre-warm Ollama with one round-trip before starting the agent:

```bash
curl -s -X POST http://127.0.0.1:11434/api/chat \
  -d '{"model":"gemma4:e2b","stream":false,"messages":[{"role":"user","content":"hi"}]}'
```

Once the model is warm, subsequent calls land in 30–45 s on CPU.

**Apple Silicon (M1/M2/M3) + 3-drone concurrent vision+tools:** the text
warm above is INSUFFICIENT. Metal serializes inference across drones at
the daemon level; the warm-up has to mirror the real call shape (image
bytes + the `report_finding` tool definition) and the agent's httpx
timeout has to be raised. The reproducible recipe (tested on M1 16GB):
`OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`,
`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KEEP_ALIVE=30m`, vision+tools
pre-warm via `scripts/run_drone3_reliability.sh:70-87`, and
`DRONE_AGENT_OLLAMA_TIMEOUT_S=240`. Full tuning table + rationale:
[`plans/2026-05-12-drone3-reliability-capture.md`](plans/2026-05-12-drone3-reliability-capture.md).

### Mesh adjacency is full-mesh in `disaster_zone_v1`

Not a bug. The scenario's three drones stay within ~200 m of each other for
the full run, so the default `mesh.range_meters: 200` puts everyone in
everyone's neighbour list. To exercise mesh-dropout dynamics, run the
`resilience_v1` scenario instead (§4c) — drones fan out radially and drop
out of range on a known schedule.

### `--duration=N` on `disaster_zone_v1`

`--duration` propagates to `sim/waypoint_runner.py` and `sim/frame_server.py`
only. Drone agents and EGS do not accept it and will keep running until you
`stop_demo.sh` them. This is the correct behaviour for scripted demos and
CI; the sim runners self-terminate, the agents stay alive for the operator
to inspect. Regression coverage:
`test_launch_swarm_duration_propagates_to_runners` and
`test_launch_swarm_default_no_duration_flag_anywhere`.

## 7. Reproducing fixture images

The 8 JPEGs under `sim/fixtures/frames/` and the static aerial under
`sim/fixtures/base_images/` are real public-domain disaster aerials
(FEMA Photo Library + USFWS), not synthetic. The full source manifest
lives at `scripts/fixtures_manifest.json` and the fetch is fully
reproducible:

```bash
uv run python -m scripts.fetch_disaster_fixtures --dry-run     # preview URLs
uv run python -m scripts.fetch_disaster_fixtures               # fetch + write
```

Re-running is byte-stable so long as the upstream Wikimedia/FEMA bytes
haven't been re-encoded — every entry in the manifest pins a
`source_sha256` and the script verifies the upstream payload hash BEFORE
Pillow processes it. If a future re-fetch fails with `source sha256
mismatch`, that's the lockdown working as designed: the upstream changed,
so the manifest must be reviewed manually before refreshing.

Every file has a full provenance entry in
`sim/fixtures/frames/LICENSES.md` (or
`sim/fixtures/base_images/LICENSES.md` for the scene aerial). The
provenance lockdown test at `sim/tests/test_fixture_provenance.py` blocks
any swap that drops attribution or violates the ≤640×480 / ≤200KB
constraint, and the scenario-load regression test at
`sim/tests/test_scenario_loads_with_real_fixtures.py` walks all three
scenarios through `FrameServer(tick_index=0)` to catch corrupt or
mis-encoded JPEGs that pass magic-byte checks but fail Pillow decode.

xBD-proper (xView2 credentials-gated) is unaffected by this — that's the
ML fine-tune pipeline at `ml/data_prep/download_xbd.py` and remains a
separate concern.

## 8. Cross-references

- Per-platform install (Python, Redis, Ollama):
  [`13-runtime-setup.md`](13-runtime-setup.md)
- Process layout, scaling 2→3 drones, manual-pilot REPL:
  [`15-multi-drone-spawning.md`](15-multi-drone-spawning.md)
- Locked Redis channels, schemas, model tags:
  [`20-integration-contracts.md`](20-integration-contracts.md)
- Live-run anomaly log:
  [`sim-live-run-notes.md`](sim-live-run-notes.md)
- Demo-capture runbook (Playwright MCP):
  [`runbooks/mcp-dom-verification.md`](runbooks/mcp-dom-verification.md)
