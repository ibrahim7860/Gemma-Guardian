# CI Workflow + Bridge Error-Path Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GitHub Actions CI workflow that runs the bridge test suite (per-file to sidestep the documented asyncio pollution) plus the Flutter dashboard test suite, AND fill the five missing bridge error-path tests so `bridge_internal` and `redis_publish_failed` are covered for every command branch.

**Architecture:** One new test file (`test_main_error_paths.py`) targets the two unhappy paths inside each of the three Phase 4 command branches (`operator_command`, `finding_approval`, `operator_command_dispatch`). It uses the same `httpx.AsyncClient + pytest_asyncio + httpx-ws + fakeredis` harness Phase 4 standardised on (see `test_main_operator_command_publish.py`). One new GitHub Actions workflow (`.github/workflows/test.yml`) installs Python and Flutter, runs the bridge test files individually (the documented pollution workaround in TODOS.md), runs `pytest shared/`, runs `flutter test`, and reports green/red on every push and PR.

**Tech Stack:** GitHub Actions, `actions/setup-python@v5`, `subosito/flutter-action@v2`, `pytest`, `pytest-asyncio`, `fakeredis`, `httpx-ws`.

---

## Why these two now

Phase 4 is in the bag and Day 8–9 (May 8–9) is the only realistic slack window before the multi-drone crunch. Both items came out of the `/review` skill on the 23-commit Phase 4 lane:

1. **CI** is the highest-leverage TODO because the team is about to start landing two more workstreams (Qasim's real EGS subscriber, Thayyil's drone agent) onto `main`. Without CI, regressions in the bridge contract surface as "the dashboard mysteriously broke during the demo."
2. **Error-path tests** are the highest-leverage code-quality gap because the unhappy paths in the bridge are exactly the paths a Redis hiccup or a schema drift would exercise live. They are also small (one file, ~150 lines) and test patterns already proven by the Phase 4 harness.

The third `/review` recommendation (DRY refactor of the three near-identical bridge command branches) is explicitly NOT in scope here. A refactor needs its own design pass and would muddy the diff.

---

## Out of scope

- Fixing the documented bridge full-suite asyncio pollution (Phase 5+ TODO). The CI workflow runs files individually as the documented workaround.
- Refactoring `main.py`'s three near-identical command branches into a helper.
- Adding CI for the drone agent (`agents/drone_agent/`) or ML pipeline. Owners haven't stabilised their test harnesses yet; CI for those lanes belongs in their own PR after Day 7's integration gate.
- Pushing or opening the PR. The user controls ship.

---

## File Structure

**Create:**
- `.github/workflows/test.yml` — GitHub Actions workflow, ~80 lines
- `frontend/ws_bridge/tests/test_main_error_paths.py` — new test file, ~250 lines, covers 5 missing tests

**No modifications.** The bridge `main.py` already raises the right echoes; we are only adding tests.

---

## Task 1: Error-path test file scaffolding (TDD-style: failing tests first)

**Files:**
- Create: `frontend/ws_bridge/tests/test_main_error_paths.py`

This task lays down the fixtures shared by all five error-path tests. We copy the `app_and_client` and `fake_client` fixtures verbatim from `test_main_operator_command_publish.py` (they are already-proven plumbing) and add one new helper: `_force_envelope_invalid` that monkeypatches `frontend.ws_bridge.main._now_iso_ms` to return a non-ISO string, which makes the envelope's defensive re-validation fail. That is the cleanest way to drive the `bridge_internal` branch without poking schema internals.

- [ ] **Step 1: Write the file scaffold with imports and fixtures**

```python
"""Phase 4 follow-up: cover the error paths the happy-path Phase 4 tests
intentionally skipped — ``bridge_internal`` (envelope re-validation
fails) and ``redis_publish_failed`` (publisher raises) for each of the
three command branches in ``frontend/ws_bridge/main.py``.

Test harness mirrors ``test_main_operator_command_publish.py``: single
event loop, ASGI WS transport, fakeredis bound to the same loop, lifespan
driven manually so subscriber + emit tasks run inline.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

import fakeredis.aioredis as fakeredis_async
import httpx
import pytest
import pytest_asyncio
from httpx_ws import aconnect_ws
from httpx_ws.transport import ASGIWebSocketTransport


@pytest_asyncio.fixture
async def fake_client():
    client = fakeredis_async.FakeRedis()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def app_and_client(monkeypatch, fake_client):
    import redis.asyncio as redis_async

    monkeypatch.setattr(
        redis_async.Redis,
        "from_url",
        staticmethod(lambda url, **kw: fake_client),
    )

    from frontend.ws_bridge.main import create_app

    app = create_app()
    transport = ASGIWebSocketTransport(app=app)
    client = httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    )
    async with app.router.lifespan_context(app):
        try:
            yield app, client, fake_client
        finally:
            transport.exit_stack = None
            await client.aclose()


async def _drain_until(ws, predicate, *, max_frames: int = 20) -> Dict[str, Any]:
    for _ in range(max_frames):
        raw = await ws.receive_text()
        msg = json.loads(raw)
        if predicate(msg):
            return msg
    raise AssertionError(
        f"no frame matched predicate after {max_frames} frames"
    )


class _IsoMsCounter:
    """Wraps a fixed return value with an invocation counter so the test
    can assert the bridge's stamping path actually executed (eng-review
    1A — silent decoupling guard if ``_now_iso_ms`` is ever refactored
    to a local import or aliased symbol).
    """

    def __init__(self, value: str = "not-an-iso") -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        return self.value
```

- [ ] **Step 2: Commit the scaffold**

```bash
git add frontend/ws_bridge/tests/test_main_error_paths.py
git commit -m "Phase 4 follow-up: scaffold error-path test file"
```

---

## Task 2: `redis_publish_failed` for `operator_command`

**Files:**
- Modify: `frontend/ws_bridge/tests/test_main_error_paths.py` (append)

The branch we are exercising is `frontend/ws_bridge/main.py:359-369` (the `try: await app.state.publisher.publish("egs.operator_commands", ...) except Exception` block). We monkeypatch `app.state.publisher.publish` to raise.

- [ ] **Step 1: Append the failing test**

```python
@pytest.mark.asyncio
async def test_operator_command_redis_publish_failed_emits_echo(
    app_and_client, monkeypatch
):
    """When the publisher raises during ``operator_command`` republish,
    the bridge MUST echo ``redis_publish_failed`` and MUST NOT ack with
    ``operator_command_received``.
    """
    app, http_client, _fake = app_and_client

    async def _boom(*_a, **_kw):
        raise RuntimeError("redis is on fire")

    monkeypatch.setattr(app.state.publisher, "publish", _boom)

    frame = {
        "type": "operator_command",
        "command_id": "err-cmd-1",
        "language": "en",
        "raw_text": "recall drone1",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()  # initial state envelope
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "redis_publish_failed"
        )

    assert echo["type"] == "echo"
    assert echo["error"] == "redis_publish_failed"
    assert echo["command_id"] == "err-cmd-1"
```

- [ ] **Step 2: Run the test to confirm it passes**

Run: `PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_error_paths.py::test_operator_command_redis_publish_failed_emits_echo -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/ws_bridge/tests/test_main_error_paths.py
git commit -m "Phase 4 follow-up: cover redis_publish_failed for operator_command"
```

---

## Task 3: `bridge_internal` for `operator_command`

**Files:**
- Modify: `frontend/ws_bridge/tests/test_main_error_paths.py` (append)

This drives the second `if not bridge_outcome.valid` block in the same branch (`main.py:351-358`). We force the envelope re-validation to fail by making `_now_iso_ms` return a string that does not match the schema's ISO regex — the inbound `operator_command` is still schema-valid, so we know the failure originates in the bridge's own re-validation step.

- [ ] **Step 1: Append the failing test**

```python
@pytest.mark.asyncio
async def test_operator_command_bridge_internal_when_envelope_invalid(
    app_and_client, monkeypatch
):
    """Force the bridge's envelope re-validation to fail by stamping a
    non-ISO timestamp. The inbound frame is well-formed, so the only path
    that fires here is ``bridge_internal``.
    """
    import frontend.ws_bridge.main as bridge_main

    iso = _IsoMsCounter()
    monkeypatch.setattr(bridge_main, "_now_iso_ms", iso)

    app, http_client, _fake = app_and_client

    frame = {
        "type": "operator_command",
        "command_id": "err-cmd-2",
        "language": "en",
        "raw_text": "recall drone1",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "bridge_internal"
        )

    assert echo["type"] == "echo"
    assert echo["error"] == "bridge_internal"
    assert echo["command_id"] == "err-cmd-2"
    assert "detail" in echo and isinstance(echo["detail"], list)
    # Decoupling guard: if _now_iso_ms is ever refactored to a local
    # import or aliased symbol, our monkeypatch silently stops driving
    # the envelope-fail path. Assert the bridge actually invoked it.
    assert iso.calls >= 1, "monkeypatched _now_iso_ms was never called"
```

- [ ] **Step 2: Run the test**

Run: `PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_error_paths.py::test_operator_command_bridge_internal_when_envelope_invalid -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add frontend/ws_bridge/tests/test_main_error_paths.py
git commit -m "Phase 4 follow-up: cover bridge_internal for operator_command"
```

---

## Task 4: `bridge_internal` and `redis_publish_failed` for `finding_approval`

**Files:**
- Modify: `frontend/ws_bridge/tests/test_main_error_paths.py` (append)

The `finding_approval` branch has the additional wrinkle that we have to seed a real finding into the aggregator first (otherwise the allowlist guard rejects with `unknown_finding_id` before either error path can fire). We do that by publishing a `state_update` onto `egs.state` via the fake redis client BEFORE opening the WS — the subscriber pipes it into the aggregator on connect and the initial state envelope echoes it back, which doubles as our "aggregator is hot" signal.

- [ ] **Step 1: Append a small helper for seeding a finding**

```python
async def _seed_finding(fake, finding_id: str = "f-err-1") -> None:
    """Publish a state_update onto ``egs.state`` so the aggregator
    accepts ``finding_id`` for the allowlist guard. The subscriber will
    pick it up on lifespan startup.

    Eng-review 1B: re-derive the inner field shapes from
    ``shared/schemas/finding.json`` and ``shared/schemas/drone_state.json``
    BEFORE writing the test, then validate the assembled payload against
    ``state_update`` here so seed-payload drift fails loudly at setup,
    not silently inside the subscriber's ignored-message path.
    """
    from shared.contracts import validate

    payload = {
        "type": "state_update",
        "timestamp": "2026-05-03T00:00:00.000Z",
        "contract_version": "1.0.0",
        "egs_state": {"recent_validation_events": []},
        "active_findings": [
            {
                # Field names below are placeholders — re-derive from
                # shared/schemas/finding.json before committing this test.
                "finding_id": finding_id,
                "drone_id": "drone1",
                "category": "structure_collapse",
                "lat": 0.0, "lon": 0.0, "alt_m": 0.0,
                "confidence": 0.9,
                "first_seen_iso_ms": "2026-05-03T00:00:00.000Z",
                "approved": False,
            }
        ],
        "active_drones": [
            # Re-derive from shared/schemas/drone_state.json before commit.
            {"drone_id": "drone1", "lat": 0.0, "lon": 0.0, "alt_m": 0.0,
             "battery_pct": 100, "mode": "patrol",
             "last_heartbeat_iso_ms": "2026-05-03T00:00:00.000Z"}
        ],
    }
    outcome = validate("state_update", payload)
    assert outcome.valid, (
        f"_seed_finding payload drifted from schema; subscriber would "
        f"silently drop and allowlist guard would still reject. "
        f"Errors: {[e.message for e in outcome.errors]}"
    )
    await fake.publish("egs.state", json.dumps(payload))
    # Give the subscriber a tick to drain.
    await asyncio.sleep(0.05)
```

The ``validate(...)`` self-check at line 19 is the load-bearing line: if any field name above drifts from the actual schema, this assertion fires at test setup with a precise error list, instead of the test failing 500ms later with "got `unknown_finding_id` instead of `bridge_internal`" — which is the failure mode the eng review flagged.

- [ ] **Step 2: Append the `redis_publish_failed` test**

```python
@pytest.mark.asyncio
async def test_finding_approval_redis_publish_failed_emits_echo(
    app_and_client, monkeypatch
):
    app, http_client, fake = app_and_client
    await _seed_finding(fake, "f-err-1")

    async def _boom(*_a, **_kw):
        raise RuntimeError("redis is on fire")

    monkeypatch.setattr(app.state.publisher, "publish", _boom)

    frame = {
        "type": "finding_approval",
        "command_id": "err-cmd-3",
        "finding_id": "f-err-1",
        "action": "approve",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "redis_publish_failed"
        )

    assert echo["error"] == "redis_publish_failed"
    assert echo["command_id"] == "err-cmd-3"
    assert echo["finding_id"] == "f-err-1"
```

- [ ] **Step 3: Append the `bridge_internal` test**

```python
@pytest.mark.asyncio
async def test_finding_approval_bridge_internal_when_envelope_invalid(
    app_and_client, monkeypatch
):
    import frontend.ws_bridge.main as bridge_main

    app, http_client, fake = app_and_client
    await _seed_finding(fake, "f-err-2")
    iso = _IsoMsCounter()
    monkeypatch.setattr(bridge_main, "_now_iso_ms", iso)

    frame = {
        "type": "finding_approval",
        "command_id": "err-cmd-4",
        "finding_id": "f-err-2",
        "action": "approve",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "bridge_internal"
        )

    assert echo["error"] == "bridge_internal"
    assert echo["command_id"] == "err-cmd-4"
    assert echo["finding_id"] == "f-err-2"
    assert iso.calls >= 1, "monkeypatched _now_iso_ms was never called"
```

- [ ] **Step 4: Run both tests**

Run: `PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_error_paths.py -k "finding_approval" -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/ws_bridge/tests/test_main_error_paths.py
git commit -m "Phase 4 follow-up: cover bridge_internal + redis_publish_failed for finding_approval"
```

---

## Task 5: `bridge_internal` and `redis_publish_failed` for `operator_command_dispatch`

**Files:**
- Modify: `frontend/ws_bridge/tests/test_main_error_paths.py` (append)

This branch has no allowlist precondition — it accepts any well-formed dispatch frame. So we only need the same two failure injections.

- [ ] **Step 1: Append both tests**

```python
@pytest.mark.asyncio
async def test_dispatch_redis_publish_failed_emits_echo(
    app_and_client, monkeypatch
):
    app, http_client, _fake = app_and_client

    async def _boom(*_a, **_kw):
        raise RuntimeError("redis is on fire")

    monkeypatch.setattr(app.state.publisher, "publish", _boom)

    frame = {
        "type": "operator_command_dispatch",
        "command_id": "err-cmd-5",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "redis_publish_failed"
        )

    assert echo["error"] == "redis_publish_failed"
    assert echo["command_id"] == "err-cmd-5"


@pytest.mark.asyncio
async def test_dispatch_bridge_internal_when_envelope_invalid(
    app_and_client, monkeypatch
):
    import frontend.ws_bridge.main as bridge_main

    iso = _IsoMsCounter()
    monkeypatch.setattr(bridge_main, "_now_iso_ms", iso)

    app, http_client, _fake = app_and_client

    frame = {
        "type": "operator_command_dispatch",
        "command_id": "err-cmd-6",
        "contract_version": "1.0.0",
    }

    async with aconnect_ws("ws://testserver/", client=http_client) as ws:
        await ws.receive_text()
        await ws.send_text(json.dumps(frame))
        echo = await _drain_until(
            ws, lambda m: m.get("error") == "bridge_internal"
        )

    assert echo["error"] == "bridge_internal"
    assert echo["command_id"] == "err-cmd-6"
    assert iso.calls >= 1, "monkeypatched _now_iso_ms was never called"
```

- [ ] **Step 2: Run both tests**

Run: `PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_error_paths.py -k "dispatch" -v`
Expected: 2 passed

- [ ] **Step 3: Run the full new file to confirm all 5 tests pass together**

Run: `PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_main_error_paths.py -v`
Expected: 5 passed, no warnings

- [ ] **Step 4: Commit**

```bash
git add frontend/ws_bridge/tests/test_main_error_paths.py
git commit -m "Phase 4 follow-up: cover bridge_internal + redis_publish_failed for dispatch"
```

---

## Task 6: GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/test.yml`

Two jobs in parallel: `bridge` (Python) and `flutter` (Dart). Bridge runs each test file individually because `pytest frontend/ws_bridge/tests/` has known cross-file asyncio pollution (TODOS.md "Bridge full-suite asyncio test pollution"). Flutter runs `flutter test` which is straightforward.

- [ ] **Step 1: Create `.github/` directory and workflow file**

Run: `mkdir -p .github/workflows`

Then write `.github/workflows/test.yml`:

```yaml
name: tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  bridge:
    name: ws_bridge + shared contracts
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r frontend/ws_bridge/requirements.txt
          pip install -r frontend/ws_bridge/requirements-dev.txt
          pip install -r shared/requirements.txt
      - name: Run shared contracts tests
        run: PYTHONPATH=. python -m pytest shared/ -v
      - name: Run ws_bridge tests (per file, see TODOS.md asyncio pollution note)
        run: |
          set -e
          for f in frontend/ws_bridge/tests/test_*.py; do
            echo "::group::$f"
            PYTHONPATH=. python -m pytest "$f" -v
            echo "::endgroup::"
          done

  flutter:
    name: flutter_dashboard
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: subosito/flutter-action@v2
        with:
          channel: stable
          cache: true
      - name: Generate topic constants
        run: PYTHONPATH=. python3 scripts/gen_topic_constants.py
      - name: Flutter pub get
        working-directory: frontend/flutter_dashboard
        run: flutter pub get
      - name: Flutter analyze
        working-directory: frontend/flutter_dashboard
        run: flutter analyze
      - name: Flutter test
        working-directory: frontend/flutter_dashboard
        run: flutter test
```

- [ ] **Step 2: Verify the per-file pytest pattern works locally**

Run:
```bash
set -e
for f in frontend/ws_bridge/tests/test_*.py; do
  echo "=== $f ==="
  PYTHONPATH=. python3 -m pytest "$f" -q
done
```
Expected: every file reports `passed` (warnings are fine; failures are not). If a file fails locally, fix or quarantine that file before pushing — CI will fail otherwise. The pollution issue is cross-file, not single-file.

- [ ] **Step 3: Verify Flutter analyze + test pass locally**

Run:
```bash
cd frontend/flutter_dashboard && flutter analyze && flutter test
```
Expected: `No issues found!` and all tests pass.

- [ ] **Step 4: Confirm `gen_topic_constants.py` is idempotent and committed**

Run: `PYTHONPATH=. python3 scripts/gen_topic_constants.py && git status --short`
Expected: no diff produced. (If a diff appears, the generated artifact is stale and needs to be committed before CI can pass — file as a separate commit.)

- [ ] **Step 5: Commit the workflow**

```bash
git add .github/workflows/test.yml
git commit -m "CI: GitHub Actions workflow for bridge + flutter tests"
```

---

## Self-Review

Before handoff:

1. **Spec coverage:**
   - 5 new bridge tests ✓ (cover the 5 uncovered echoes documented in this plan's "Why these two now" section)
   - CI workflow runs every test currently in the repo ✓ (bridge per-file, shared, flutter)
   - `flutter analyze` runs to catch the kind of lint warnings Phase 4 Task 13 had to chase down post-hoc ✓

2. **Placeholder scan:** None. Every test body is complete code. The workflow YAML is complete.

3. **Type consistency:**
   - `_now_iso_ms` is monkeypatched on `frontend.ws_bridge.main` (module-level), not on a copy. Verified by `grep -n "_now_iso_ms" frontend/ws_bridge/main.py` — used at call sites by name, not aliased.
   - `app.state.publisher.publish` matches the `RedisPublisher.publish(channel, payload)` signature — `_boom(*_a, **_kw)` swallows both.
   - Echo error keys (`bridge_internal`, `redis_publish_failed`) match `main.py:354,370,419,438,479,495` exactly.

4. **Operational risks I considered:**
   - CI cold-start time on Ubuntu: Flutter setup is the slow step (~2 min). Bridge job runs in parallel so wall-clock ~3 min total. Acceptable.
   - The per-file pytest loop hides a file-level test count regression (e.g., a whole file becoming a no-op). Mitigation: `flutter analyze` and the `set -e` shell flag still surface the most likely failure modes. Full-suite-pass is filed as a Phase 5+ TODO.
   - `subosito/flutter-action@v2` is the de-facto standard action; pinned to major version. If we need a stable channel pin later, that is a one-line change.

5. **Things I deliberately did not do:**
   - Did not enable branch protection or required checks. That is a repo-settings change, not a workflow change. After this PR merges, I'll suggest enabling required checks on `main` separately.
   - Did not add coverage reporting. Would balloon scope. File as Phase 5+ if the team wants it.

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session, batch with checkpoints.

Which approach?

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 3 issues (1A monkeypatch decoupling, 1B seed-payload drift, 2A `_drain_until` duplication); 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**UNRESOLVED:** 0
**VERDICT:** ENG CLEARED — applied 1A (counter guard on `_now_iso_ms` monkeypatch), 1B (seed payload self-validates against `state_update` schema). 2A deferred to Phase 5+ TODO ("Extract bridge WS test helpers to `conftest.py`"). Plan is implementation-ready.
