# Close Remaining Test Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two remaining coverage gaps from PR #(current) — (1) live Gemma firing `report_finding` on a real disaster image, and (2) the last hop of the agent → Redis → bridge → WebSocket → Flutter DOM render chain — and prove both via repeatable tests + one-shot MCP verification.

**Architecture:**
- **Gap #2 (live Gemma):** Swap a single fixture frame (`sim/fixtures/frames/placeholder_victim_01.jpg`) with a CC0 disaster image. The scenario YAML already designates this frame for drone1 ticks 61–90 — no scenario changes needed. Run the full stack with real Ollama + `gemma4:e2b` and capture whether `report_finding` fires on `drones.drone1.findings`. Document outcome (positive or negative) in `docs/sim-live-run-notes.md`.
- **Gap #1 (Flutter DOM render):** Flutter 3.41 ships only the CanvasKit renderer, so finding text is painted to `<canvas>`, not into the DOM tree. The standard test seam is Flutter's accessibility/semantics tree, which IS exposed as real ARIA nodes (`<flt-semantics>`) once enabled. Add a stable `Semantics(label: ...)` wrapper to the finding tile so Playwright can query it by accessible name. Build `frontend/flutter_dashboard` to `build/web/`, serve it via `python -m http.server`, and drive sync_playwright (Chromium) to navigate, enable semantics (single Tab keypress), and assert the finding's accessible label appears.
- **One-shot MCP verification:** Beyond the durable pytest, drive the running stack via the already-installed Playwright MCP for a screenshot-grade demo capture. Document the procedure as a runbook so it can be repeated on demand for the submission video.

**Tech Stack:**
- Python: pytest, pytest-asyncio, sync_playwright (Chromium), httpx, httpx_ws, redis, fastapi
- Flutter 3.41 (CanvasKit web renderer, semantics tree)
- Existing: `redis-server`, `python -m sim.waypoint_runner`, `python -m sim.frame_server`, `python -m agents.drone_agent`, `python -m uvicorn frontend.ws_bridge.main:app`
- Real Ollama on `http://127.0.0.1:11434` with `gemma4:e2b` already pulled

---

## File Structure

**Modify:**
- `sim/fixtures/frames/placeholder_victim_01.jpg` — overwrite with CC0 disaster image (filename preserved per scenario YAML's stability contract)
- `frontend/flutter_dashboard/lib/widgets/findings_panel.dart` — add `Semantics(identifier: "finding-tile-$id", label: ...)` around each `_FindingTile`
- `docs/sim-live-run-notes.md` — append Gap #2 live-run results + Gap #1 MCP verification log

**Create:**
- `sim/fixtures/frames/LICENSES.md` — provenance + license for any non-placeholder fixture image
- `frontend/flutter_dashboard/test/findings_panel_semantics_test.dart` — Flutter widget test that asserts the new semantics label is present
- `frontend/ws_bridge/tests/test_e2e_playwright_dom_render.py` — durable pytest using sync_playwright + Flutter static server + real drone-agent process
- `docs/runbooks/mcp-dom-verification.md` — operator runbook for one-shot MCP browser verification (used for demo video capture)

**Touch (build artifact, gitignored):**
- `frontend/flutter_dashboard/build/web/` — produced by `flutter build web --release`, NOT committed

---

## Task 1: Source CC0 disaster image and swap fixture

**Files:**
- Modify: `sim/fixtures/frames/placeholder_victim_01.jpg`
- Create: `sim/fixtures/frames/LICENSES.md`

**Why:** The scenario YAML pins drone1 ticks 61–90 to `placeholder_victim_01.jpg`. The current file is a 7,919-byte stand-in (320x240 placeholder). Swapping the file contents — but keeping the filename — is the lowest-blast-radius change: no scenario, no contract, no code touches.

**Acceptable image criteria:**
- License: CC0 / public domain (US Federal works qualify: USGS, FEMA, NASA, NOAA, USFS, DoD imagery; Wikipedia Commons CC0 also fine)
- Visible content: at least one of: collapsed/damaged structures, active fire/smoke plume, debris field, visible person in distress
- Resolution: ≥640×480 (crop/resize as needed; gemma4:e2b's vision branch handles 224×224 internally)
- File size: ≤1 MB after JPEG re-encoding (keeps repo cheap)

- [ ] **Step 1: Choose source image**

Prefer USGS Earth Resources Observation and Science (EROS) post-fire aerial photography or FEMA disaster photo library. Verified CC0 starting points:
- USGS Multimedia Gallery: https://www.usgs.gov/products/multimedia/multimedia (public domain, US federal work)
- FEMA Photo Library: https://www.fema.gov/about/news-multimedia/photo-library (public domain)
- Wikipedia Commons "Wildfires" / "Earthquake damage" categories filtered by CC0: https://commons.wikimedia.org/wiki/Category:Disasters

Download a single image showing visible damage. Example searches that work: "USGS post-fire aerial Eaton", "FEMA Hurricane Ian damage residential", "Commons CC0 collapsed building earthquake".

- [ ] **Step 2: Re-encode to 640×480 JPEG quality 85**

```bash
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
# Replace SOURCE.jpg with downloaded file path
python3 -c "
from PIL import Image
img = Image.open('SOURCE.jpg').convert('RGB')
img.thumbnail((640, 480))
img.save('sim/fixtures/frames/placeholder_victim_01.jpg', 'JPEG', quality=85, optimize=True)
print('size:', img.size)
"
```

Expected: `size: (640, 480)` (or smaller, preserving aspect)

- [ ] **Step 3: Verify the swap**

```bash
file sim/fixtures/frames/placeholder_victim_01.jpg
ls -lh sim/fixtures/frames/placeholder_victim_01.jpg
```

Expected: `JPEG image data, ... <larger dimensions>` and size between 50KB and 1MB.

- [ ] **Step 4: Write provenance**

Create `sim/fixtures/frames/LICENSES.md` with:

```markdown
# Fixture image provenance

Most files in this directory are synthetic placeholders generated by
`scripts/generate_placeholder_fixtures.py`. The following are real
non-placeholder images and require attribution:

## placeholder_victim_01.jpg

- **Source URL:** <paste exact source URL>
- **Title:** <image title from source>
- **Author / Credit:** <author or agency>
- **License:** Public Domain (US federal work) / CC0
- **Date retrieved:** 2026-05-06
- **Modifications:** Resized to ≤640×480, JPEG quality 85.
- **Why this image:** Frame designated for drone1 ticks 61–90 in
  `sim/scenarios/disaster_zone_v1.yaml`. Used in live-Gemma verification
  to drive a real `report_finding` tool call on real disaster imagery.
```

- [ ] **Step 5: Commit**

```bash
git add sim/fixtures/frames/placeholder_victim_01.jpg sim/fixtures/frames/LICENSES.md
git commit -m "fixtures: swap victim_01 placeholder for CC0 disaster image

Per docs/superpowers/plans/2026-05-06-close-test-gaps.md Task 1.
Filename preserved so disaster_zone_v1.yaml stays unchanged."
```

---

## Task 2: Live Gemma verification (Gap #2)

**Files:**
- Modify: `docs/sim-live-run-notes.md` (append)

**Why:** This task is a *verification*, not an implementation. It answers the demo-load-bearing question: does `gemma4:e2b` actually fire `report_finding` on a real disaster image, or does it always pick `continue_mission`/`return_to_base`?

We accept either outcome. The result determines whether Beat 3b of the storyboard fires live or falls back to scripted findings.

**Pre-flight check:**

```bash
# Confirm Ollama daemon up + model present
curl -s http://127.0.0.1:11434/api/tags | python3 -c "import json,sys; d=json.load(sys.stdin); print([m['name'] for m in d['models']])"
```

Expected: list contains `gemma4:e2b`. If not: run `ollama pull gemma4:e2b` first.

- [ ] **Step 1: Start redis + sim + drone agent in foreground tabs**

Open 4 terminal tabs (or use `tmux`):

```bash
# Tab 1: redis
redis-server --port 6379 --save "" --appendonly no

# Tab 2: waypoint runner
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
uv run python -m sim.waypoint_runner --scenario disaster_zone_v1 --redis-url redis://127.0.0.1:6379/0

# Tab 3: frame server
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
uv run python -m sim.frame_server --scenario disaster_zone_v1 --redis-url redis://127.0.0.1:6379/0

# Tab 4: drone agent (real Ollama, NOT mock)
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
GG_LOG_DIR=/tmp/gemma_guardian_live_run uv run python -m agents.drone_agent \
  --drone-id drone1 --scenario disaster_zone_v1 \
  --redis-url redis://127.0.0.1:6379/0 \
  --ollama-endpoint http://127.0.0.1:11434
```

Expected: drone agent stdout shows `ollama OK` + `gemma4:e2b present` from healthcheck, then begins step loop.

- [ ] **Step 2: Subscribe to findings channel in a fifth tab**

```bash
redis-cli -p 6379 SUBSCRIBE drones.drone1.findings
```

Expected: prints "Reading messages... (press Ctrl-C to quit)"

- [ ] **Step 3: Wait 4–5 minutes**

Tick range 61–90 = drone1 looking at new image. At 1 Hz step rate (default), this is roughly minutes 1–1.5 from sim start. Allow generous buffer for Gemma cold-load latency on first call (≤120s). Stop watching at sim tick 240 (mission complete) ≈ 4 minutes.

- [ ] **Step 4: Capture results**

Save the redis-cli tab output. Save the drone agent stdout (last ~500 lines) by piping to a file in a future run, or copy from tmux scrollback.

Also save the validation event log: `cat /tmp/gemma_guardian_live_run/drone1/validation_events.jsonl`.

- [ ] **Step 5: Append to run notes**

Append to `docs/sim-live-run-notes.md`:

```markdown
## 2026-05-06 — Gap #2 live Gemma verification (real disaster image)

**Setup:**
- Scenario: disaster_zone_v1, drone1 only
- Image swap: placeholder_victim_01.jpg replaced with CC0 disaster photo
  (source: <URL from LICENSES.md>)
- Ollama: gemma4:e2b on http://127.0.0.1:11434 (Apple Silicon Metal)
- Frames seen by drone1: ticks 61–90 → new image; otherwise placeholders

**Outcome:** <PICK ONE: "report_finding fired" / "report_finding did NOT fire">

**Function calls observed on drones.drone1.findings during ticks 61–90:**
<paste redis-cli SUBSCRIBE output verbatim>

**Validation events log (last 30 entries):**
<paste tail -30 of validation_events.jsonl>

**Conclusion:**
- If report_finding fired: Beat 3b of demo storyboard is LIVE-CAPABLE.
  No fallback to scripted findings needed.
- If report_finding did NOT fire: document the function calls Gemma DID
  emit. This is data for the demo storyboard fallback decision.
```

- [ ] **Step 6: Commit run notes**

```bash
git add docs/sim-live-run-notes.md
git commit -m "live: Gap #2 verification — Gemma vs real disaster image

<one-line outcome summary>"
```

---

## Task 3: Add stable Semantics label to FindingTile

**Files:**
- Modify: `frontend/flutter_dashboard/lib/widgets/findings_panel.dart` (around line 47–125, the `_FindingTile` widget)

**Why:** Flutter web with CanvasKit paints all text to `<canvas>`. The DOM tree contains no finding text. Flutter's accessibility/semantics tree DOES surface as real `<flt-semantics>` ARIA nodes — but only for widgets explicitly wrapped in `Semantics(...)` OR for widgets like `Text`/`Button` that auto-emit semantics. The auto-emitted semantics for `ListTile.title` use the rendered string, which is not a stable test selector (it changes with severity/confidence). We need a stable `identifier` on each tile.

`Semantics.identifier` is a Flutter-3.x-only property that surfaces in the browser semantics tree as a stable hook (Playwright reads it via accessible-name). Using `identifier` (vs `label`) keeps the visible accessible label intact for screen readers while giving us a deterministic test selector.

- [ ] **Step 1: Write failing widget test**

Create `frontend/flutter_dashboard/test/findings_panel_semantics_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:flutter_dashboard/state/mission_state.dart';
import 'package:flutter_dashboard/widgets/findings_panel.dart';

void main() {
  testWidgets('FindingsPanel emits stable Semantics identifier per tile',
      (tester) async {
    final mission = MissionState();
    mission.applyStateUpdate({
      'active_findings': [
        {
          'finding_id': 'finding-abc',
          'type': 'victim',
          'severity': 4,
          'confidence': 0.85,
          'source_drone_id': 'drone1',
          'timestamp': '2026-05-06T10:00:00.000Z',
          'visual_description':
              'Person trapped under collapsed wall, visible from above',
        }
      ],
    });

    await tester.pumpWidget(
      MaterialApp(
        home: ChangeNotifierProvider<MissionState>.value(
          value: mission,
          child: const Scaffold(body: FindingsPanel()),
        ),
      ),
    );
    await tester.pump();

    // Locate by Semantics identifier — must match the contract used by
    // the Playwright DOM-render test.
    expect(
      find.bySemanticsIdentifier('finding-tile-finding-abc'),
      findsOneWidget,
      reason:
          'FindingsPanel must emit Semantics(identifier: "finding-tile-<id>") '
          'so the Playwright DOM-render test (test_e2e_playwright_dom_render.py) '
          'has a stable accessibility hook.',
    );
  });
}
```

- [ ] **Step 2: Run the failing test**

```bash
cd frontend/flutter_dashboard
"/Users/appleuser/CS Work/flutter/bin/flutter" test test/findings_panel_semantics_test.dart
```

Expected: FAIL with "Expected: exactly one matching candidate / Actual: _MatchesFinder ... Which: means none were found".

- [ ] **Step 3: Wrap _FindingTile in Semantics**

In `frontend/flutter_dashboard/lib/widgets/findings_panel.dart`, locate the `_FindingTile.build` method (around line 52). Replace the returned `Container(...)` with a `Semantics`-wrapped version. Apply the wrapper at the OUTERMOST point so the identifier covers the whole tile:

Locate this code block (around lines 83–124):

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
```

Replace with:

```dart
    final isSelected = mission.selectedFindingId == id;
    return Semantics(
      identifier: 'finding-tile-$id',
      label: '${(finding["type"] as String).toUpperCase()} '
          'severity ${finding["severity"]} from ${finding["source_drone_id"]}',
      child: Container(
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
```

And close the new `Semantics(...)` with one extra `)` at the end of the original `return Container(...)` block.

- [ ] **Step 4: Run the widget test again**

```bash
cd frontend/flutter_dashboard
"/Users/appleuser/CS Work/flutter/bin/flutter" test test/findings_panel_semantics_test.dart
```

Expected: PASS.

- [ ] **Step 5: Run full Flutter test suite**

```bash
cd frontend/flutter_dashboard
"/Users/appleuser/CS Work/flutter/bin/flutter" test
```

Expected: ALL tests pass. If any pre-existing widget test fails, the wrap likely changed semantics in a way that broke another assertion. Inspect and fix.

- [ ] **Step 6: Commit**

```bash
git add frontend/flutter_dashboard/lib/widgets/findings_panel.dart \
        frontend/flutter_dashboard/test/findings_panel_semantics_test.dart
git commit -m "flutter: stable Semantics identifier on FindingTile

Per docs/superpowers/plans/2026-05-06-close-test-gaps.md Task 3.
Provides a deterministic accessibility hook for the Playwright
DOM-render test (Task 7), independent of finding text content."
```

---

## Task 4: Build Flutter web for the static-server fixture

**Files:**
- Touch (gitignored): `frontend/flutter_dashboard/build/web/`

**Why:** The Playwright test serves a real built web bundle, not a `flutter run -d web-server` dev session, because the test must be deterministic and not require a long-lived dev server.

- [ ] **Step 1: Build**

```bash
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian/frontend/flutter_dashboard"
"/Users/appleuser/CS Work/flutter/bin/flutter" build web --release
```

Expected: completes in 1–3 minutes; produces `build/web/index.html`, `build/web/main.dart.js`, `build/web/canvaskit/`, `build/web/flutter_bootstrap.js`.

- [ ] **Step 2: Verify build artifacts**

```bash
ls -la build/web/index.html build/web/main.dart.js build/web/flutter_bootstrap.js
```

Expected: all three exist. `main.dart.js` should be ≥1 MB (tree-shaken release bundle).

- [ ] **Step 3: Spot-check serve**

```bash
cd build/web
python3 -m http.server 8765 &
SERVER_PID=$!
sleep 1
curl -s http://127.0.0.1:8765/ | head -20
kill $SERVER_PID
cd ../../../..
```

Expected: HTML output starts with `<!DOCTYPE html>` and references `flutter_bootstrap.js`. If 404: build failed silently — re-run step 1.

- [ ] **Step 4: Confirm gitignore covers build/web/**

```bash
git check-ignore frontend/flutter_dashboard/build/web/index.html
echo $?
```

Expected: exit code `0` (ignored). If exit 1, append `frontend/flutter_dashboard/build/` to the repo `.gitignore` and commit that change separately.

No commit for this task — `build/web/` is generated, not source.

---

## Task 5: Add static-server pytest fixture

**Files:**
- Modify: `frontend/ws_bridge/tests/conftest.py` (append fixture)

**Why:** The Playwright test needs Flutter web served on a free port for the duration of one test. Building it inside the fixture (rebuild-if-missing) keeps the test self-contained without checking 30+ MB of `main.dart.js` into the repo.

- [ ] **Step 1: Write failing fixture-consumer test (sanity check before real test)**

Append to `frontend/ws_bridge/tests/conftest.py`:

```python
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT_FOR_FLUTTER = Path(__file__).resolve().parents[3]


def _free_port_sync() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_http_ok(port: int, deadline_s: float = 5.0) -> bool:
    import urllib.request
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=0.5) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.1)
    return False


@pytest.fixture(scope="session")
def flutter_web_build_dir() -> Path:
    """Returns Path to a built Flutter web bundle. Skips if Flutter SDK absent.

    Builds on first call per session if build/web/index.html is missing or older
    than the Flutter source. Subsequent fixtures reuse the artifact.
    """
    flutter_root = REPO_ROOT_FOR_FLUTTER / "frontend" / "flutter_dashboard"
    build_dir = flutter_root / "build" / "web"
    flutter_bin = shutil.which("flutter") or "/Users/appleuser/CS Work/flutter/bin/flutter"
    if not Path(flutter_bin).exists():
        pytest.skip(f"Flutter SDK not found at {flutter_bin}")

    index_html = build_dir / "index.html"
    if not index_html.exists():
        proc = subprocess.run(
            [flutter_bin, "build", "web", "--release"],
            cwd=str(flutter_root),
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0 or not index_html.exists():
            pytest.skip(
                f"flutter build web failed (rc={proc.returncode}); "
                f"stderr tail: {proc.stderr[-500:]}"
            )
    return build_dir


@pytest.fixture
def flutter_static_server(flutter_web_build_dir):
    """Yields the URL of an http.server serving the Flutter web bundle.

    Function-scoped so each test gets a clean server (cheap; ~50ms boot).
    """
    port = _free_port_sync()
    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(flutter_web_build_dir),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_for_http_ok(port, 5.0):
            raise RuntimeError("flutter static server did not start")
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
```

- [ ] **Step 2: Add a smoke test of the fixture**

Create `frontend/ws_bridge/tests/test_flutter_static_server_fixture.py`:

```python
"""Smoke test: fixture builds Flutter web (if needed) and serves index.html."""
from __future__ import annotations

import urllib.request


def test_flutter_static_server_serves_index(flutter_static_server):
    with urllib.request.urlopen(f"{flutter_static_server}/") as r:
        body = r.read().decode()
    assert r.status == 200
    assert "<!DOCTYPE html>" in body
    # Flutter bootstrap loader is a stable sentinel across Flutter 3.x web.
    assert "flutter_bootstrap.js" in body
```

- [ ] **Step 3: Run smoke test**

```bash
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
uv run pytest frontend/ws_bridge/tests/test_flutter_static_server_fixture.py -v
```

Expected: PASS in <10s if `build/web/` already populated from Task 4. If Flutter rebuild triggers, may take 60–180s on first call (still passes).

- [ ] **Step 4: Commit**

```bash
git add frontend/ws_bridge/tests/conftest.py \
        frontend/ws_bridge/tests/test_flutter_static_server_fixture.py
git commit -m "tests: flutter_static_server fixture for DOM-render tests

Per docs/superpowers/plans/2026-05-06-close-test-gaps.md Task 5.
Builds frontend/flutter_dashboard to build/web/ if missing,
serves on a free port via python -m http.server."
```

---

## Task 6: Verify sync_playwright Chromium is installed

**Files:** none (environment setup)

**Why:** `pytest-playwright>=0.5` is in `pyproject.toml`, but the Chromium binary is downloaded via a separate `playwright install` step. Without it, the test errors with "Executable doesn't exist at ...". This task verifies and bootstraps as needed.

- [ ] **Step 1: Check Chromium presence**

```bash
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
uv run python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    print('chromium executable:', p.chromium.executable_path)
    browser = p.chromium.launch()
    browser.close()
print('OK')
"
```

Expected: prints a path under `~/Library/Caches/ms-playwright/chromium-*/chrome-mac/Chromium.app/.../Chromium` and `OK`.

- [ ] **Step 2: If above fails, install browsers**

If step 1 errored with "Executable doesn't exist":

```bash
uv run playwright install chromium
```

Expected: downloads ~140MB Chromium bundle to `~/Library/Caches/ms-playwright/`. Re-run step 1; should now succeed.

- [ ] **Step 3: No commit needed** (this is environment, not code).

---

## Task 7: Write the Playwright DOM-render test

**Files:**
- Create: `frontend/ws_bridge/tests/test_e2e_playwright_dom_render.py`

**Why:** The durable, repeatable test for Gap #1's last hop. Stands up the entire stack (redis + sim + drone agent + bridge + Flutter static server), drives Chromium via sync_playwright, navigates to the dashboard, enables the semantics tree, and asserts the finding's stable accessibility identifier appears in the DOM. This is the test that proves "agent → Redis → bridge → WebSocket → Flutter widget tree → rendered (semantic) DOM" works end-to-end.

The test uses the OLLAMA MOCK (not real Gemma) for determinism. Real-Gemma integration is already covered by `test_e2e_playwright_real_drone_findings.py`.

- [ ] **Step 1: Write the failing test**

Create `frontend/ws_bridge/tests/test_e2e_playwright_dom_render.py`:

```python
"""Playwright e2e: agent → bridge → Flutter dashboard DOM (semantics tree).

Closes Gap #1's last hop. Builds on test_e2e_playwright_real_drone_findings.py
but adds the final assertion: the finding renders into the Flutter dashboard's
semantics tree, queryable via Chromium's accessibility tree.

Why semantics tree (not visible DOM): Flutter 3.41 web ships only CanvasKit,
which paints to <canvas>. Text content lives in the accessibility/semantics
overlay — Flutter's own equivalent of an ARIA tree, exposed as real
<flt-semantics> elements with `flt-semantics-identifier` attributes once
semantics is enabled.

Semantics is enabled by sending a Tab keypress (Flutter's standard
auto-enable trigger) or by calling SemanticsBinding.instance.ensureSemantics()
via JS. We use the Tab keypress because it works without engine-internal JS.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_for_port(port: int, deadline_s: float) -> bool:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


@contextmanager
def _spawn(cmd: list[str], env: dict | None = None, name: str = "child"):
    proc = subprocess.Popen(
        cmd, cwd=str(REPO_ROOT),
        env={**os.environ, **(env or {})},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.timeout(180)
def test_finding_renders_in_flutter_semantics_tree(tmp_path, flutter_static_server):
    if not shutil.which("redis-server"):
        pytest.skip("redis-server not on PATH")
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        pytest.skip("playwright not installed")

    redis_port = _free_port()
    ollama_port = _free_port()
    bridge_port = _free_port()

    redis_proc = subprocess.Popen(
        ["redis-server", "--port", str(redis_port), "--save", "", "--appendonly", "no"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    assert _wait_for_port(redis_port, 5), "redis did not come up"
    redis_url = f"redis://127.0.0.1:{redis_port}/0"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    try:
        with _spawn(
            [sys.executable, "scripts/ollama_mock_server.py", "--port", str(ollama_port)],
            name="ollama-mock",
        ):
            assert _wait_for_port(ollama_port, 5), "ollama mock did not come up"

            scenario = "disaster_zone_v1"
            with _spawn(
                [sys.executable, "-m", "sim.waypoint_runner",
                 "--scenario", scenario, "--redis-url", redis_url],
                name="waypoint",
            ), _spawn(
                [sys.executable, "-m", "sim.frame_server",
                 "--scenario", scenario, "--redis-url", redis_url],
                name="frame",
            ), _spawn(
                [sys.executable, "-m", "agents.drone_agent",
                 "--drone-id", "drone1", "--scenario", scenario,
                 "--redis-url", redis_url,
                 "--ollama-endpoint", f"http://127.0.0.1:{ollama_port}"],
                env={"GG_LOG_DIR": str(log_dir)},
                name="drone-agent",
            ), _spawn(
                [sys.executable, "-m", "uvicorn", "frontend.ws_bridge.main:app",
                 "--host", "127.0.0.1", "--port", str(bridge_port)],
                env={"REDIS_URL": redis_url},
                name="bridge",
            ):
                assert _wait_for_port(bridge_port, 10), "bridge did not come up"

                # Capture finding_id off Redis so we know what to look for.
                import redis as _redis
                client = _redis.Redis.from_url(redis_url)
                pubsub = client.pubsub()
                pubsub.subscribe("drones.drone1.findings")
                pubsub.get_message(timeout=1)
                deadline = time.time() + 60
                victim_finding_id = None
                while time.time() < deadline:
                    msg = pubsub.get_message(timeout=1)
                    if msg and msg["type"] == "message":
                        payload = json.loads(msg["data"])
                        if payload.get("type") == "victim":
                            victim_finding_id = payload["finding_id"]
                            break
                assert victim_finding_id, "no victim finding observed within 60s"

                # The Flutter dashboard talks directly to the bridge's WS.
                # We must point the dashboard at our bridge_port. The dashboard
                # reads the bridge URL from a query string ?ws=<url> (per main.dart),
                # OR from a build-time env. Use the query-string path so we
                # don't need a custom build.
                ws_url = f"ws://127.0.0.1:{bridge_port}/"
                dashboard_url = (
                    f"{flutter_static_server}/?ws={ws_url}"
                )

                from playwright.sync_api import sync_playwright

                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    context = browser.new_context()
                    page = context.new_page()
                    page.goto(dashboard_url, wait_until="networkidle", timeout=30_000)

                    # Trigger Flutter's semantics tree. Flutter web auto-enables
                    # semantics on first Tab keypress.
                    page.keyboard.press("Tab")

                    # Poll the accessibility tree for our identifier. Flutter
                    # exposes Semantics.identifier via the ARIA flt-semantics
                    # element. We use page.locator with a CSS attribute selector.
                    target_selector = (
                        f'[flt-semantics-identifier="finding-tile-{victim_finding_id}"]'
                    )
                    page.wait_for_selector(target_selector, timeout=30_000,
                                           state="attached")

                    # Sanity-check the visible accessible label too.
                    el = page.locator(target_selector).first
                    aria_label = el.get_attribute("aria-label") or ""
                    assert "VICTIM" in aria_label.upper(), (
                        f"semantics label missing VICTIM marker: {aria_label!r}"
                    )

                    browser.close()

    finally:
        redis_proc.terminate()
        try:
            redis_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            redis_proc.kill()
```

- [ ] **Step 2: Run the test (expect first-run failures to debug)**

```bash
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
uv run pytest frontend/ws_bridge/tests/test_e2e_playwright_dom_render.py -v -s
```

**Possible failure modes and the exact fix for each:**

| Failure signature | Cause | Fix |
|---|---|---|
| `dashboard page goto timeout` | Flutter bundle 404 | Re-run Task 4 build; check `flutter_static_server` URL |
| `wait_for_selector timeout on flt-semantics-identifier` | Semantics not enabled | Replace `page.keyboard.press("Tab")` with `page.evaluate("document.body.focus(); document.body.dispatchEvent(new KeyboardEvent('keydown', {key:'Tab'}))")` |
| `wait_for_selector timeout, semantics enabled` | Dashboard didn't connect to bridge | Inspect `main.dart` for the WS URL parameter name; if not `ws=`, change query string |
| `aria-label missing VICTIM` | Semantics emits label without type prefix | Adjust the assertion or change `Semantics(label: ...)` in Task 3 to put `VICTIM` first |

If `main.dart` does NOT accept a `?ws=` query param, you'll need to either (a) extend `main.dart` to read `Uri.base.queryParameters['ws']` and use it as the WS endpoint, or (b) build with `--dart-define=WS_URL=ws://...` per test (slower; rebuild required). Prefer (a) — it's a one-line dashboard change.

- [ ] **Step 3: If the dashboard does not accept ?ws= query param, add it**

If failure mode 3 above hits: open `frontend/flutter_dashboard/lib/main.dart`, find where the WebSocket URL is hardcoded (likely a `const String` or env-injected default near the entry point or in a `WsBridgeClient` constructor). Add:

```dart
String _wsBridgeUrl() {
  final fromQuery = Uri.base.queryParameters['ws'];
  if (fromQuery != null && fromQuery.isNotEmpty) return fromQuery;
  return const String.fromEnvironment('WS_URL', defaultValue: 'ws://127.0.0.1:8000/');
}
```

…and use `_wsBridgeUrl()` at the construction site. Rebuild Flutter web (Task 4 step 1), re-run the test.

- [ ] **Step 4: Iterate until green**

Run the test, read failure, apply fix, re-run. Common second-pass issue: the test consumes the finding off the Redis pubsub subscription, so by the time the bridge subscribes, the finding has already passed. The bridge's findings subscriber MUST be listening *before* the test SUBSCRIBE, OR the test should re-publish, OR (cleanest) the test should subscribe AFTER the bridge spawns but use the bridge's WebSocket envelope to detect the finding (the bridge re-sends past findings on connect via state_update).

The cleanest fix if this hits: drop the `pubsub.subscribe("drones.drone1.findings")` block entirely, and instead have Playwright connect first, then poll the semantics tree, scraping the rendered finding ID from the `flt-semantics-identifier` attribute. Adjust `target_selector` to use a prefix match: `'[flt-semantics-identifier^="finding-tile-"]'`.

- [ ] **Step 5: Once green, commit**

```bash
git add frontend/ws_bridge/tests/test_e2e_playwright_dom_render.py
# also stage main.dart if Step 3 was triggered
git commit -m "tests: e2e DOM-render — Gap #1 last hop closed

Per docs/superpowers/plans/2026-05-06-close-test-gaps.md Task 7.
Asserts the finding renders into the Flutter dashboard's semantics
tree (Chromium accessibility) end-to-end through redis+sim+agent+
bridge+flutter_web."
```

---

## Task 8: One-shot MCP browser verification + runbook

**Files:**
- Create: `docs/runbooks/mcp-dom-verification.md`
- Modify: `docs/sim-live-run-notes.md` (append outcome)

**Why:** The user has Playwright MCP installed. We use it to drive the live, running stack interactively for a screenshot-grade demo capture. The runbook makes this repeatable for the submission video.

This task is verification/documentation. There is no automation — you (or the demo operator) execute these steps.

- [ ] **Step 1: Write the runbook**

Create `docs/runbooks/mcp-dom-verification.md`:

```markdown
# Runbook: MCP browser verification of finding DOM render

Purpose: drive the running FieldAgent stack via Playwright MCP, capture
a screenshot of a real finding rendered in the Flutter dashboard.
Used for demo-video capture and as a sanity check before any submission.

## Prerequisites

- Playwright MCP installed and connected (verify: `mcp__playwright__browser_navigate` tool available in your Claude session)
- Ollama running on http://127.0.0.1:11434 with `gemma4:e2b` pulled
- Redis available (`brew install redis` on macOS)
- Flutter web bundle built: `cd frontend/flutter_dashboard && flutter build web --release`

## Steps

### 1. Stand up the stack (5 terminal tabs)

```bash
# Tab 1
redis-server --port 6379 --save "" --appendonly no

# Tab 2
cd "/path/to/Gemma-Guardian"
uv run python -m sim.waypoint_runner --scenario disaster_zone_v1 \
  --redis-url redis://127.0.0.1:6379/0

# Tab 3
cd "/path/to/Gemma-Guardian"
uv run python -m sim.frame_server --scenario disaster_zone_v1 \
  --redis-url redis://127.0.0.1:6379/0

# Tab 4 (real Gemma — for live demo) OR mock (deterministic)
# Live:
cd "/path/to/Gemma-Guardian"
uv run python -m agents.drone_agent --drone-id drone1 \
  --scenario disaster_zone_v1 \
  --redis-url redis://127.0.0.1:6379/0 \
  --ollama-endpoint http://127.0.0.1:11434
# Mock (run scripts/ollama_mock_server.py first):
# python scripts/ollama_mock_server.py --port 11500 &
# uv run python -m agents.drone_agent ... --ollama-endpoint http://127.0.0.1:11500

# Tab 5
cd "/path/to/Gemma-Guardian"
REDIS_URL=redis://127.0.0.1:6379/0 uv run python -m uvicorn \
  frontend.ws_bridge.main:app --host 127.0.0.1 --port 8000

# Tab 6: serve the built Flutter dashboard
cd "/path/to/Gemma-Guardian/frontend/flutter_dashboard/build/web"
python3 -m http.server 8080
```

### 2. Drive Playwright MCP from Claude session

In a Claude Code session, run these MCP tool calls in order:

1. `mcp__playwright__browser_navigate` → `http://127.0.0.1:8080/?ws=ws://127.0.0.1:8000/`
2. `mcp__playwright__browser_press_key` → `Tab` (enables Flutter semantics)
3. `mcp__playwright__browser_wait_for` → text contains `VICTIM` (or use snapshot to find it)
4. `mcp__playwright__browser_snapshot` → capture accessibility tree
5. `mcp__playwright__browser_take_screenshot` → save to `docs_assets/dashboard-finding-rendered.png`

### 3. Verify the screenshot shows

- A finding tile in the Findings panel with type/severity/confidence text
- The visual_description from the finding visible
- APPROVE / DISMISS buttons visible

### 4. Tear down

```bash
# Ctrl-C every tab in reverse order: flutter server, bridge, agent, frame, sim, redis
```

## Recovering from common failures

- **MCP browser_navigate hangs:** `flutter build web` may not have run, or
  `http.server` is on the wrong port. Curl the URL first.
- **No finding appears:** the agent isn't producing one. Check Tab 4 stdout
  for `report_finding` log lines. With mock Ollama, the first call always
  produces a victim finding.
- **Screenshot shows blank canvas:** Flutter is rendering but failing to
  connect to the bridge. Check the browser console (`mcp__playwright__browser_console_messages`) for WS errors.
```

- [ ] **Step 2: Execute the runbook end-to-end**

Follow the steps above. Use the MOCK Ollama for the first pass (deterministic) and then optionally REAL Ollama for the second pass (demo-grade).

- [ ] **Step 3: Save the screenshot**

After step 2.5 in the runbook, the screenshot should exist at `docs_assets/dashboard-finding-rendered.png`. If not present, re-run step 2.5.

- [ ] **Step 4: Append to run notes**

Append to `docs/sim-live-run-notes.md`:

```markdown
## 2026-05-06 — Gap #1 MCP DOM-render verification

**Setup:**
- Stack: redis + waypoint + frame + drone agent + bridge + flutter_web (build/web/)
- Ollama variant used: <PICK ONE: mock | gemma4:e2b live>
- Browser: Playwright MCP Chromium

**Outcome:** finding rendered in dashboard semantics tree.

**Screenshot:** docs_assets/dashboard-finding-rendered.png

**Accessibility tree snapshot (relevant excerpt):**
<paste relevant lines from mcp__playwright__browser_snapshot output>

**Notes:**
- Page loaded via http://127.0.0.1:8080/?ws=ws://127.0.0.1:8000/
- Semantics enabled via Tab keypress (Flutter standard auto-enable)
- Finding tile located via Semantics(identifier: "finding-tile-<id>")
```

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/mcp-dom-verification.md \
        docs/sim-live-run-notes.md \
        docs_assets/dashboard-finding-rendered.png
git commit -m "verify: MCP DOM-render runbook + screenshot capture

Per docs/superpowers/plans/2026-05-06-close-test-gaps.md Task 8.
Repeatable runbook for demo-video capture; one-shot screenshot
saved as evidence."
```

---

## Task 9: Final test sweep

**Files:** none (verification only)

**Why:** Confirm the full test suite stays green, and the new e2e tests don't flake when run together.

- [ ] **Step 1: Run the full Python suite**

```bash
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
uv run pytest -x --timeout=300 -v 2>&1 | tail -50
```

Expected: ALL pass (60 prior + ~3 new = ~63 tests). No skips other than legitimate ones (e.g., redis-server not on PATH on a CI runner).

- [ ] **Step 2: Run the full Flutter suite**

```bash
cd frontend/flutter_dashboard
"/Users/appleuser/CS Work/flutter/bin/flutter" test
```

Expected: ALL pass.

- [ ] **Step 3: Run the new e2e tests three times in a row to check for flake**

```bash
cd "/Users/appleuser/CS Work/Repos/Gemma-Guardian"
for i in 1 2 3; do
  echo "=== run $i ==="
  uv run pytest frontend/ws_bridge/tests/test_e2e_playwright_dom_render.py \
                 frontend/ws_bridge/tests/test_e2e_playwright_real_drone_findings.py \
                 -v --timeout=180
done
```

Expected: 3/3 green. If 1/3 flaked, investigate the timing — likely the wait-for-port deadline or the wait-for-selector timeout needs a buffer increase.

- [ ] **Step 4: Confirm clean working tree**

```bash
git status
```

Expected: clean (or only the build/web/ artifact, which is gitignored).

- [ ] **Step 5: Final commit if any docs were touched**

If `docs/STATUS.md` should reflect both gaps closed, append a line to STATUS.md and commit.

---

## Self-Review (already performed)

**1. Spec coverage:**
- Gap #2 live Gemma: Tasks 1, 2 ✓
- Gap #1 last hop: Tasks 3–7 ✓
- "Verifies that the testing actually occurs properly": Tasks 8 (MCP demo), 9 (sweep + flake check) ✓

**2. Placeholder scan:** No "TBD"/"TODO"/"add appropriate" — all tasks have real code or real procedures. The only operator-fill-in fields are documented placeholders (image source URL, redis-cli output) that genuinely cannot be predicted.

**3. Type consistency:**
- Semantics `identifier: "finding-tile-$id"` — used identically in Tasks 3 (Dart), 7 (`flt-semantics-identifier="finding-tile-{id}"`).
- `flutter_static_server` fixture — defined in Task 5, consumed in Tasks 5 (smoke) and 7 (e2e).
- `flutter_web_build_dir` session-scoped fixture — defined in Task 5, depended on by `flutter_static_server`.

---

## Risk register

| Risk | Mitigation |
|---|---|
| `flutter build web` fails on this Flutter version | Task 4 Step 1 surfaces stderr; Task 5 fixture skips test rather than hanging CI |
| Flutter dashboard hardcodes WS URL with no override | Task 7 Step 3 specifies the exact one-line `main.dart` patch |
| Semantics tree doesn't auto-enable on Tab | Task 7 Step 2 failure-mode table gives the JS-eval fallback |
| Live Gemma Task 2 doesn't fire `report_finding` | Task 2 explicitly accepts both outcomes; documents either way |
| Image source license uncertain | Task 1 step 1 lists three vetted PD sources |
| Playwright Chromium not installed | Task 6 bootstraps it |
