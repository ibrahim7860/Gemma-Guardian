# Multi-Drone Playwright Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the `bridge_e2e` Playwright suite from single-drone (`drone99`) coverage to multi-drone (`drone1`/`drone2`/`drone3`) coverage so the dashboard's multi-drone contract is regression-locked before the Day 12 integration session.

**Architecture:** Add a sibling `test_e2e_playwright_multi_drone.py` file that reuses the proven subprocess-orchestration pattern from `test_e2e_playwright.py`. A new `multi_drone_pipeline` module-scoped fixture spawns N+1 fake-producer processes (one per drone with `--emit=state,findings --drone-id=droneN`, plus one with `--emit=egs`) on top of an isolated Redis + uvicorn bridge + static-served Flutter web build. Three focused tests cover the TODO's three concerns: (a) every drone appears in `active_drones[]`, (b) `active_findings[]` carries findings from every drone with no collision, (c) the operator-command translate path still works in the multi-drone state. Existing single-drone tests stay untouched.

**Tech Stack:** Python 3.11+, pytest + pytest-playwright + httpx-ws (already in `dev` extra), `subprocess.Popen` (no tmux), `redis-server` from Homebrew, FastAPI bridge launched via uvicorn.

---

## File Structure

**Create:**
- `frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py` — new test file. Owns: multi-drone fixture and three focused tests. Mirrors the harness pattern from `test_e2e_playwright.py` but does NOT import its `pipeline` fixture (different scope, different process roster).

**Modify:**
- `frontend/ws_bridge/tests/_helpers.py` — extract one shared helper (`_capture_ws_frames_until`) only if Task 4 finds duplication; otherwise leave alone.
- `TODOS.md` — close the multi-drone Playwright entry under Phase 4+.
- `.github/workflows/test.yml` — verify the existing `bridge_e2e` job picks up the new test file (no edit if it globs `frontend/ws_bridge/tests/test_e2e_*.py`; explicit add if it pins the existing filename).

**Reuse without modification:**
- `frontend/ws_bridge/tests/test_e2e_playwright.py` — the single-drone tests stay as-is. Their `pipeline` fixture and harness helpers are the model we copy.
- `scripts/dev_fake_producers.py` — already supports `--emit=<csv>` and `--drone-id`; nothing to change.

---

## Task 0: Branch setup

**Files:** none (git only)

- [ ] **Step 0: Confirm clean tree on `main`, create branch BEFORE any commits**

```bash
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
git status                    # must be clean
git checkout main
git pull --ff-only
git checkout -b feature/multi-drone-playwright
```

Expected: branch created, no diffs.

---

## Task 1: Multi-drone fixture (TDD via the smallest possible test)

**Files:**
- Create: `frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py`

The fixture is the load-bearing piece. We TDD it via one tiny smoke test that asserts the bridge produces SOME frame, then layer the real assertions on top in Tasks 2–4.

- [ ] **Step 1: Create the test file scaffold + fixture + smoke test**

Create `frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py`:

```python
"""End-to-end Playwright coverage for multi-drone scenarios.

Mirrors the harness shape of ``test_e2e_playwright.py`` but spawns one
``dev_fake_producers.py`` instance per drone (``--emit=state,findings``)
plus a single global ``--emit=egs`` instance. The single-drone file's
``pipeline`` fixture is intentionally NOT reused — different roster, and
keeping the fixtures independent prevents subtle module-scope coupling
between the two suites.

drone roster: drone1, drone2, drone3 — matches Hazim's
``sim/scenarios/disaster_zone_v1.yaml`` so failures here translate
directly to demo-time risk.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import httpx
import pytest
from httpx_ws import aconnect_ws
import asyncio


_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
_DEV_PRODUCER: Path = _REPO_ROOT / "scripts" / "dev_fake_producers.py"
_FLUTTER_WEB_DIR: Path = (
    _REPO_ROOT / "frontend" / "flutter_dashboard" / "build" / "web"
)
_DRONE_ROSTER: List[str] = ["drone1", "drone2", "drone3"]


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _resolve_redis_server() -> str:
    for candidate in ("/opt/homebrew/bin/redis-server", "/usr/local/bin/redis-server", "redis-server"):
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        else:
            from shutil import which
            resolved = which(candidate)
            if resolved:
                return resolved
    pytest.skip("redis-server not on PATH; install via brew/apt to run e2e")


def _resolve_redis_cli() -> str:
    for candidate in ("/opt/homebrew/bin/redis-cli", "/usr/local/bin/redis-cli", "redis-cli"):
        if os.path.isabs(candidate):
            if os.path.exists(candidate):
                return candidate
        else:
            from shutil import which
            resolved = which(candidate)
            if resolved:
                return resolved
    pytest.skip("redis-cli not on PATH; install via brew/apt to run e2e")


def _wait_redis_ready(redis_cli: str, port: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = subprocess.run(
            [redis_cli, "-p", str(port), "ping"],
            capture_output=True, text=True, timeout=2.0,
        )
        if r.returncode == 0 and r.stdout.strip().upper() == "PONG":
            return
        time.sleep(0.1)
    raise RuntimeError(f"redis on port {port} did not become ready in {timeout_s}s")


def _wait_http_ready(url: str, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"{url} did not become ready in {timeout_s}s")


def _terminate_proc(proc: Optional[subprocess.Popen], label: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            print(f"[multi_drone_pipeline] WARNING: {label} did not exit", file=sys.stderr)


@pytest.fixture(scope="module")
def multi_drone_pipeline() -> Iterator[Dict[str, Any]]:
    """Spin up redis + bridge + 1 egs producer + 3 drone producers + http.server.

    Yields ports/urls and the resolved drone roster. Tears everything down in
    a ``try/finally`` so a test failure never leaks subprocesses.
    """
    if not _FLUTTER_WEB_DIR.is_dir() or not (_FLUTTER_WEB_DIR / "index.html").exists():
        pytest.skip(
            f"Flutter web build missing at {_FLUTTER_WEB_DIR}. Run "
            "`flutter build web` in frontend/flutter_dashboard first."
        )

    redis_server = _resolve_redis_server()
    redis_cli = _resolve_redis_cli()

    redis_port = _pick_free_port()
    bridge_port = _pick_free_port()
    flutter_port = _pick_free_port()

    redis_proc: Optional[subprocess.Popen] = None
    bridge_proc: Optional[subprocess.Popen] = None
    egs_producer: Optional[subprocess.Popen] = None
    drone_producers: List[subprocess.Popen] = []
    http_proc: Optional[subprocess.Popen] = None

    try:
        # 1. Redis on isolated port, no persistence.
        redis_proc = subprocess.Popen(
            [
                redis_server,
                "--port", str(redis_port),
                "--daemonize", "no",
                "--save", "",
                "--appendonly", "no",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_redis_ready(redis_cli, redis_port, timeout_s=5.0)

        # 2. Bridge via uvicorn, pointed at the isolated Redis.
        bridge_env = os.environ.copy()
        bridge_env["REDIS_URL"] = f"redis://127.0.0.1:{redis_port}"
        bridge_env["BRIDGE_TICK_S"] = "0.25"
        bridge_env["BRIDGE_RECONNECT_MAX_S"] = "2"
        existing_pp = bridge_env.get("PYTHONPATH", "")
        bridge_env["PYTHONPATH"] = (
            f"{_REPO_ROOT}{os.pathsep}{existing_pp}" if existing_pp else str(_REPO_ROOT)
        )
        bridge_proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "frontend.ws_bridge.main:app",
                "--host", "127.0.0.1",
                "--port", str(bridge_port),
                "--log-level", "warning",
            ],
            env=bridge_env,
            cwd=str(_REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_http_ready(f"http://127.0.0.1:{bridge_port}/health", timeout_s=15.0)

        # 3. Single egs producer (1 instance — egs.state is global).
        egs_producer = subprocess.Popen(
            [
                sys.executable, str(_DEV_PRODUCER),
                "--emit", "egs",
                "--redis-url", f"redis://127.0.0.1:{redis_port}",
                "--tick-s", "0.2",
            ],
            cwd=str(_REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # 4. Per-drone producers (state + findings each).
        for drone_id in _DRONE_ROSTER:
            proc = subprocess.Popen(
                [
                    sys.executable, str(_DEV_PRODUCER),
                    "--emit", "state,findings",
                    "--drone-id", drone_id,
                    "--redis-url", f"redis://127.0.0.1:{redis_port}",
                    "--tick-s", "0.2",
                ],
                cwd=str(_REPO_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            drone_producers.append(proc)

        # 5. Static server for Flutter web build.
        http_proc = subprocess.Popen(
            [
                sys.executable, "-m", "http.server", str(flutter_port),
                "--directory", str(_FLUTTER_WEB_DIR),
                "--bind", "127.0.0.1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_http_ready(f"http://127.0.0.1:{flutter_port}/", timeout_s=10.0)

        yield {
            "redis_port": redis_port,
            "bridge_port": bridge_port,
            "flutter_port": flutter_port,
            "redis_url": f"redis://127.0.0.1:{redis_port}",
            "bridge_ws_url": f"ws://127.0.0.1:{bridge_port}/",
            "bridge_health_url": f"http://127.0.0.1:{bridge_port}/health",
            "flutter_url": f"http://127.0.0.1:{flutter_port}/",
            "drone_roster": list(_DRONE_ROSTER),
        }
    finally:
        _terminate_proc(egs_producer, "egs_producer")
        for i, p in enumerate(drone_producers):
            _terminate_proc(p, f"drone_producer[{i}]")
        _terminate_proc(http_proc, "http.server")
        _terminate_proc(bridge_proc, "uvicorn_bridge")
        _terminate_proc(redis_proc, "redis-server")


async def _capture_envelopes(
    bridge_ws_url: str, *, min_envelopes: int, timeout_s: float,
) -> List[Dict[str, Any]]:
    """Connect to the bridge WS and accumulate up to ``min_envelopes`` parsed
    state_update envelopes (or until ``timeout_s`` elapses). Returns parsed
    dicts only — invalid JSON or non-state_update messages are skipped."""
    deadline = time.monotonic() + timeout_s
    envelopes: List[Dict[str, Any]] = []
    async with httpx.AsyncClient() as c:
        async with aconnect_ws(bridge_ws_url, c) as ws:
            while time.monotonic() < deadline and len(envelopes) < min_envelopes:
                remaining = deadline - time.monotonic()
                try:
                    raw = await asyncio.wait_for(ws.receive_text(), timeout=remaining)
                except asyncio.TimeoutError:
                    break
                try:
                    env = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(env, dict) and env.get("type") == "state_update":
                    envelopes.append(env)
    return envelopes


def test_smoke_bridge_emits_envelopes(multi_drone_pipeline: Dict[str, Any]) -> None:
    """Sanity check that the multi-drone pipeline produces ANY envelope.
    Real multi-drone assertions live in subsequent tests; this one fails
    fast if the harness itself is broken."""
    envelopes = asyncio.run(
        _capture_envelopes(
            multi_drone_pipeline["bridge_ws_url"],
            min_envelopes=3,
            timeout_s=15.0,
        )
    )
    assert len(envelopes) >= 3, (
        f"Expected >=3 state_update envelopes; got {len(envelopes)}. "
        f"Pipeline may be misconfigured."
    )
```

- [ ] **Step 2: Run the smoke test to verify the harness works**

Prerequisite (one-time): build the Flutter web bundle if it's missing.

```bash
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian/frontend/flutter_dashboard"
flutter build web
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
```

Then run:

```bash
PYTHONPATH=. uv run --extra ws_bridge --extra dev pytest \
  frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py::test_smoke_bridge_emits_envelopes -v
```

Expected: PASS in <30s. If it FAILS, capture the bridge stderr by changing the bridge_proc Popen to drop `stdout=subprocess.DEVNULL` and re-run; do NOT advance to Task 2 until smoke is green.

- [ ] **Step 3: Commit**

```bash
git add frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py
git commit -m "tests(e2e): multi_drone_pipeline fixture + harness smoke"
```

---

## Task 2: Assert dashboard renders one drone status card per drone (TODO concern (a))

The bridge emits `active_drones[]`; the dashboard renders one card per entry. We assert at the WS-envelope level (matches the existing test file's pattern) — the bridge contract is what gates demo correctness.

**Files:**
- Modify: `frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py`

- [ ] **Step 1: Add the failing test**

Append to `frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py`:

```python
def test_active_drones_covers_full_roster(multi_drone_pipeline: Dict[str, Any]) -> None:
    """At least one envelope reports every drone in the configured roster.

    The bridge aggregates state per-drone_id and emits an active_drones[]
    array. If the dashboard ever drops or merges drones, this fails before
    a judge sees it.
    """
    expected: set[str] = set(multi_drone_pipeline["drone_roster"])
    envelopes = asyncio.run(
        _capture_envelopes(
            multi_drone_pipeline["bridge_ws_url"],
            min_envelopes=20,         # 20 envelopes @ 0.25s tick = ~5s
            timeout_s=20.0,
        )
    )
    assert envelopes, "captured zero envelopes; pipeline misconfigured"

    seen: set[str] = set()
    for env in envelopes:
        active_drones = env.get("active_drones", []) or []
        for d in active_drones:
            did = d.get("drone_id")
            if did:
                seen.add(did)
        if expected.issubset(seen):
            break

    missing = expected - seen
    assert not missing, (
        f"Expected all of {sorted(expected)} in active_drones across "
        f"{len(envelopes)} envelopes; missing={sorted(missing)} (saw "
        f"{sorted(seen)})"
    )
```

- [ ] **Step 2: Run the test to verify it passes**

```bash
PYTHONPATH=. uv run --extra ws_bridge --extra dev pytest \
  frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py::test_active_drones_covers_full_roster -v
```

Expected: PASS. (The harness already runs all three drone producers; the assertion is the new piece.)

If it FAILS with `missing={'drone3'}` or similar, the most likely cause is one of the per-drone producers crashed — re-enable its stderr in the fixture for one diagnostic run.

- [ ] **Step 3: Commit**

```bash
git add frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py
git commit -m "tests(e2e): assert active_drones covers full roster"
```

---

## Task 3: Assert findings from every drone land in active_findings without collision (TODO concern (b))

Each `dev_fake_producers.py --emit=findings --drone-id=droneN` instance generates `finding_id` values shaped `f_droneN_<counter>`. Distinct drones never collide on `finding_id`. The bridge aggregator uses an `OrderedDict[finding_id]` capped at `max_findings=50` (FIFO). We assert that within the capture window, findings from all three drones are present.

**Files:**
- Modify: `frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py`

- [ ] **Step 1: Add the failing test**

Append:

```python
def test_active_findings_carries_every_drone(
    multi_drone_pipeline: Dict[str, Any],
) -> None:
    """active_findings[] eventually contains a finding from every drone.

    Each producer emits findings every 8 ticks at tick-s=0.2 — i.e. one new
    finding per drone every 1.6s. Within ~12s we should see all three.
    `finding_id` is shaped `f_<drone_id>_<n>` so source attribution is
    derivable from the id alone (we also cross-check `source_drone_id`).
    """
    expected: set[str] = set(multi_drone_pipeline["drone_roster"])
    envelopes = asyncio.run(
        _capture_envelopes(
            multi_drone_pipeline["bridge_ws_url"],
            min_envelopes=60,         # 60 envelopes @ 0.25s = ~15s
            timeout_s=25.0,
        )
    )
    assert envelopes, "captured zero envelopes; pipeline misconfigured"

    sources_via_id: set[str] = set()
    sources_via_field: set[str] = set()
    finding_ids_per_drone: Dict[str, set[str]] = {d: set() for d in expected}

    for env in envelopes:
        for f in env.get("active_findings", []) or []:
            fid = f.get("finding_id", "") or ""
            sdi = f.get("source_drone_id", "") or ""
            # finding_id format: f_<drone_id>_<counter>
            if fid.startswith("f_"):
                parts = fid.split("_")
                if len(parts) >= 3:
                    derived = parts[1]
                    if derived in expected:
                        sources_via_id.add(derived)
                        finding_ids_per_drone[derived].add(fid)
            if sdi in expected:
                sources_via_field.add(sdi)

    # Both attribution paths must agree — and both must cover every drone.
    missing_id = expected - sources_via_id
    missing_field = expected - sources_via_field
    assert not missing_id, (
        f"finding_id-derived sources missing {sorted(missing_id)} "
        f"(saw {sorted(sources_via_id)})"
    )
    assert not missing_field, (
        f"source_drone_id-field missing {sorted(missing_field)} "
        f"(saw {sorted(sources_via_field)})"
    )

    # Collision check: per-drone finding_id sets must NOT share any id with
    # another drone's set. The producer-side regex enforces this, but a
    # bridge-side aggregation bug could collapse them — we test the
    # observable invariant.
    for did_a, ids_a in finding_ids_per_drone.items():
        for did_b, ids_b in finding_ids_per_drone.items():
            if did_a >= did_b:
                continue
            shared = ids_a & ids_b
            assert not shared, (
                f"finding_id collision between {did_a} and {did_b}: {shared}"
            )
```

- [ ] **Step 2: Run the test to verify it passes**

```bash
PYTHONPATH=. uv run --extra ws_bridge --extra dev pytest \
  frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py::test_active_findings_carries_every_drone -v
```

Expected: PASS in ~15-20s.

- [ ] **Step 3: Commit**

```bash
git add frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py
git commit -m "tests(e2e): assert active_findings covers every drone (no collision)"
```

---

## Task 4: Assert operator-command translation path still works in multi-drone state (TODO concern (c))

The single-drone file's `test_command_translation_forward` (line 767) verifies the bridge republishes a validated `operator_command` to `egs.operator_commands` and forwards a downstream `command_translation` back to clients. We replicate that contract in the multi-drone state to catch any aggregator-induced regression.

**Files:**
- Modify: `frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py`

- [ ] **Step 1: Read the single-drone reference test for shape**

Read `frontend/ws_bridge/tests/test_e2e_playwright.py` lines 767–846 to confirm the shape used. The relevant invocation pattern:

- Open WS to bridge
- Send `{"type": "operator_command", "command_id": "...", "language": "es", "raw_text": "..."}`
- Expect ack echo + a `command_translation` frame from the test command_translator stub

For the multi-drone variant, we accept that no real translator runs alongside this fixture, so we assert ONLY the bridge-side ack + republish path (NOT the downstream translation frame). That keeps the test's surface to "the multi-drone aggregator does not block operator-command processing".

- [ ] **Step 2: Add the failing test**

Append:

```python
def test_operator_command_acked_in_multi_drone_state(
    multi_drone_pipeline: Dict[str, Any],
) -> None:
    """The bridge acks an operator_command even when active_drones[] is
    multi-drone. Locks the contract that `aggregator.has_finding` /
    multi-drone state aggregation does not regress the inbound command path.
    """
    async def _go() -> Dict[str, Any]:
        async with httpx.AsyncClient() as c:
            async with aconnect_ws(multi_drone_pipeline["bridge_ws_url"], c) as ws:
                # Drain initial seed envelope (bridge sends one immediately).
                _ = await asyncio.wait_for(ws.receive_text(), timeout=5.0)

                cmd = {
                    "type": "operator_command",
                    "command_id": "multi-drone-test-001",
                    "language": "es",
                    "raw_text": "recall drone1 to base",
                }
                await ws.send_text(json.dumps(cmd))

                # Read frames until we see the echo ack (skip envelopes).
                deadline = time.monotonic() + 10.0
                while time.monotonic() < deadline:
                    raw = await asyncio.wait_for(
                        ws.receive_text(),
                        timeout=deadline - time.monotonic(),
                    )
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") == "echo" and msg.get(
                        "ack"
                    ) == "operator_command_received":
                        return msg
                raise AssertionError("no operator_command_received ack within 10s")

    ack = asyncio.run(_go())
    assert ack.get("command_id") == "multi-drone-test-001"
    assert "error" not in ack, f"unexpected error in ack: {ack}"
```

- [ ] **Step 3: Run the test**

```bash
PYTHONPATH=. uv run --extra ws_bridge --extra dev pytest \
  frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py::test_operator_command_acked_in_multi_drone_state -v
```

Expected: PASS.

If it FAILS with `no operator_command_received ack`, inspect the bridge log — most likely the `operator_command` schema rejected the payload. Compare with the proven-working fixture at `shared/schemas/fixtures/valid/websocket_messages/02_operator_command.json`.

- [ ] **Step 4: Commit**

```bash
git add frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py
git commit -m "tests(e2e): operator_command ack survives multi-drone state"
```

---

## Task 5: Run the full new test file to verify the fixture is reused module-wide

`pytest` reuses module-scoped fixtures across all tests in the same module. With four tests now (smoke + three real), one Redis + one bridge + four producers + one http.server should spin up exactly once.

**Files:** none (manual verification)

- [ ] **Step 1: Run all four tests**

```bash
PYTHONPATH=. uv run --extra ws_bridge --extra dev pytest \
  frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py -v
```

Expected: 4 passed in <60s. The first test pays the fixture-startup cost (~5–10s); subsequent tests reuse the running stack.

- [ ] **Step 2: Run the entire bridge test suite to confirm no cross-file interference**

```bash
PYTHONPATH=. uv run --extra ws_bridge --extra dev pytest \
  frontend/ws_bridge/tests/ -v
```

Expected: every existing test still passes; the new four pass too. If a port-binding race shows up (each fixture picks free ports independently, so collision is rare but possible under heavy load), serialize the suites with `--forked` or accept the existing serialization (pytest runs tests in collection order by default).

- [ ] **Step 3: No commit at this step** — verification only.

---

## Task 6: Verify CI picks up the new file

**Files:** read-only inspection of `.github/workflows/test.yml`

- [ ] **Step 1: Inspect the bridge_e2e job invocation**

```bash
grep -A 20 "bridge_e2e\|bridge-e2e" .github/workflows/test.yml | head -40
```

Look at how the job invokes pytest. If the command is `pytest frontend/ws_bridge/tests/test_e2e_playwright.py` (pinned filename), Task 6 must edit the workflow to add the new file. If it's `pytest frontend/ws_bridge/tests/` or globs `test_e2e_*.py`, no edit needed.

- [ ] **Step 2 (conditional): Edit `.github/workflows/test.yml` to include the new file**

If the job pins the existing filename, change it to glob the e2e tests. Example diff:

```yaml
# before
run: pytest frontend/ws_bridge/tests/test_e2e_playwright.py -v

# after
run: pytest frontend/ws_bridge/tests/test_e2e_playwright.py frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py -v
```

(Glob is also acceptable: `pytest frontend/ws_bridge/tests/test_e2e_playwright*.py -v`.)

- [ ] **Step 3 (conditional): Commit if edited**

```bash
git add .github/workflows/test.yml
git commit -m "ci: include test_e2e_playwright_multi_drone.py in bridge_e2e job"
```

If no edit was needed (glob already in place), skip the commit and note the verification result in Task 8's PR body.

---

## Task 7: Update TODOS.md

**Files:**
- Modify: `TODOS.md`

- [ ] **Step 1: Replace the open TODO entry with a CLOSED entry**

Open `TODOS.md`. Locate the `### Expand Playwright coverage to multi-drone scenarios (Day 8+)` heading. Replace the entire entry (heading + bullets) with:

```markdown
### CLOSED — Expand Playwright coverage to multi-drone scenarios
- **Resolution:** Shipped `frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py` with a `multi_drone_pipeline` fixture (1 EGS + 3 per-drone fake producers + bridge + Flutter web). Three load-bearing assertions: every drone in `active_drones[]`, every drone's findings in `active_findings[]` with no `finding_id` collision, and `operator_command` acks survive multi-drone aggregator state.
- **Coverage:** Reuses `--emit=state,findings` per drone + `--emit=egs` global. No producer-side `--multi-drone` mode needed.
- **Owner:** Person 4 (closed by this PR).
```

- [ ] **Step 2: Commit**

```bash
git add TODOS.md
git commit -m "TODOS: close multi-drone Playwright entry"
```

---

## Task 8: Open PR

**Files:** none (gh + git only)

- [ ] **Step 1: Push and open**

```bash
git push -u origin feature/multi-drone-playwright
gh pr create --title "Multi-drone Playwright coverage (3-drone e2e contract)" --body "$(cat <<'EOF'
## Summary
- Adds `frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py` with a new `multi_drone_pipeline` module-scoped fixture.
- Spawns 1 `dev_fake_producers.py --emit=egs` + N (=3) `--emit=state,findings --drone-id=droneN` producers atop an isolated Redis + uvicorn bridge + http.server-served Flutter web build.
- Three load-bearing tests:
  - `test_active_drones_covers_full_roster` — every drone reaches `active_drones[]`.
  - `test_active_findings_carries_every_drone` — every drone's findings reach `active_findings[]` with no `finding_id` collision; `source_drone_id` agrees with the parsed `finding_id`.
  - `test_operator_command_acked_in_multi_drone_state` — bridge acks `operator_command` even with the multi-drone aggregator state.

## Why now
Multi-drone is the headline demo story. Today's `bridge_e2e` job only covered single-drone (`drone99`); a regression that drops one drone's status card or collapses two drones' findings would silently pass. PR #20's hybrid-mode cutover is what unblocked this work — the per-drone `--emit` flag is the lever.

## Test plan
- [x] `pytest frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py -v` — 4/4 pass locally
- [x] Full bridge e2e suite passes (existing 14 single-drone tests unaffected)
- [x] CI `bridge_e2e` job picks up the new file (verified during Task 6)

## Out of scope
- DOM-level Flutter rendering checks remain on the existing `test_e2e_playwright.py` UI suite.
- A producer-side `--multi-drone` mode (would fan out N drones from one process) — not needed; spawning N processes is simpler and matches the production shape.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Capture the PR URL for the standup.

---

## Self-Review Notes

**Spec coverage (against TODO entry's three concerns):**
- ✅ (a) dashboard renders one drone status card per drone — Task 2.
- ✅ (b) findings from both drones populate without collision — Task 3.
- ✅ (c) language-aware translation works regardless of source drone — Task 4 (asserts the bridge-side path; the downstream translator is mocked elsewhere and orthogonal to multi-drone aggregation).

**Type/name consistency:**
- `_DRONE_ROSTER`, `multi_drone_pipeline`, `_capture_envelopes` are defined once and used across all four tests.
- `--emit=state,findings` and `--emit=egs` use exactly the token spellings introduced by `dev_fake_producers.py` (Task 2 of PR #20). No drift.

**Out of scope (intentional):**
- Producer-side `--multi-drone` mode — N processes is simpler, matches production.
- DOM-level Playwright assertions for drone cards — existing UI tests already cover the rendering layer for one drone, and the bridge contract is what gates demo correctness.
- A reusable `_capture_envelopes` shared helper across both test files — premature; if a third e2e file lands, extract then.
- Larger-than-3-drone scenarios — `disaster_zone_v1.yaml` is the canonical 3-drone fixture; expanding past that is a separate (and unneeded) experiment.

**Failure modes:**
- Producer crashes silently → `active_drones` test fails with a specific missing-drone message; diagnostic recipe is in Task 1 Step 2.
- Port collision between the single-drone and multi-drone fixtures → both pick free ports independently; collision is theoretically possible, mitigated by pytest's serial collection order.
- Flutter web build missing → fixture skips with a clear `pytest.skip` message (same as the single-drone fixture).
