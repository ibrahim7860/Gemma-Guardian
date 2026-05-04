# Bridge Cutover (Hybrid Mode) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the bridge over from `dev_fake_producers.py` to Hazim's real sim for `drones.<id>.state`, while keeping fake-producer fallbacks for `egs.state` and `drones.<id>.findings` until Qasim's EGS and Kaleel's drone agent ship findings to Redis.

**Architecture:** Add an `--emit=<csv>` flag to `dev_fake_producers.py` so each instance can be scoped to a subset of channels (`state`, `egs`, `findings`). Write a `scripts/run_hybrid_demo.sh` orchestrator that runs the real sim for drone state plus fake producers for `egs.state` and per-drone `findings`. Two opt-out flags (`--no-fake-egs`, `--no-fake-findings`, default OFF — i.e., fakes ON) make the eventual flip a single CLI argument when Qasim's EGS / Kaleel's drone agent ship — no source edits, no risk of dangling fake processes. Add `scripts/check_hybrid_demo.py` (WS smoke verifier) and a parallel pytest in `scripts/tests/test_launch_scripts.py` that pins the dry-run output of the new orchestrator.

**Tech Stack:** Python 3.11+, redis-py (sync), bash, tmux (orchestrator), pytest for flag tests, `httpx-ws` (already in dev extras) for the smoke verifier.

---

## File Structure

**Modify:**
- `scripts/dev_fake_producers.py` — add `--emit` flag, gate per-channel publishes on it, update module docstring with hybrid-mode rationale.
- `scripts/tests/test_launch_scripts.py` — add dry-run regression test for `run_hybrid_demo.sh` (mirrors `test_launch_swarm_dry_run_prints_commands`).
- `TODOS.md` — close the bridge-cutover entry once shipped.

**Create:**
- `scripts/tests/test_dev_fake_producers.py` — pytest coverage for the new `--emit` flag (parser + behaviour, including the `egs,findings` hybrid combo).
- `scripts/run_hybrid_demo.sh` — tmux orchestrator (sim + N+1 fake producers + bridge + dashboard) with `--no-fake-egs` / `--no-fake-findings` opt-out flags.
- `scripts/check_hybrid_demo.py` — WS smoke verifier; connects to `ws://localhost:9090/`, asserts within 10 s that the envelope contains real-shape drone state for every scenario drone and ≥1 fake finding.

---

## Task 0: Branch setup

**Files:** none (git only)

- [ ] **Step 0: Confirm clean tree on `main` and create the feature branch BEFORE any commit**

```bash
git status                    # must show "working tree clean"
git checkout main
git pull --ff-only
git checkout -b feature/bridge-cutover-hybrid
```

Expected: branch created, no diffs. If `git status` is dirty, stop and surface to the user — don't stash, don't commit on main.

---

## Task 1: Add `--emit` flag to dev_fake_producers.py (TDD)

**Files:**
- Create: `scripts/tests/test_dev_fake_producers.py`
- Modify: `scripts/dev_fake_producers.py` (`_parse_args`, `_run`, module docstring)

- [ ] **Step 1: Write the failing test for parser default + parsing**

Create `scripts/tests/test_dev_fake_producers.py`:

```python
"""Tests for dev_fake_producers.py CLI surface and emission gating.

We avoid spinning up Redis: ``_run`` is bypassed entirely by patching
``redis.Redis.from_url`` to a Mock that records ``publish`` calls.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts import dev_fake_producers as dfp  # noqa: E402


def test_parser_default_emits_all_channels():
    args = dfp._parse_args([])
    assert args.emit == ["state", "egs", "findings"]


def test_parser_emit_csv_subset():
    args = dfp._parse_args(["--emit", "egs,findings"])
    assert args.emit == ["egs", "findings"]


def test_parser_emit_rejects_unknown_token():
    with pytest.raises(SystemExit):
        dfp._parse_args(["--emit", "egs,bogus"])
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
PYTHONPATH=. uv run --extra dev pytest scripts/tests/test_dev_fake_producers.py -v
```

Expected: all three tests FAIL — `args.emit` does not exist on the namespace; the parser does not understand `--emit`.

- [ ] **Step 3: Implement the `--emit` flag in `_parse_args`**

In `scripts/dev_fake_producers.py`, locate `_parse_args` (around line 181) and:

1. Add a module-level constant near `_FINDING_TYPE_ROTATION` (~ line 67):

```python
# Allowed tokens for --emit. Each value enables one channel family. Default
# (all three) keeps backwards compatibility with existing dev workflows
# that did not pass --emit.
_EMIT_CHANNEL_TOKENS: List[str] = ["state", "egs", "findings"]
```

2. Add a parser helper above `_parse_args`:

```python
def _parse_emit_csv(value: str) -> List[str]:
    """argparse type-converter for --emit. Splits on comma, strips whitespace,
    and rejects unknown tokens with argparse.ArgumentTypeError so the parser
    exits with a clear message instead of failing later at publish time."""
    tokens = [t.strip() for t in value.split(",") if t.strip()]
    if not tokens:
        raise argparse.ArgumentTypeError(
            "--emit must contain at least one of: "
            f"{','.join(_EMIT_CHANNEL_TOKENS)}"
        )
    bad = [t for t in tokens if t not in _EMIT_CHANNEL_TOKENS]
    if bad:
        raise argparse.ArgumentTypeError(
            f"--emit got unknown token(s): {bad}. "
            f"Valid tokens: {_EMIT_CHANNEL_TOKENS}"
        )
    return tokens
```

3. Add the argument to the parser (inside `_parse_args`, after `--no-validate`):

```python
    parser.add_argument(
        "--emit",
        type=_parse_emit_csv,
        default=list(_EMIT_CHANNEL_TOKENS),
        help=(
            "Comma-separated subset of channel families to emit. "
            "Tokens: state (drones.<id>.state, every tick), "
            "egs (egs.state, every 2 ticks), "
            "findings (drones.<id>.findings, every 8 ticks). "
            "Default: all three. Hybrid demo mode runs one --emit=state "
            "instance disabled (sim owns it) and one --emit=egs,findings "
            "instance enabled until Qasim/Kaleel ship real producers."
        ),
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
PYTHONPATH=. uv run --extra dev pytest scripts/tests/test_dev_fake_producers.py -v
```

Expected: all three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/tests/test_dev_fake_producers.py scripts/dev_fake_producers.py
git commit -m "dev_fake_producers: add --emit flag (CSV gate for state/egs/findings)"
```

---

## Task 2: Wire `--emit` into the publish loop

**Files:**
- Modify: `scripts/dev_fake_producers.py` (`_run`)
- Modify: `scripts/tests/test_dev_fake_producers.py` (add behaviour tests)

- [ ] **Step 1: Write the failing tests for emission gating**

Append to `scripts/tests/test_dev_fake_producers.py`:

```python
def _stub_args(**overrides):
    """Build a SimpleNamespace mimicking argparse output for _run."""
    import types
    base = dict(
        redis_url="redis://localhost:6379",
        drone_id="drone1",
        tick_s=0.0,           # zero-sleep so the test never actually sleeps
        no_validate=False,
        emit=["state", "egs", "findings"],
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def _channels_published(mock_client) -> list[str]:
    return [call.args[0] for call in mock_client.publish.call_args_list]


@patch("scripts.dev_fake_producers.time.sleep", side_effect=KeyboardInterrupt)
@patch("scripts.dev_fake_producers.redis.Redis.from_url")
def test_run_default_publishes_all_three_channels(mock_from_url, _mock_sleep):
    client = MagicMock()
    mock_from_url.return_value = client
    rc = dfp._run(_stub_args())
    assert rc == 0
    channels = _channels_published(client)
    # First tick (tick=0): state + egs + findings (8|0 and 2|0).
    assert "drones.drone1.state" in channels
    assert "egs.state" in channels
    assert "drones.drone1.findings" in channels


@patch("scripts.dev_fake_producers.time.sleep", side_effect=KeyboardInterrupt)
@patch("scripts.dev_fake_producers.redis.Redis.from_url")
def test_run_emit_findings_only_skips_state_and_egs(mock_from_url, _mock_sleep):
    client = MagicMock()
    mock_from_url.return_value = client
    rc = dfp._run(_stub_args(emit=["findings"]))
    assert rc == 0
    channels = _channels_published(client)
    assert "drones.drone1.findings" in channels
    assert "drones.drone1.state" not in channels
    assert "egs.state" not in channels


@patch("scripts.dev_fake_producers.time.sleep", side_effect=KeyboardInterrupt)
@patch("scripts.dev_fake_producers.redis.Redis.from_url")
def test_run_emit_egs_only_skips_drone_channels(mock_from_url, _mock_sleep):
    client = MagicMock()
    mock_from_url.return_value = client
    rc = dfp._run(_stub_args(emit=["egs"]))
    assert rc == 0
    channels = _channels_published(client)
    assert channels == ["egs.state"]


@patch("scripts.dev_fake_producers.time.sleep", side_effect=KeyboardInterrupt)
@patch("scripts.dev_fake_producers.redis.Redis.from_url")
def test_run_emit_egs_and_findings_is_the_hybrid_mode(mock_from_url, _mock_sleep):
    """The actual mode the orchestrator runs: fakes own egs + findings, real
    sim owns drones.<id>.state. This is the contract the cutover depends on."""
    client = MagicMock()
    mock_from_url.return_value = client
    rc = dfp._run(_stub_args(emit=["egs", "findings"]))
    assert rc == 0
    channels = _channels_published(client)
    assert "egs.state" in channels
    assert "drones.drone1.findings" in channels
    assert "drones.drone1.state" not in channels, (
        "hybrid mode must NOT emit drone state (sim owns that channel)"
    )
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run:
```bash
PYTHONPATH=. uv run --extra dev pytest scripts/tests/test_dev_fake_producers.py -v
```

Expected: the four new behavior tests FAIL — `_run` still emits all three channels regardless of `args.emit` (the flag exists from Task 1 but is unused).

- [ ] **Step 3: Gate publishes on `args.emit` inside `_run`**

In `scripts/dev_fake_producers.py`, replace the `_run` function body's publish block with conditional emission. Locate `_run` (around line 234) and change the inner `try` block to:

```python
    try:
        emit_state: bool = "state" in args.emit
        emit_egs: bool = "egs" in args.emit
        emit_findings: bool = "findings" in args.emit
        while True:
            # Drone state: every tick. Skipped when --emit excludes "state"
            # (hybrid mode: sim/waypoint_runner.py owns drones.<id>.state).
            if emit_state:
                ds_payload = _build_drone_state(drone_id, tick)
                if validate_payloads:
                    _validate_or_die("drone_state", ds_payload)
                _publish(client, drone_state_channel, ds_payload)
                print(
                    f"[fake_producer] tick={tick} channel={drone_state_channel} "
                    f"battery={ds_payload['battery_pct']}"
                )

            # EGS state: every 2 ticks. Skipped when --emit excludes "egs"
            # (replaced by Qasim's agents/egs_agent/main.py once it aligns
            # zone_polygon to the active scenario YAML).
            if emit_egs and tick % 2 == 0:
                egs_payload = _build_egs_state(tick)
                if validate_payloads:
                    _validate_or_die("egs_state", egs_payload)
                _publish(client, EGS_STATE, egs_payload)
                print(
                    f"[fake_producer] tick={tick} channel={EGS_STATE} "
                    f"mission_id={egs_payload['mission_id']}"
                )

            # Finding: every 8 ticks. Skipped when --emit excludes "findings"
            # (replaced by Kaleel's drone agent once action.py publishes to
            # Redis instead of stdout).
            if emit_findings and tick % 8 == 0:
                finding_payload = _build_finding(drone_id, finding_counter)
                if validate_payloads:
                    _validate_or_die("finding", finding_payload)
                _publish(client, finding_channel, finding_payload)
                print(
                    f"[fake_producer] tick={tick} channel={finding_channel} "
                    f"finding_id={finding_payload['finding_id']} "
                    f"type={finding_payload['type']}"
                )
                finding_counter += 1

            tick += 1
            time.sleep(tick_s)
    except KeyboardInterrupt:
        print("[fake_producer] shutting down")
        return 0
```

- [ ] **Step 4: Run all tests to verify they pass**

Run:
```bash
PYTHONPATH=. uv run --extra dev pytest scripts/tests/test_dev_fake_producers.py -v
```

Expected: all seven tests PASS (3 from Task 1 + 4 from Task 2, including `test_run_emit_egs_and_findings_is_the_hybrid_mode`).

- [ ] **Step 5: Update the module docstring to document hybrid mode**

In `scripts/dev_fake_producers.py`, replace the WARNING paragraph (around line 12) with:

```python
"""Dev-only Redis fake-producer for the Phase 2+ WebSocket bridge.

Originally scaffolding for Phase 2 dashboard development before any real
producers existed. Now also serves as a fallback during the bridge cutover
to Hazim's sim: each instance can be scoped to a subset of channels via
``--emit``, so the real sim owns ``drones.<id>.state`` while this script
keeps emitting ``egs.state`` and per-drone ``findings`` until Qasim
(EGS) and Kaleel (drone agent) ship their real publishers.

Channel families (gated by --emit):
    state       drones.<drone_id>.state         (every tick, schema: drone_state)
    egs         egs.state                       (every 2 ticks, schema: egs_state)
    findings    drones.<drone_id>.findings      (every 8 ticks, schema: finding)

WARNING: Still dev-only scaffolding. Channel and schema bindings come from
shared.contracts.topics and shared.contracts.validate; do not hardcode
channel strings or payload shapes.

Hybrid demo recipe (orchestrated by scripts/run_hybrid_demo.sh):
    sim/waypoint_runner.py --scenario disaster_zone_v1   # state, real
    dev_fake_producers.py --emit=egs                     # egs.state, fake
    dev_fake_producers.py --emit=findings --drone-id drone1
    dev_fake_producers.py --emit=findings --drone-id drone2
    dev_fake_producers.py --emit=findings --drone-id drone3

drone_id default note (deviation from spec):
    The Phase 2 design spec proposed `dev_drone1` as the default to avoid
    collision with Hazim's `drone1`. However the locked v1 contract
    schema (`shared/schemas/_common.json`) requires drone_id to match
    `^drone\\d+$`, which excludes any `dev_` prefix. To keep the script's
    output schema-valid by default while still avoiding collision with
    Hazim's `drone1`/`drone2`/`drone3` IDs, the default is `drone99`.
    Override with --drone-id at the CLI if you need a specific value
    (e.g. matching a sim drone in hybrid mode or a Playwright fixture).

Usage:
    python scripts/dev_fake_producers.py
    python scripts/dev_fake_producers.py --emit=findings --drone-id drone1
    python scripts/dev_fake_producers.py --emit=egs --tick-s 0.5
    python scripts/dev_fake_producers.py --redis-url redis://localhost:6379
"""
```

- [ ] **Step 6: Commit**

```bash
git add scripts/dev_fake_producers.py scripts/tests/test_dev_fake_producers.py
git commit -m "dev_fake_producers: gate publishes on --emit; document hybrid mode"
```

---

## Task 3: Hybrid demo orchestrator script

**Files:**
- Create: `scripts/run_hybrid_demo.sh`

- [ ] **Step 1: Create the orchestrator**

Create `scripts/run_hybrid_demo.sh`:

```bash
#!/bin/bash
#
# run_hybrid_demo.sh — bridge cutover hybrid mode launcher.
#
# Runs the real sim for drones.<id>.state and dev_fake_producers.py for the
# remaining channels (egs.state, drones.<id>.findings) until Qasim and
# Kaleel ship real publishers. Mirrors launch_swarm.sh's tmux style and
# DRY-RUN semantics.
#
# Usage:
#   scripts/run_hybrid_demo.sh [scenario] [flags]
#
# Flags:
#   --dry-run           Print the plan, do not start tmux.
#   --duration=N        Forwarded to sim runners (they self-terminate).
#                       Fake producers ignore --duration and must be killed
#                       via stop_demo.sh or tmux kill.
#   --no-fake-egs       Suppress the fake egs.state producer. Use this once
#                       Qasim's agents/egs_agent/main.py aligns zone_polygon
#                       to the scenario YAML.
#   --no-fake-findings  Suppress the per-drone fake findings producers. Use
#                       this once Kaleel's drone agent publishes to Redis.
#
# Scenario default: disaster_zone_v1.
#
# Env overrides:
#   GG_NO_TMUX=1   — skip tmux invocation; just print plans (used by tests)
#   GG_REDIS_URL   — defaults to redis://localhost:6379/0
#   GG_LOG_DIR     — defaults to /tmp/gemma_guardian_logs
#
# Migration path: edit a wrapper script (or pass the flag at the CLI) to
# add --no-fake-egs / --no-fake-findings as the real producers ship. No
# source edits to this file required, no risk of dangling fake processes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${GG_LOG_DIR:-/tmp/gemma_guardian_logs}"
REDIS_URL="${GG_REDIS_URL:-redis://localhost:6379/0}"

DRY_RUN=0
SCENARIO="disaster_zone_v1"
DURATION=""
FAKE_EGS=1
FAKE_FINDINGS=1

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --duration=*) DURATION="${arg#--duration=}" ;;
    --no-fake-egs) FAKE_EGS=0 ;;
    --no-fake-findings) FAKE_FINDINGS=0 ;;
    --*) echo "unknown flag: $arg" >&2; exit 2 ;;
    *)   SCENARIO="$arg" ;;
  esac
done

DURATION_ARG=""
if [ -n "$DURATION" ]; then
  DURATION_ARG="--duration $DURATION"
fi

# Resolve drone roster from the scenario YAML.
if ! DRONES="$(PYTHONPATH="$REPO_ROOT" python3 "$REPO_ROOT/sim/list_drones.py" "$SCENARIO")"; then
  echo "[error] failed to derive drone roster from scenario '$SCENARIO'" >&2
  exit 1
fi

emit() {
  local window="$1"; shift
  echo "[plan] tmux:${window} :: $*"
  if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
    tmux new-window -t hybrid_demo -n "$window"
    tmux send-keys -t "hybrid_demo:${window}" "$*" Enter
  fi
}

mkdir -p "$LOG_DIR"

# --- Redis (mirror of launch_swarm.sh's sentinel logic) --------------------
SENTINEL="$LOG_DIR/.gg_started_redis"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "[plan] redis-server (or skip if already running)"
else
  if command -v redis-cli >/dev/null 2>&1 && redis-cli ping >/dev/null 2>&1; then
    echo "[ok] redis-server already running (will not be stopped by stop_demo.sh)"
    rm -f "$SENTINEL"
  elif command -v redis-server >/dev/null 2>&1; then
    redis-server --daemonize yes --logfile "$LOG_DIR/redis.log"
    : > "$SENTINEL"
    echo "[ok] redis-server started, log: $LOG_DIR/redis.log"
  else
    echo "[error] redis-server not found on PATH" >&2
    exit 1
  fi
fi

# --- tmux session ---------------------------------------------------------
if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
  if ! command -v tmux >/dev/null 2>&1; then
    echo "[error] tmux not on PATH; install or use --dry-run" >&2
    exit 1
  fi
  tmux kill-session -t hybrid_demo 2>/dev/null || true
  tmux new-session -d -s hybrid_demo -n placeholder
fi

# --- Real sim (Hazim) — owns drones.<id>.state -----------------------------
emit waypoint "cd $REPO_ROOT && python3 sim/waypoint_runner.py --scenario $SCENARIO --redis-url $REDIS_URL $DURATION_ARG 2>&1 | tee $LOG_DIR/waypoint_runner.log"
emit frames   "cd $REPO_ROOT && python3 sim/frame_server.py    --scenario $SCENARIO --redis-url $REDIS_URL $DURATION_ARG 2>&1 | tee $LOG_DIR/frame_server.log"

# --- Fake EGS state (default ON; pass --no-fake-egs once Qasim ships) ----
if [ "$FAKE_EGS" -eq 1 ]; then
  emit egs_fake "cd $REPO_ROOT && python3 scripts/dev_fake_producers.py --emit=egs --redis-url $REDIS_URL 2>&1 | tee $LOG_DIR/egs_fake.log"
else
  echo "[skip] egs_fake — --no-fake-egs set (Qasim's EGS owns egs.state)"
fi

# --- Fake findings (default ON; pass --no-fake-findings once Kaleel ships) -
if [ "$FAKE_FINDINGS" -eq 1 ]; then
  IFS=',' read -ra DRONE_ARRAY <<< "$DRONES"
  for ID in "${DRONE_ARRAY[@]}"; do
    emit "findings_$ID" "cd $REPO_ROOT && python3 scripts/dev_fake_producers.py --emit=findings --drone-id $ID --redis-url $REDIS_URL 2>&1 | tee $LOG_DIR/findings_${ID}_fake.log"
  done
else
  echo "[skip] findings_* — --no-fake-findings set (drone agent owns drones.<id>.findings)"
fi

# --- WebSocket bridge (Ibrahim) -------------------------------------------
emit ws_bridge "cd $REPO_ROOT && python3 frontend/ws_bridge/main.py 2>&1 | tee $LOG_DIR/ws_bridge.log"

if [ "$DRY_RUN" -eq 0 ] && [ "${GG_NO_TMUX:-0}" != "1" ]; then
  tmux kill-window -t hybrid_demo:placeholder 2>/dev/null || true
  echo ""
  echo "Hybrid demo running in tmux session 'hybrid_demo'."
  echo "Attach with: tmux attach -t hybrid_demo"
  echo "Logs at: $LOG_DIR/"
  echo "Stop with: scripts/stop_demo.sh hybrid_demo  (or: tmux kill-session -t hybrid_demo)"
fi
```

- [ ] **Step 2: Make it executable**

Run:
```bash
chmod +x scripts/run_hybrid_demo.sh
```

- [ ] **Step 3: Verify dry-run prints the expected plan**

Run:
```bash
scripts/run_hybrid_demo.sh --dry-run disaster_zone_v1
```

Expected output (relevant lines, drone roster comes from scenario YAML — `disaster_zone_v1` has drone1, drone2, drone3):

```
[plan] redis-server (or skip if already running)
[plan] tmux:waypoint :: cd .../sim/waypoint_runner.py --scenario disaster_zone_v1 ...
[plan] tmux:frames :: cd .../sim/frame_server.py --scenario disaster_zone_v1 ...
[plan] tmux:egs_fake :: cd .../scripts/dev_fake_producers.py --emit=egs ...
[plan] tmux:findings_drone1 :: cd .../scripts/dev_fake_producers.py --emit=findings --drone-id drone1 ...
[plan] tmux:findings_drone2 :: cd .../scripts/dev_fake_producers.py --emit=findings --drone-id drone2 ...
[plan] tmux:findings_drone3 :: cd .../scripts/dev_fake_producers.py --emit=findings --drone-id drone3 ...
[plan] tmux:ws_bridge :: cd .../frontend/ws_bridge/main.py ...
```

If the drone count or scenario differs, that's a real failure of `sim/list_drones.py` against the scenario file — investigate before proceeding.

- [ ] **Step 4: Commit**

```bash
git add scripts/run_hybrid_demo.sh
git commit -m "scripts: add run_hybrid_demo.sh (real sim state + fake egs/findings)"
```

---

## Task 3.5: Dry-run regression test for the orchestrator

**Files:**
- Modify: `scripts/tests/test_launch_scripts.py`

- [ ] **Step 1: Add the new script to the syntax-check parametrize list**

In `scripts/tests/test_launch_scripts.py`, locate the `SCRIPTS = [...]` list (around line 29) and add the new orchestrator:

```python
SCRIPTS = [
    SCRIPTS_DIR / "launch_swarm.sh",
    SCRIPTS_DIR / "stop_demo.sh",
    SCRIPTS_DIR / "run_full_demo.sh",
    SCRIPTS_DIR / "run_resilience_scenario.sh",
    SCRIPTS_DIR / "run_hybrid_demo.sh",
]
```

This wires `run_hybrid_demo.sh` into `test_script_passes_bash_syntax_check` for free.

- [ ] **Step 2: Add three behavioral dry-run tests**

Append to `scripts/tests/test_launch_scripts.py`:

```python
def test_run_hybrid_demo_dry_run_default_includes_fakes_and_sim():
    """Default hybrid mode: real sim windows + 1 fake egs + N fake findings."""
    script = SCRIPTS_DIR / "run_hybrid_demo.sh"
    result = subprocess.run(
        ["bash", str(script), "--dry-run", "disaster_zone_v1"],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    assert result.returncode == 0, f"dry-run failed: stderr={result.stderr}"
    out = result.stdout
    # Real sim owns drone state.
    assert "waypoint_runner.py" in out
    assert "frame_server.py" in out
    # Default fakes.
    assert "tmux:egs_fake" in out
    assert "--emit=egs" in out
    # disaster_zone_v1 declares drone1, drone2, drone3.
    for did in ("drone1", "drone2", "drone3"):
        assert f"tmux:findings_{did}" in out, f"missing findings window for {did}"
        assert f"--drone-id {did}" in out
    # Bridge.
    assert "frontend/ws_bridge/main.py" in out


def test_run_hybrid_demo_dry_run_no_fake_egs_skips_egs_window():
    script = SCRIPTS_DIR / "run_hybrid_demo.sh"
    result = subprocess.run(
        ["bash", str(script), "--dry-run", "disaster_zone_v1", "--no-fake-egs"],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    assert result.returncode == 0, f"dry-run failed: stderr={result.stderr}"
    out = result.stdout
    assert "tmux:egs_fake" not in out
    assert "[skip] egs_fake" in out
    # Findings still on by default.
    assert "tmux:findings_drone1" in out


def test_run_hybrid_demo_dry_run_no_fake_findings_skips_all_findings_windows():
    script = SCRIPTS_DIR / "run_hybrid_demo.sh"
    result = subprocess.run(
        ["bash", str(script), "--dry-run", "disaster_zone_v1", "--no-fake-findings"],
        capture_output=True,
        text=True,
        timeout=20,
        env={**os.environ, "GG_NO_TMUX": "1"},
    )
    assert result.returncode == 0, f"dry-run failed: stderr={result.stderr}"
    out = result.stdout
    for did in ("drone1", "drone2", "drone3"):
        assert f"tmux:findings_{did}" not in out, f"unexpected findings window for {did}"
    assert "[skip] findings_*" in out
    # EGS still on by default.
    assert "tmux:egs_fake" in out
```

- [ ] **Step 3: Run the new tests to verify they pass**

Run:
```bash
PYTHONPATH=. uv run --extra dev pytest scripts/tests/test_launch_scripts.py -v -k "hybrid or syntax_check"
```

Expected: 4 tests pass — bash syntax check (all five scripts incl. the new one) + the three new dry-run tests.

- [ ] **Step 4: Commit**

```bash
git add scripts/tests/test_launch_scripts.py
git commit -m "tests: pin run_hybrid_demo.sh dry-run output and flag opt-outs"
```

---

## Task 4: WS smoke verifier

**Files:**
- Create: `scripts/check_hybrid_demo.py`

- [ ] **Step 1: Implement the smoke verifier**

Create `scripts/check_hybrid_demo.py`:

```python
"""Smoke verifier for the bridge cutover hybrid demo.

Connects to ws://localhost:9090/ (the bridge) and asserts that within the
deadline, a state_update envelope arrives whose drones[] covers every
drone_id from the named scenario AND whose findings[] is non-empty.

Usage:
    python scripts/check_hybrid_demo.py disaster_zone_v1
    python scripts/check_hybrid_demo.py disaster_zone_v1 --deadline-s 30

Exit codes:
    0  — envelope satisfied both invariants within the deadline
    1  — deadline elapsed without satisfying both invariants
    2  — connection / protocol error (bridge not running, etc.)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import List, Set

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sim.list_drones import list_drone_ids  # noqa: E402

import httpx  # noqa: E402
from httpx_ws import aconnect_ws  # noqa: E402


async def _verify(scenario: str, ws_url: str, deadline_s: float) -> int:
    expected: Set[str] = set(list_drone_ids(scenario))
    if not expected:
        print(f"[check] scenario {scenario!r} has no drones declared", file=sys.stderr)
        return 2
    print(f"[check] expecting drones={sorted(expected)} from scenario={scenario}")
    print(f"[check] connecting to {ws_url} (deadline {deadline_s:.0f}s)")

    deadline = time.monotonic() + deadline_s
    try:
        async with httpx.AsyncClient() as http_client:
            async with aconnect_ws(ws_url, http_client) as ws:
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    try:
                        raw = await asyncio.wait_for(
                            ws.receive_text(), timeout=remaining,
                        )
                    except asyncio.TimeoutError:
                        break
                    try:
                        env = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(env, dict):
                        continue
                    if env.get("type") != "state_update":
                        continue
                    drones: List[dict] = env.get("drones", []) or []
                    findings: List[dict] = env.get("findings", []) or []
                    seen = {d.get("drone_id") for d in drones if d.get("drone_id")}
                    missing = expected - seen
                    if missing:
                        continue
                    if not findings:
                        continue
                    print(
                        f"[check] PASS — drones={sorted(seen)} "
                        f"findings_count={len(findings)}"
                    )
                    return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[check] connection error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"[check] FAIL — deadline {deadline_s:.0f}s elapsed without "
          f"satisfying invariants (expected drones={sorted(expected)} + "
          f"findings_count > 0)", file=sys.stderr)
    return 1


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", help="Scenario id or path (same forms as launch_swarm.sh)")
    parser.add_argument("--ws-url", default="ws://localhost:9090/")
    parser.add_argument("--deadline-s", type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_verify(args.scenario, args.ws_url, args.deadline_s))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run a syntax/import check**

Run:
```bash
PYTHONPATH=. uv run --extra ws_bridge --extra dev python -c "import scripts.check_hybrid_demo"
```

Expected: no output (clean import).

- [ ] **Step 3: Commit**

```bash
git add scripts/check_hybrid_demo.py
git commit -m "scripts: add check_hybrid_demo.py (WS envelope smoke verifier)"
```

---

## Task 5: End-to-end smoke verification

**Files:** none (manual verification)

This task is human-driven — it confirms the wiring works end-to-end against real Redis. Do not skip; the previous tasks only prove the parts in isolation.

- [ ] **Step 1: Stop any prior demo, start hybrid demo**

Run (in a terminal):
```bash
scripts/stop_demo.sh 2>/dev/null || true
scripts/run_hybrid_demo.sh disaster_zone_v1 --duration=120
```

Expected: tmux session `hybrid_demo` starts; `tmux attach -t hybrid_demo` shows windows for waypoint, frames, egs_fake, findings_drone1, findings_drone2, findings_drone3, ws_bridge.

- [ ] **Step 2: Verify each window is healthy (≤30 s after launch)**

Run:
```bash
sleep 8
tail -n 5 /tmp/gemma_guardian_logs/waypoint_runner.log
tail -n 5 /tmp/gemma_guardian_logs/egs_fake.log
tail -n 5 /tmp/gemma_guardian_logs/findings_drone1.log 2>/dev/null \
  || tail -n 5 /tmp/gemma_guardian_logs/findings_drone1_fake.log
tail -n 5 /tmp/gemma_guardian_logs/ws_bridge.log
```

Expected:
- waypoint log: lines containing `drones.drone1.state`, `drones.drone2.state`, `drones.drone3.state`
- egs_fake log: lines containing `[fake_producer] tick=... channel=egs.state`
- findings_drone1 log: lines containing `[fake_producer] ... channel=drones.drone1.findings`
- ws_bridge log: NO lines containing `STRUCTURAL_VALIDATION_FAILED`

If any of those expectations is missed, stop and investigate before claiming the cutover is done.

- [ ] **Step 3: Run the smoke verifier**

Run:
```bash
PYTHONPATH=. uv run --extra ws_bridge --extra dev \
  python scripts/check_hybrid_demo.py disaster_zone_v1 --deadline-s 20
```

Expected: exit code 0 with output:
```
[check] expecting drones=['drone1', 'drone2', 'drone3'] from scenario=disaster_zone_v1
[check] connecting to ws://localhost:9090/ (deadline 20s)
[check] PASS — drones=['drone1', 'drone2', 'drone3'] findings_count=...
```

If exit code is 1 (deadline elapsed), inspect the bridge log for validation failures and the egs_fake/findings logs for publish errors. The most likely failure mode is the scenario advertising drone IDs that aren't getting state — confirm sim is actually publishing for every drone.

- [ ] **Step 4: Tear down**

Run:
```bash
scripts/stop_demo.sh
tmux kill-session -t hybrid_demo 2>/dev/null || true
```

Expected: no live `hybrid_demo` tmux session; Redis stays running (system-managed) or is shut down cleanly (sentinel-managed).

- [ ] **Step 5: Commit a runbook note (no code)**

There is no commit at this step — this is a manual verification gate. If all four prior steps passed, proceed to Task 6. If any failed, fix the underlying issue and rerun this task before continuing.

---

## Task 6: Update TODOS.md

**Files:**
- Modify: `TODOS.md`

- [ ] **Step 1: Read the current state of TODOS.md to find the cutover entry**

Run:
```bash
grep -n -i "cutover\|dev_fake_producers" TODOS.md || echo "(no entry — add a CLOSED note instead)"
```

Expected: either a line number for the existing cutover TODO (rare — Hazim's roadmap was the source of truth) or no match (likely — the cutover was tracked in `sim/ROADMAP.md`, not `TODOS.md`).

- [ ] **Step 2: Add a CLOSED entry at the top of the "Phase 4+" section**

Open `TODOS.md`. Locate the heading `## Phase 4+ (post-Dashboard MVP)`. Insert immediately below it:

```markdown
### CLOSED — Bridge cutover from `dev_fake_producers.py` to real sim (hybrid mode)
- **Resolution:** Shipped `scripts/run_hybrid_demo.sh` orchestrator + `--emit` flag on `dev_fake_producers.py`. Real sim now owns `drones.<id>.state`; fake producer remains the source for `egs.state` and `drones.<id>.findings` until Qasim's EGS aligns `zone_polygon` to the scenario YAML and Kaleel's drone agent publishes findings to Redis.
- **Migration path:** When Qasim ships, delete the EGS_FAKE block in `scripts/run_hybrid_demo.sh`. When Kaleel ships, delete the FINDINGS_FAKE loop. Both are flagged in source comments.
- **Verification:** `scripts/check_hybrid_demo.py disaster_zone_v1 --deadline-s 20` passes against a freshly-launched hybrid stack (3-drone scenario, fake findings present).
- **Owner:** Person 4 (closed by this PR).
```

- [ ] **Step 3: Commit**

```bash
git add TODOS.md
git commit -m "TODOS: close bridge cutover entry (hybrid mode shipped)"
```

---

## Task 7: Open PR

**Files:** none (gh + git only)

- [ ] **Step 1: Push and open**

Run:
```bash
git push -u origin feature/bridge-cutover-hybrid
gh pr create --title "Bridge cutover: hybrid mode (real sim state + fake egs/findings)" --body "$(cat <<'EOF'
## Summary
- Adds `--emit=<csv>` flag to `scripts/dev_fake_producers.py` so each instance can be scoped to a subset of channels (`state`, `egs`, `findings`).
- Adds `scripts/run_hybrid_demo.sh` orchestrator with `--no-fake-egs` / `--no-fake-findings` opt-outs: real sim publishes `drones.<id>.state`; fake producers fill `egs.state` + per-drone `findings` by default until Qasim and Kaleel ship.
- Adds `scripts/check_hybrid_demo.py` WS smoke verifier (asserts envelope contains every scenario drone + ≥1 finding within a deadline).
- Pins `run_hybrid_demo.sh --dry-run` output via `scripts/tests/test_launch_scripts.py`.

## Migration path
- When Qasim's `agents/egs_agent/main.py` aligns `zone_polygon` to the scenario YAML, pass `--no-fake-egs` to `run_hybrid_demo.sh` (or set it in whichever wrapper script invokes hybrid mode). No source edits.
- When Kaleel's drone agent publishes findings to Redis, pass `--no-fake-findings`. Same shape.
- Both flags default OFF (fakes ON), so today's behavior is unchanged. Reversible at runtime.

## Test plan
- [ ] `pytest scripts/tests/test_dev_fake_producers.py -v` — 7/7 pass (3 parser + 4 emission gating, including the `egs,findings` hybrid combo)
- [ ] `pytest scripts/tests/test_launch_scripts.py -v -k hybrid` — 3/3 pass (default + --no-fake-egs + --no-fake-findings)
- [ ] `pytest scripts/tests/test_launch_scripts.py -v -k syntax_check` — 5/5 pass (incl. new `run_hybrid_demo.sh`)
- [ ] `scripts/run_hybrid_demo.sh disaster_zone_v1 --duration=120` plus `python scripts/check_hybrid_demo.py disaster_zone_v1 --deadline-s 20` exits 0
- [ ] `tail -n 50 /tmp/gemma_guardian_logs/ws_bridge.log` shows no `STRUCTURAL_VALIDATION_FAILED` lines during the smoke run

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed. Capture it for the standup.

---

## Self-Review Notes

**Spec coverage:**
- ✅ `--emit` flag with TDD (incl. hybrid combo test): Tasks 1–2.
- ✅ Hybrid orchestrator with opt-out flags: Task 3.
- ✅ Dry-run pytest pinning + bash syntax check: Task 3.5.
- ✅ Smoke verifier: Task 4.
- ✅ End-to-end verification: Task 5.
- ✅ TODOS hygiene: Task 6.
- ✅ PR: Task 7.

**Type consistency:**
- `--emit` token list (`state`, `egs`, `findings`) is defined once in `_EMIT_CHANNEL_TOKENS` and consumed by `_parse_emit_csv`, the parser default, and `_run`'s gating booleans. No drift across tasks.
- `list_drone_ids(scenario)` is the single helper used by `launch_swarm.sh`, `run_hybrid_demo.sh`, and `check_hybrid_demo.py` — no parallel parsing logic.
- `--no-fake-egs` / `--no-fake-findings` flag names are mirrored in: bash arg parsing, the `[skip]` log lines, the dry-run pytest assertions, the PR test plan, and the migration path note. One name, five surfaces.

**Out-of-scope (intentionally deferred):**
- Multi-drone Playwright extension — separate TODO entry, depends on this cutover landing.
- Static aerial base image — orthogonal, blocked on Thayyil.
- Real EGS / drone-agent integrations — those are Qasim and Kaleel's PRs; this plan only tightens the seams so their flips are a single CLI flag (`--no-fake-egs` / `--no-fake-findings`).
- `egs.command_translations` channel: not part of this cutover. `dev_command_translator.py` continues to handle the translation path until Qasim's EGS implements it. Documented in `docs/11-prompt-templates.md`.
- Roster-mismatch defensive assertion in `check_hybrid_demo.py` (verify `findings[].source_drone_id ⊆ scenario drones`) — low value because the orchestrator pulls roster from the same `list_drones.py`, so mismatch can only arise from a manual misuse.

---

## Completion Summary

- Step 0: Scope Challenge — scope accepted as-is (5 files, 0 new classes, below complexity threshold)
- Architecture Review: 1 issue found, 1 resolved (1A: comment-based migration → opt-out flags)
- Code Quality Review: 0 issues found
- Test Review: 4 gaps identified, 2 closed in plan (3A: hybrid combo test, 3B: dry-run pytest), 2 deferred (state-only emission test = redundant; `check_hybrid_demo.py` unit test = low ROI for a manual tool)
- Performance Review: N/A (dev tooling)
- NOT in scope: written
- What already exists: written
- TODOS.md updates: 0 new (this plan closes the only candidate TODO — the cutover itself)
- Failure modes: 0 critical gaps flagged
- Outside voice: not run
- Parallelization: Sequential implementation, no parallelization opportunity (all tasks share `scripts/`)
- Lake Score: 3/3 recommendations chose complete option

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 1 arch issue + 2 test gaps, all resolved |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — ready to implement.
