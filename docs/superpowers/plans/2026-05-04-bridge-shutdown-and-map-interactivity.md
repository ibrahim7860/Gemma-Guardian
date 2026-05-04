# Bridge Shutdown Cleanup + Map Marker Interactivity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate `RuntimeError: Event loop is closed` shutdown noise from the WS bridge AND make map markers cross-highlight rows in the Findings and Drone Status panels.

**Architecture:** Two independent unblocked workstreams from `TODOS.md` bundled into one PR because they share the same owner (Person 4) and neither touches shared/contracts:

1. **Bridge teardown ordering** (`frontend/ws_bridge/main.py:174-214`): set `subscriber._stopping=True` and await all three background tasks BEFORE calling `subscriber.stop()` (which calls `pubsub.aclose()`). Today's sequence — cancel → stop (closes pubsub) → await tasks — lets `subscribe_task` be mid-`pubsub.get_message()` when `aclose()` runs, producing stderr noise on every shutdown.

2. **Map marker interactivity** (`frontend/flutter_dashboard/lib/widgets/map_panel.dart:60-124`): wrap drone and finding markers in `GestureDetector`s, expose `selectedFindingId` / `selectedDroneId` on `MissionState`, and have `findings_panel.dart` + `drone_status_panel.dart` render a highlight border on the selected row. Re-clicking the same marker clears the selection.

**Tech Stack:** Python 3.11 + FastAPI + pytest-asyncio + fakeredis (bridge); Flutter 3.x + Provider + flutter_test (dashboard).

---

## File Structure

**Bridge (Task 1-3):**
- Modify: `frontend/ws_bridge/main.py:190-214` — reorder lifespan teardown
- Modify: `frontend/ws_bridge/redis_subscriber.py:151-175` — split `stop()` into `signal_stop()` + `close()` so the lifespan can signal first, await the run task, then close the pubsub
- Create: `frontend/ws_bridge/tests/test_main_lifespan_teardown.py` — assert teardown order via captured shutdown logs

**Dashboard (Task 4-7):**
- Modify: `frontend/flutter_dashboard/lib/state/mission_state.dart:35-83` — add `selectedFindingId`, `selectedDroneId`, `selectFinding()`, `selectDrone()`, `clearSelection()`
- Modify: `frontend/flutter_dashboard/lib/widgets/map_panel.dart:60-124` — wrap markers in `GestureDetector`s with hit-testing rects sized to match painted radii; replace zero-size `Positioned` shells with real positioned tap targets; pass projection coords to a small private `_MarkerLayer` widget so the painter and the hit boxes share one source of truth
- Modify: `frontend/flutter_dashboard/lib/widgets/findings_panel.dart:82-118` — add `Container(decoration: ...)` highlight when `mission.selectedFindingId == id`
- Modify: `frontend/flutter_dashboard/lib/widgets/drone_status_panel.dart:24-46` — same highlight pattern when `mission.selectedDroneId == droneId`
- Create: `frontend/flutter_dashboard/test/map_panel_interaction_test.dart` — widget tests for tap → selection → highlight
- Modify: `frontend/flutter_dashboard/test/mission_state_test.dart` — add unit tests for the selection API

**TODO bookkeeping (Task 8):**
- Modify: `TODOS.md:51-57` (close map marker tap/hover) and `TODOS.md:78-84` (close bridge lifespan teardown ordering)

---

## Bridge Workstream

### Task 1: Split `RedisSubscriber.stop()` into `signal_stop()` + `close()`

The current `stop()` does two things in one call: it sets `_stopping=True` (so the run loop exits its next iteration) AND it tears down the pubsub. The lifespan handler can't put `await subscribe_task` between those two steps. Splitting the method gives the lifespan handler a place to await the run task before closing the pubsub.

**Files:**
- Modify: `frontend/ws_bridge/redis_subscriber.py:151-175`
- Test: `frontend/ws_bridge/tests/test_subscriber.py` (extend existing)

- [ ] **Step 1: Write the failing test**

Append to `frontend/ws_bridge/tests/test_subscriber.py`:

```python
@pytest.mark.asyncio
async def test_signal_stop_only_sets_flag_does_not_close_pubsub():
    """signal_stop() must set _stopping=True without touching pubsub.

    The lifespan handler relies on this so it can await the run task
    (which exits cleanly because the flag is set) before closing the
    pubsub via close().
    """
    fake = fakeredis.aioredis.FakeRedis()
    config = BridgeConfig(redis_url="redis://localhost", tick_s=0.05,
                         max_findings=100, broadcast_timeout_s=0.5,
                         reconnect_max_s=2.0)
    aggregator = StateAggregator(max_findings=100, seed_envelope=_seed())
    sub = RedisSubscriber(
        config=config, aggregator=aggregator,
        validation_logger=ValidationEventLogger(),
        translation_queue=asyncio.Queue(maxsize=64),
        client_factory=lambda url: fake,
    )
    task = asyncio.create_task(sub.run())
    await asyncio.sleep(0.05)  # let it subscribe

    sub.signal_stop()
    assert sub._stopping is True
    # pubsub is still open at this point — we only signalled.
    assert sub._pubsub is not None

    # Now the run task should exit on its own.
    await asyncio.wait_for(task, timeout=2.0)

    # And close() actually tears down.
    await sub.close()
    assert sub._pubsub is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python -m pytest frontend/ws_bridge/tests/test_subscriber.py::test_signal_stop_only_sets_flag_does_not_close_pubsub -v`
Expected: FAIL with `AttributeError: 'RedisSubscriber' object has no attribute 'signal_stop'`.

- [ ] **Step 3: Implement `signal_stop()` and rename teardown half to `close()`**

Replace the existing `stop()` method in `frontend/ws_bridge/redis_subscriber.py:151-175` with:

```python
def signal_stop(self) -> None:
    """Set the stop flag. Does NOT close the pubsub.

    The run loop checks ``self._stopping`` on every iteration of
    ``_connect_and_dispatch``'s read loop and on every iteration of
    ``run()``'s reconnect loop. Once this is True, the run task
    exits cleanly on its next read-timeout boundary
    (``_GET_MESSAGE_TIMEOUT_S``).

    Synchronous so callers can fire it from a non-async context
    (e.g., signal handlers) without ceremony.
    """
    self._stopping = True

async def close(self) -> None:
    """Tear down the pubsub and client. Idempotent.

    Must be called AFTER the run task has exited; otherwise the run
    task may be mid-``pubsub.get_message()`` when ``aclose()`` runs,
    producing ``RuntimeError: Event loop is closed`` on shutdown.
    """
    pubsub = self._pubsub
    client = self._client
    self._pubsub = None
    self._client = None
    if pubsub is not None:
        try:
            await pubsub.unsubscribe()
        except Exception:
            pass
        try:
            await pubsub.punsubscribe()
        except Exception:
            pass
        try:
            await pubsub.aclose()
        except Exception:
            pass
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            pass

# Backwards-compat shim — keep ``stop()`` working for any external
# callers (none in-tree, but cheap insurance). Wraps the new pair.
async def stop(self) -> None:
    """Deprecated: use signal_stop() + close() in lifespan order."""
    self.signal_stop()
    await self.close()
```

- [ ] **Step 4: Run new test to verify it passes**

Run: `PYTHONPATH=. python -m pytest frontend/ws_bridge/tests/test_subscriber.py::test_signal_stop_only_sets_flag_does_not_close_pubsub -v`
Expected: PASS.

- [ ] **Step 5: Run full subscriber test file to verify backwards-compat `stop()` still works**

Run: `PYTHONPATH=. python -m pytest frontend/ws_bridge/tests/test_subscriber.py -v`
Expected: All existing tests PASS (the legacy `await subscriber.stop()` call at `test_subscriber.py:145` should still work via the shim).

- [ ] **Step 6: Commit**

```bash
git add frontend/ws_bridge/redis_subscriber.py frontend/ws_bridge/tests/test_subscriber.py
git commit -m "refactor(bridge): split RedisSubscriber.stop() into signal_stop() + close()"
```

---

### Task 2: Reorder lifespan teardown

**Files:**
- Modify: `frontend/ws_bridge/main.py:190-214`
- Test: `frontend/ws_bridge/tests/test_main_lifespan_teardown.py` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/ws_bridge/tests/test_main_lifespan_teardown.py`:

```python
"""Phase 5+: bridge lifespan teardown must NOT produce
``RuntimeError: Event loop is closed`` noise on shutdown.

The fix orders teardown as:

    1. signal_stop on subscriber (flag flips, no pubsub close yet)
    2. cancel emit/translation tasks
    3. await ALL THREE background tasks
    4. ONLY THEN close the subscriber's pubsub
    5. close the publisher

Today's sequence cancels and then closes the pubsub before the
subscribe task has a chance to exit its read loop, leaving the task
mid-``pubsub.get_message()`` when ``aclose()`` runs. We verify the
new ordering by capturing the call order on a stub subscriber.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import List

import pytest
from httpx import ASGITransport, AsyncClient

from frontend.ws_bridge.main import create_app


class _OrderRecordingSubscriber:
    """Stand-in subscriber that records the order of lifecycle calls."""

    def __init__(self, order: List[str]) -> None:
        self._order = order
        self._stopping = False
        self._run_started = asyncio.Event()
        self._run_done = asyncio.Event()

    async def run(self) -> None:
        self._order.append("run_start")
        self._run_started.set()
        # Park until signal_stop flips _stopping. Mirrors the real
        # subscriber's read-timeout-then-check-flag loop.
        while not self._stopping:
            await asyncio.sleep(0.01)
        self._order.append("run_exit")
        self._run_done.set()

    def signal_stop(self) -> None:
        self._order.append("signal_stop")
        self._stopping = True

    async def close(self) -> None:
        self._order.append("close")

    # Legacy shim — must NOT be called by the new lifespan.
    async def stop(self) -> None:  # pragma: no cover
        self._order.append("LEGACY_STOP_CALLED")
        self.signal_stop()
        await self.close()


@pytest.mark.asyncio
async def test_lifespan_signals_stop_before_closing_pubsub(monkeypatch):
    order: List[str] = []
    stub = _OrderRecordingSubscriber(order)

    app = create_app()
    # Swap in our recording subscriber after create_app() wired the real one.
    app.state.subscriber = stub

    async with AsyncExitStack() as stack:
        transport = ASGITransport(app=app)
        client = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url="http://testserver")
        )
        # Trigger the lifespan startup by hitting /health.
        r = await client.get("/health")
        assert r.status_code == 200
        # Give the subscribe task a tick to enter its run loop.
        await asyncio.wait_for(stub._run_started.wait(), timeout=1.0)

    # AsyncExitStack closing -> ASGITransport -> lifespan shutdown.
    # Verify ordering:
    #   signal_stop must precede close
    #   run_exit must precede close (i.e., we awaited the task)
    assert "signal_stop" in order, order
    assert "close" in order, order
    assert "run_exit" in order, order
    assert order.index("signal_stop") < order.index("close"), order
    assert order.index("run_exit") < order.index("close"), order
    assert "LEGACY_STOP_CALLED" not in order, order
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python -m pytest frontend/ws_bridge/tests/test_main_lifespan_teardown.py -v`
Expected: FAIL — current lifespan calls `subscriber.stop()` directly, which the stub records as `LEGACY_STOP_CALLED`. Assertion `"LEGACY_STOP_CALLED" not in order` fails.

- [ ] **Step 3: Update lifespan teardown**

Replace `frontend/ws_bridge/main.py:192-214` (the `try: yield ... finally:` block) with:

```python
    try:
        yield
    finally:
        # Phase 5+ teardown ordering. The old sequence
        # (cancel → subscriber.stop → await tasks) closed the
        # subscriber's pubsub while the subscribe task was still mid-
        # ``pubsub.get_message()``, producing
        # ``RuntimeError: Event loop is closed`` on every shutdown.
        #
        # New order:
        #   1. Flip the subscriber's stop flag (NO pubsub close yet)
        #   2. Cancel the emit + translation tasks (they don't share
        #      the pubsub; cancel is safe and immediate)
        #   3. Await ALL THREE tasks so the subscribe task has a
        #      chance to exit its read loop on the flag transition
        #   4. ONLY THEN close the subscriber (pubsub.aclose())
        #   5. Close the publisher
        subscriber.signal_stop()
        emit_task.cancel()
        translation_task.cancel()
        for task in (emit_task, subscribe_task, translation_task):
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await subscriber.close()
        except Exception:
            pass
        try:
            await app.state.publisher.close()
        except Exception:
            pass
```

- [ ] **Step 4: Run lifespan teardown test to verify it passes**

Run: `PYTHONPATH=. python -m pytest frontend/ws_bridge/tests/test_main_lifespan_teardown.py -v`
Expected: PASS.

- [ ] **Step 5: Run full bridge suite to verify nothing broke**

Run: `PYTHONPATH=. python -m pytest frontend/ws_bridge/tests/ -m "not e2e" -v`
Expected: All tests PASS. (We're checking the existing `test_main_*.py` files still tear down cleanly and don't regress.)

- [ ] **Step 6: Smoke-test stderr cleanliness manually**

Run:
```bash
PYTHONPATH=. python -c "
import asyncio
from frontend.ws_bridge.main import create_app
from contextlib import AsyncExitStack
from httpx import ASGITransport, AsyncClient

async def main():
    app = create_app()
    async with AsyncExitStack() as stack:
        transport = ASGITransport(app=app)
        client = await stack.enter_async_context(
            AsyncClient(transport=transport, base_url='http://testserver')
        )
        r = await client.get('/health')
        print('health:', r.status_code)

asyncio.run(main())
" 2>&1 | grep -i "RuntimeError\|Event loop" || echo "CLEAN: no shutdown noise"
```
Expected: `CLEAN: no shutdown noise` (no `RuntimeError: Event loop is closed` lines on stderr).

- [ ] **Step 7: Commit**

```bash
git add frontend/ws_bridge/main.py frontend/ws_bridge/tests/test_main_lifespan_teardown.py
git commit -m "fix(bridge): clean shutdown ordering eliminates 'Event loop is closed' noise"
```

---

### Task 3: Verify CI green

- [ ] **Step 1: Push branch and check CI**

```bash
git push -u origin feat/bridge-shutdown-and-map-interactivity
```
Then watch the `bridge` job on GitHub Actions for the test run.

- [ ] **Step 2: Run e2e job locally if green**

Run: `PYTHONPATH=. python -m pytest frontend/ws_bridge/tests/test_e2e_playwright.py -m e2e -v`
Expected: All e2e tests still pass (lifespan reorder must not regress real Redis + Chromium teardown).

---

## Dashboard Workstream

### Task 4: Add selection state to `MissionState`

**Files:**
- Modify: `frontend/flutter_dashboard/lib/state/mission_state.dart` (add fields + 3 methods after the existing approval/command sections, around line 83)
- Test: `frontend/flutter_dashboard/test/mission_state_test.dart` (extend)

- [ ] **Step 1: Write the failing test**

Append to `frontend/flutter_dashboard/test/mission_state_test.dart`:

```dart
group('map marker selection', () {
  test('selectFinding stores id and notifies listeners', () {
    final s = MissionState();
    var notifications = 0;
    s.addListener(() => notifications++);

    s.selectFinding('f_drone1_5');

    expect(s.selectedFindingId, equals('f_drone1_5'));
    expect(s.selectedDroneId, isNull);
    expect(notifications, equals(1));
  });

  test('selectDrone clears any active finding selection', () {
    final s = MissionState();
    s.selectFinding('f_drone1_5');

    s.selectDrone('drone1');

    expect(s.selectedFindingId, isNull,
        reason: 'finding selection must clear when a drone is selected');
    expect(s.selectedDroneId, equals('drone1'));
  });

  test('selectFinding called twice with the same id clears the selection', () {
    final s = MissionState();
    s.selectFinding('f_drone1_5');
    s.selectFinding('f_drone1_5');

    expect(s.selectedFindingId, isNull,
        reason: 're-selecting the same id is a toggle');
  });

  test('selectDrone called twice with the same id clears the selection', () {
    final s = MissionState();
    s.selectDrone('drone1');
    s.selectDrone('drone1');

    expect(s.selectedDroneId, isNull);
  });

  test('clearSelection drops both finding and drone ids', () {
    final s = MissionState();
    s.selectDrone('drone1');
    s.clearSelection();
    expect(s.selectedFindingId, isNull);
    expect(s.selectedDroneId, isNull);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend/flutter_dashboard && flutter test test/mission_state_test.dart`
Expected: FAIL with `The getter 'selectedFindingId' isn't defined for the type 'MissionState'`.

- [ ] **Step 3: Implement the selection API**

Insert into `frontend/flutter_dashboard/lib/state/mission_state.dart` immediately after the line `Map<String, dynamic>? commandTranslation(String commandId) => _commandTranslations[commandId];` (currently around line 83), and BEFORE the `submitOperatorCommand` method:

```dart

// ---- map marker selection ----------------------------------------------
//
// One-of: at most one selection at a time. Selecting a drone clears any
// finding selection, and vice versa. Re-selecting the same id is a
// toggle that clears the selection — matches operator expectation
// ("click again to deselect").

String? _selectedFindingId;
String? _selectedDroneId;

String? get selectedFindingId => _selectedFindingId;
String? get selectedDroneId => _selectedDroneId;

void selectFinding(String findingId) {
  if (_selectedFindingId == findingId) {
    // Toggle off.
    _selectedFindingId = null;
  } else {
    _selectedFindingId = findingId;
    _selectedDroneId = null;
  }
  notifyListeners();
}

void selectDrone(String droneId) {
  if (_selectedDroneId == droneId) {
    _selectedDroneId = null;
  } else {
    _selectedDroneId = droneId;
    _selectedFindingId = null;
  }
  notifyListeners();
}

void clearSelection() {
  if (_selectedFindingId == null && _selectedDroneId == null) return;
  _selectedFindingId = null;
  _selectedDroneId = null;
  notifyListeners();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend/flutter_dashboard && flutter test test/mission_state_test.dart`
Expected: PASS (all new tests in the `map marker selection` group plus all existing tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/flutter_dashboard/lib/state/mission_state.dart frontend/flutter_dashboard/test/mission_state_test.dart
git commit -m "feat(dashboard): add MissionState selection API for map markers"
```

---

### Task 5: Make map markers tappable

The current `_buildDroneMarkers` and `_buildFindingMarkers` (`map_panel.dart:87-124`) emit zero-size `Positioned` shells. They exist only so widget tests can find one-per-id keys; the real visuals are painted by `_ProjectionPainter`. We need to (a) compute marker positions in widget-land so the hit boxes match the painted circles, and (b) wrap each in a `GestureDetector`.

**Files:**
- Modify: `frontend/flutter_dashboard/lib/widgets/map_panel.dart`
- Test: `frontend/flutter_dashboard/test/map_panel_interaction_test.dart` (new)

- [ ] **Step 1: Write the failing test**

Create `frontend/flutter_dashboard/test/map_panel_interaction_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/map_panel.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';

Widget _wrap(MissionState s) => MaterialApp(
      home: ChangeNotifierProvider<MissionState>.value(
        value: s,
        child: const Scaffold(body: SizedBox(width: 600, height: 600, child: MapPanel())),
      ),
    );

Map<String, dynamic> _drone(String id, double lat, double lon) => {
      "drone_id": id,
      "agent_status": "active",
      "battery_pct": 87,
      "current_task": "survey_zone_a",
      "findings_count": 0,
      "validation_failures_total": 0,
      "position": {"lat": lat, "lon": lon, "alt": 50.0},
    };

Map<String, dynamic> _finding(String id, String drone, double lat, double lon) => {
      "finding_id": id,
      "source_drone_id": drone,
      "type": "victim",
      "severity": 4,
      "confidence": 0.8,
      "timestamp": "2026-05-04T12:00:00.000Z",
      "visual_description": "person prone in debris",
      "location": {"lat": lat, "lon": lon, "alt": 0.0},
      "validated": true,
      "operator_status": "pending",
    };

void _seed(MissionState s) {
  s.applyStateUpdate({
    "type": "state_update",
    "timestamp": "2026-05-04T12:00:00.000Z",
    "contract_version": "1.0.0",
    "active_findings": [
      _finding("f_drone1_5", "drone1", 34.001, -118.001),
    ],
    "active_drones": [
      _drone("drone1", 34.0, -118.0),
      _drone("drone2", 34.01, -118.01),
    ],
  });
}

void main() {
  testWidgets('tapping a drone marker selects that drone', (tester) async {
    final s = MissionState();
    _seed(s);
    await tester.pumpWidget(_wrap(s));
    await tester.pump();  // first frame: bbox locks

    await tester.tap(find.byKey(const ValueKey('map-drone-drone1')));
    await tester.pump();

    expect(s.selectedDroneId, equals('drone1'));
    expect(s.selectedFindingId, isNull);
  });

  testWidgets('tapping a finding marker selects that finding', (tester) async {
    final s = MissionState();
    _seed(s);
    await tester.pumpWidget(_wrap(s));
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('map-finding-f_drone1_5')));
    await tester.pump();

    expect(s.selectedFindingId, equals('f_drone1_5'));
    expect(s.selectedDroneId, isNull);
  });

  testWidgets('tapping the same drone marker twice deselects', (tester) async {
    final s = MissionState();
    _seed(s);
    await tester.pumpWidget(_wrap(s));
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('map-drone-drone1')));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('map-drone-drone1')));
    await tester.pump();

    expect(s.selectedDroneId, isNull);
  });
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend/flutter_dashboard && flutter test test/map_panel_interaction_test.dart`
Expected: FAIL — `tester.tap(...)` finds the zero-size `Positioned` shell but the tap target has no width/height, so the hit-test misses. Or `selectedDroneId` is still null because no `GestureDetector` is wired.

- [ ] **Step 3: Replace `_buildDroneMarkers` and `_buildFindingMarkers` with tappable, sized markers**

In `frontend/flutter_dashboard/lib/widgets/map_panel.dart`, replace the entire body of `_MapPanelState` (lines 29-125) with the version below. Key changes: (a) factor projection math out of `_ProjectionPainter` into a top-level `_project` helper so the widget layer and the painter share it, (b) compute marker rects in `LayoutBuilder` so they sit at the same coords the painter draws to, (c) wrap each marker in a `GestureDetector` calling into `MissionState`.

```dart
class _MapPanelState extends State<MapPanel> {
  _Bbox? _bbox;

  @override
  Widget build(BuildContext context) {
    return Consumer<MissionState>(
      builder: (_, mission, _) {
        final drones = mission.activeDrones.whereType<Map<String, dynamic>>().toList();
        final findings = mission.activeFindings.whereType<Map<String, dynamic>>().toList();
        final hasData = drones.isNotEmpty || findings.isNotEmpty;

        if (!hasData) {
          return const Center(child: Text("Waiting for state…"));
        }

        _bbox ??= _computeBbox(drones, findings);
        if (!_bboxStillCovers(_bbox!, drones, findings)) {
          _bbox = _computeBbox(drones, findings);
        }
        final bbox = _bbox!;
        final colors = palettePreview([
          for (final d in drones) (d["drone_id"] as String?) ?? "?",
        ]);

        return LayoutBuilder(builder: (context, constraints) {
          final size = Size(constraints.maxWidth, constraints.maxHeight);
          return Stack(
            children: [
              CustomPaint(
                size: Size.infinite,
                painter: _ProjectionPainter(
                  drones: drones,
                  findings: findings,
                  bbox: bbox,
                  colors: colors,
                ),
              ),
              ..._buildDroneMarkers(drones, bbox, size, mission),
              ..._buildFindingMarkers(findings, bbox, size, mission),
              Positioned(
                top: 4, right: 4,
                child: IconButton(
                  tooltip: "Refit",
                  icon: const Icon(Icons.center_focus_strong),
                  onPressed: () => setState(() => _bbox = null),
                ),
              ),
            ],
          );
        });
      },
    );
  }

  static const double _droneHitRadius = 18;  // bigger than the painted 9 so taps are forgiving
  static const double _findingHitRadius = 14;

  List<Widget> _buildDroneMarkers(
    List<Map<String, dynamic>> drones,
    _Bbox bbox,
    Size size,
    MissionState mission,
  ) {
    final out = <Widget>[];
    for (final d in drones) {
      final id = (d["drone_id"] as String?) ?? "?";
      final pos = d["position"] as Map<String, dynamic>?;
      final p = _project(pos?["lat"] as num?, pos?["lon"] as num?, bbox, size);
      if (p == null) continue;
      out.add(
        Positioned(
          key: ValueKey("map-drone-$id"),
          left: p.dx - _droneHitRadius,
          top: p.dy - _droneHitRadius,
          width: _droneHitRadius * 2,
          height: _droneHitRadius * 2,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => mission.selectDrone(id),
            child: const SizedBox.expand(),
          ),
        ),
      );
    }
    return out;
  }

  List<Widget> _buildFindingMarkers(
    List<Map<String, dynamic>> findings,
    _Bbox bbox,
    Size size,
    MissionState mission,
  ) {
    final out = <Widget>[];
    for (final f in findings) {
      final id = f["finding_id"] as String?;
      if (id == null) continue;
      final loc = f["location"] as Map<String, dynamic>?;
      final p = _project(loc?["lat"] as num?, loc?["lon"] as num?, bbox, size);
      if (p == null) continue;
      out.add(Positioned(
        key: ValueKey("map-finding-$id"),
        left: p.dx - _findingHitRadius,
        top: p.dy - _findingHitRadius,
        width: _findingHitRadius * 2,
        height: _findingHitRadius * 2,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onTap: () => mission.selectFinding(id),
          child: const SizedBox.expand(),
        ),
      ));
    }
    return out;
  }
}

/// Top-level projection used by both the painter and the widget hit-boxes.
/// Single source of truth: if you change one, change the painter together.
Offset? _project(num? la, num? lo, _Bbox bbox, Size size) {
  if (la == null || lo == null) return null;
  final lat = la.toDouble();
  final lon = lo.toDouble();
  if (!lat.isFinite || !lon.isFinite) return null;
  final cosLat = math.max(
    math.cos(bbox.midLat * math.pi / 180.0).abs(),
    0.01,
  );
  final lonScale = size.width / (bbox.lonSpan * cosLat);
  final latScale = size.height / bbox.latSpan;
  final x = (lon - bbox.minLon) * cosLat * lonScale;
  final y = size.height - (lat - bbox.minLat) * latScale;
  return Offset(x, y);
}
```

Then update `_ProjectionPainter.paint` (`map_panel.dart:217-275`) to delegate to `_project` instead of computing locally — replace its inline `Offset? project(...)` closure with calls to `_project(la, lo, bbox, size)`.

Concretely, in `_ProjectionPainter.paint`, replace the block from `final cosLat = math.max(...)` through the inline `Offset? project(num? la, num? lo) { ... }` definition with:

```dart
    Offset? project(num? la, num? lo) => _project(la, lo, bbox, size);
```

The painter's two callers (`final p = project(loc?["lat"] as num?, loc?["lon"] as num?);` etc.) keep working unchanged.

- [ ] **Step 4: Run interaction tests to verify they pass**

Run: `cd frontend/flutter_dashboard && flutter test test/map_panel_interaction_test.dart`
Expected: PASS for all three interaction tests.

- [ ] **Step 5: Run existing map_panel_test.dart to verify no regression**

Run: `cd frontend/flutter_dashboard && flutter test test/map_panel_test.dart`
Expected: PASS (existing tests find markers by `ValueKey('map-drone-...')` — those keys still exist, just now on real-sized hit boxes).

- [ ] **Step 6: Commit**

```bash
git add frontend/flutter_dashboard/lib/widgets/map_panel.dart frontend/flutter_dashboard/test/map_panel_interaction_test.dart
git commit -m "feat(dashboard): tappable map markers select findings/drones"
```

---

### Task 6: Highlight selected finding row in Findings panel

**Files:**
- Modify: `frontend/flutter_dashboard/lib/widgets/findings_panel.dart:82-118`
- Test: `frontend/flutter_dashboard/test/findings_panel_test.dart` (extend)

- [ ] **Step 1: Write the failing test**

Append to `frontend/flutter_dashboard/test/findings_panel_test.dart` (inside the existing `void main()` block, after the last test):

```dart
testWidgets('selected finding row renders blue highlight border', (tester) async {
  final s = MissionState();
  s.applyStateUpdate({
    "type": "state_update",
    "timestamp": "2026-05-04T12:00:00.000Z",
    "contract_version": "1.0.0",
    "active_drones": [],
    "active_findings": [
      {
        "finding_id": "f_drone1_5",
        "source_drone_id": "drone1",
        "type": "victim",
        "severity": 4,
        "confidence": 0.8,
        "timestamp": "2026-05-04T12:00:00.000Z",
        "visual_description": "person prone",
        "location": {"lat": 34.0, "lon": -118.0, "alt": 0.0},
        "validated": true,
        "operator_status": "pending",
      },
    ],
  });

  await tester.pumpWidget(MaterialApp(
    home: ChangeNotifierProvider<MissionState>.value(
      value: s,
      child: const Scaffold(body: FindingsPanel()),
    ),
  ));
  await tester.pump();

  // No selection — no highlight key.
  expect(find.byKey(const ValueKey('findings-row-highlight-f_drone1_5')),
      findsNothing);

  s.selectFinding('f_drone1_5');
  await tester.pump();

  expect(find.byKey(const ValueKey('findings-row-highlight-f_drone1_5')),
      findsOneWidget);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend/flutter_dashboard && flutter test test/findings_panel_test.dart`
Expected: FAIL — the new key doesn't exist yet.

- [ ] **Step 3: Add highlight wrapper in `_FindingTile.build`**

In `frontend/flutter_dashboard/lib/widgets/findings_panel.dart`, modify `_FindingTile.build` to wrap the existing `Container(decoration: ...)` block (currently around lines 82-118) in a parent `Container` whose decoration encodes the highlight when this row is selected. Replace the existing `return Container(...)` block at line 82 with:

```dart
    final isSelected = mission.selectedFindingId == id;
    return Container(
      key: isSelected
          ? ValueKey('findings-row-highlight-$id')
          : null,
      decoration: BoxDecoration(
        color: isSelected ? Colors.blue.withValues(alpha: 0.08) : null,
        border: Border(left: BorderSide(color: borderColor, width: 4)),
      ),
      child: Opacity(
        opacity: state == ApprovalState.dismissed ? 0.5 : 1.0,
        child: ListTile(
          title: Text(
            "${(finding["type"] as String).toUpperCase()} "
            "(severity ${finding["severity"]}, conf ${finding["confidence"]})",
            style: titleStyle,
          ),
          subtitle: Text(
            "${finding["source_drone_id"]} · ${finding["timestamp"]}\n"
            "${finding["visual_description"]}",
          ),
          isThreeLine: true,
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              _ApprovalIcon(state: state, findingId: id),
              const SizedBox(width: 8),
              ElevatedButton(
                onPressed: disabled ? null : () => mission.markFinding(id, "approve"),
                style: ElevatedButton.styleFrom(backgroundColor: Colors.green.shade600),
                child: const Text("APPROVE"),
              ),
              const SizedBox(width: 4),
              OutlinedButton(
                onPressed: disabled ? null : () => mission.markFinding(id, "dismiss"),
                child: const Text("DISMISS"),
              ),
            ],
          ),
        ),
      ),
    );
```

(The original `Container` already has the `Border(left: ...)` decoration — we extend it with the conditional fill color and conditional key.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend/flutter_dashboard && flutter test test/findings_panel_test.dart`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/flutter_dashboard/lib/widgets/findings_panel.dart frontend/flutter_dashboard/test/findings_panel_test.dart
git commit -m "feat(dashboard): highlight selected finding row from map tap"
```

---

### Task 7: Highlight selected drone row in Drone Status panel

**Files:**
- Modify: `frontend/flutter_dashboard/lib/widgets/drone_status_panel.dart:24-46`
- Test: `frontend/flutter_dashboard/test/drone_status_panel_test.dart` (extend)

- [ ] **Step 1: Write the failing test**

Append to `frontend/flutter_dashboard/test/drone_status_panel_test.dart` (inside `void main()`, after the last test):

```dart
testWidgets('selected drone row renders highlight key', (tester) async {
  final s = MissionState();
  s.applyStateUpdate({
    "type": "state_update",
    "timestamp": "2026-05-04T12:00:00.000Z",
    "contract_version": "1.0.0",
    "active_findings": [],
    "active_drones": [
      {
        "drone_id": "drone1",
        "agent_status": "active",
        "battery_pct": 87,
        "current_task": "survey_zone_a",
        "findings_count": 0,
        "validation_failures_total": 0,
        "position": {"lat": 34.0, "lon": -118.0, "alt": 50.0},
      },
    ],
  });

  await tester.pumpWidget(MaterialApp(
    home: ChangeNotifierProvider<MissionState>.value(
      value: s,
      child: const Scaffold(body: DroneStatusPanel()),
    ),
  ));
  await tester.pump();

  expect(find.byKey(const ValueKey('drone-row-highlight-drone1')),
      findsNothing);

  s.selectDrone('drone1');
  await tester.pump();

  expect(find.byKey(const ValueKey('drone-row-highlight-drone1')),
      findsOneWidget);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend/flutter_dashboard && flutter test test/drone_status_panel_test.dart`
Expected: FAIL — highlight key not present.

- [ ] **Step 3: Wrap each drone row in a conditionally-keyed `Container`**

In `frontend/flutter_dashboard/lib/widgets/drone_status_panel.dart`, replace the `itemBuilder` body (lines 20-47) with:

```dart
          itemBuilder: (_, i) {
            final d = mission.activeDrones[i] as Map<String, dynamic>;
            final droneId = d["drone_id"] as String? ?? "drone?";
            final perDrone = events[droneId] ?? const <Map<String, dynamic>>[];
            final isSelected = mission.selectedDroneId == droneId;
            return Container(
              key: isSelected
                  ? ValueKey('drone-row-highlight-$droneId')
                  : null,
              color: isSelected ? Colors.blue.withValues(alpha: 0.08) : null,
              child: ListTile(
                isThreeLine: true,
                title: Text("$droneId — ${d["agent_status"]}"),
                subtitle: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      "Battery ${d["battery_pct"]}% · "
                      "Task: ${d["current_task"] ?? "idle"} · "
                      "Findings: ${d["findings_count"]} · "
                      "Validation fails: ${d["validation_failures_total"]}",
                    ),
                    const SizedBox(height: 2),
                    Text(
                      _tickerLine(perDrone),
                      style: TextStyle(
                        fontSize: 11,
                        color: perDrone.isEmpty ? Colors.grey[600] : Colors.orange[800],
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend/flutter_dashboard && flutter test test/drone_status_panel_test.dart`
Expected: PASS.

- [ ] **Step 5: Run full Flutter test suite**

Run: `cd frontend/flutter_dashboard && flutter test`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/flutter_dashboard/lib/widgets/drone_status_panel.dart frontend/flutter_dashboard/test/drone_status_panel_test.dart
git commit -m "feat(dashboard): highlight selected drone row from map tap"
```

---

### Task 8: Close TODOs and open PR

- [ ] **Step 1: Update `TODOS.md`**

In `TODOS.md`, find the "Bridge lifespan teardown ordering (Phase 5+)" entry (line 78) and prepend `### ~~` and append `~~` to the heading, then add a `**CLOSED** — ...` body line. Apply the same closure pattern to "Map marker tap/hover interactivity" (line 51).

For "Bridge lifespan teardown ordering (Phase 5+)" replace its heading line with:
```markdown
### ~~Bridge lifespan teardown ordering (Phase 5+)~~ (closed in feat/bridge-shutdown-and-map-interactivity)
**CLOSED** — `frontend/ws_bridge/main.py` lifespan now signals stop on
the subscriber and awaits all three background tasks BEFORE calling
`subscriber.close()` (which calls `pubsub.aclose()`). New regression
test at `frontend/ws_bridge/tests/test_main_lifespan_teardown.py`.
Original entry retained below for historical context.
```

For "Map marker tap/hover interactivity" replace its heading line with:
```markdown
### ~~Map marker tap/hover interactivity~~ (closed in feat/bridge-shutdown-and-map-interactivity)
**CLOSED** — `MissionState` exposes `selectFinding`/`selectDrone`/
`clearSelection`. `MapPanel` wraps each marker in a `GestureDetector`
sized to a forgiving hit-radius. Findings and Drone Status panels
render a blue highlight on the selected row. Original entry retained
below for historical context.
```

- [ ] **Step 2: Commit TODO updates**

```bash
git add TODOS.md
git commit -m "docs(todos): close bridge shutdown ordering and map marker interactivity"
```

- [ ] **Step 3: Push and open PR**

```bash
git push
gh pr create --title "Bridge shutdown cleanup + map marker interactivity" --body "$(cat <<'EOF'
## Summary
- Bridge: split `RedisSubscriber.stop()` into `signal_stop()` + `close()` and reorder lifespan teardown so background tasks exit BEFORE `pubsub.aclose()`. Eliminates `RuntimeError: Event loop is closed` shutdown noise.
- Dashboard: tappable map markers cross-highlight rows in Findings and Drone Status panels via a `MissionState` selection API. Re-tapping the same marker deselects.

## Test plan
- [ ] `pytest frontend/ws_bridge/tests/ -m "not e2e"` green
- [ ] `pytest frontend/ws_bridge/tests/test_e2e_playwright.py -m e2e` green
- [ ] `cd frontend/flutter_dashboard && flutter test` green
- [ ] Manual: start the bridge, hit /health, kill — confirm no RuntimeError on stderr
- [ ] Manual: open dashboard with a multi-finding scenario, tap a marker, observe highlighted row
EOF
)"
```

Expected: PR opens, CI runs `bridge`, `flutter`, and `bridge_e2e` jobs.

---

## Self-Review

**1. Spec coverage:**
- TODOS.md:78 (bridge lifespan teardown) → Tasks 1, 2, 3.
- TODOS.md:51 (map marker tap/hover) → Tasks 4, 5, 6, 7.
- TODO closure breadcrumb → Task 8.

**2. Placeholder scan:** None — every step has full code or full commands. The `_seed()` helper used in `test_main_lifespan_teardown.py` would be a placeholder; instead I made the test use the real `create_app()` and swap `app.state.subscriber` after construction, which avoids needing a private seed helper.

**3. Type consistency:**
- `RedisSubscriber.signal_stop` (sync, no await) — same shape used in Tasks 1 and 2.
- `RedisSubscriber.close` (async) — same shape used in Tasks 1 and 2.
- `MissionState.selectedFindingId` / `selectedDroneId` getters — used in Tasks 4, 5, 6, 7.
- `selectFinding(String) → void`, `selectDrone(String) → void` — same signatures across Tasks 4, 5, 6, 7.
- Highlight key conventions: `findings-row-highlight-$id` (Task 6) and `drone-row-highlight-$droneId` (Task 7) — distinct namespaces, no collision with existing `map-drone-` / `map-finding-` / `approval-icon-*` keys.

**4. One open consistency note:** Task 5 changes the painter's projection logic to delegate to a top-level `_project` helper. The existing test `'renders one marker per active drone'` (`map_panel_test.dart:30`) finds markers by `ValueKey('map-drone-drone1')` — this still works because the new code preserves the same key on the `Positioned` wrapper. Verified by the explicit "Run existing map_panel_test.dart" step in Task 5 Step 5.
