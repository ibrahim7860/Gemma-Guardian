# Playwright UI-Interaction Tests via Flutter Web a11y Semantics

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Playwright tests that drive the actual Flutter dashboard UI (clicks, typing, dropdown changes) instead of bypassing the UI by sending JSON over a side-channel WebSocket. Today's `bridge_e2e` job has 9 tests, all of which use Playwright as a network transport — none touch UI affordances. This plan adds 4 UI-driven tests that prove "operator clicks Approve → bridge sees finding_approval" and "operator picks Spanish + types + clicks Translate → bridge sees operator_command with language=es."

**Architecture:** Flutter web is canvas-rendered, but `frontend/flutter_dashboard/lib/main.dart:27` calls `SemanticsBinding.instance.ensureSemantics()`, which makes Flutter inject a parallel DOM tree of `<flt-semantics>` elements with `role` and `aria-label` attributes for every visible widget. Playwright can find buttons by text content (`flt-semantics[role=button]:has-text("APPROVE")`), the language dropdown by role, and the text input by aria-label.

**Verified by probe (2026-05-04):** loading the dashboard headless surfaces `flt-semantics` nodes for `TRANSLATE`, `CLEAR`, `English` (dropdown trigger), and an `<input aria-label="Type a command...">`. The findings panel exposes `APPROVE` and `DISMISS` buttons per finding once findings are populated. The technique works.

**Tech Stack:** Playwright chromium (already in CI via `bridge_e2e`), Flutter web a11y semantics (already wired in main.dart), the existing `pipeline` fixture (provides redis + bridge + flutter http.server + producer subprocesses).

---

## Why now

The user asked: "did you actually look at the UI and interact with it?" Honest answer: no, the previous 5 tests use Playwright purely as a JSON transport. That validates the network/protocol layer but not whether clicking "Approve" on a finding card actually fires `finding_approval`. With the demo deadline 14 days away, the dashboard's clickable affordances are exactly what judges will see — they need real-browser interaction coverage, not just JSON-shape assertions.

---

## Out of scope

- **Visual regression testing** (pixel-diff screenshots). Flutter web canvas-renders, so pixel diffs are noisy across runs. The a11y tree is the stable surface.
- **Touch / mobile gestures.** Demo runs in a desktop browser.
- **Map panel interaction.** Markers are read-only per existing TODOS.
- **Snackbar text assertions.** Flutter's snackbar may not surface in the a11y tree reliably; if it does we'll cover it, if it doesn't we'll skip without retrying.
- **Spawning a `bridge_e2e_ui` job separately from `bridge_e2e`.** The new tests live in the same file with the `e2e` mark, so they ride the existing CI job.
- **Migrating the existing 9 network-only tests to UI-driven.** Those still have value as protocol regression — they catch bridge-side breakage that the UI tests can't see (e.g., finding_approval works at the UI but bridge silently swallows the publish).

---

## File Structure

**Modify:**
- `frontend/ws_bridge/tests/test_e2e_playwright.py` — add UI helpers + 4 new UI-interaction tests

**No other files touched.** No new dependencies, no new CI job, no widget changes.

---

## Testing Strategy

The 4 new tests complement (not replace) the existing 9. Each verifies a different layer:

| Layer | Tests today (network-only) | Tests this plan adds (UI-driven) |
|---|---|---|
| Bridge JSON shape | 9 | — |
| UI affordance fires correct frame | — | 3 |
| UI state transition after server ack | — | 1 |

Per-test, the assertion shape:
1. Open the dashboard via Playwright.
2. Capture all WS frames the Flutter app sends (via `page.on("websocket")` + `framesent`).
3. Drive the UI (click, type, select dropdown).
4. Assert the captured frames include the expected operator-action frame.
5. Optionally drive the bridge to send back an ack (via the side-channel the existing tests use), then assert the UI updated.

---

## Task 1: Helper for capturing the Flutter app's outbound WS frames

**Files:**
- Modify: `frontend/ws_bridge/tests/test_e2e_playwright.py`

The existing `_capture_ws_frames` only listens for `framereceived` (frames the bridge sends to the client). For UI tests we need `framesent` (frames the Flutter app sends to the bridge, in response to clicks).

- [ ] **Step 1: Add a `_capture_app_outbound_frames` helper**

```python
def _capture_app_outbound_frames(
    page,
    bridge_port: int,
) -> List[str]:
    """Attach a WS listener that buffers every outbound frame the Flutter
    app sends to the bridge. Returns a live list — keep using ``page`` and
    new frames append automatically.

    The Flutter app opens its own WS to the bridge on load. We filter by
    ``bridge_port`` so unrelated WS connections (e.g., devtools) are
    ignored.
    """
    sent: List[str] = []

    def on_websocket(ws):
        if str(bridge_port) not in ws.url:
            return
        ws.on(
            "framesent",
            lambda payload: sent.append(
                payload if isinstance(payload, str) else payload.decode("utf-8", "replace")
            ),
        )

    page.on("websocket", on_websocket)
    return sent
```

The helper must be attached BEFORE `page.goto(...)` so the listener is live when the Flutter app opens its WS.

- [ ] **Step 2: Add a `_wait_for_frame_matching` helper**

```python
def _wait_for_frame_matching(
    frames: List[str],
    predicate: Callable[[Dict[str, Any]], bool],
    *,
    timeout_s: float,
    poll_ms: int = 100,
) -> Dict[str, Any]:
    """Poll the live ``frames`` list until one parses-as-JSON and matches
    ``predicate``. Returns the matching frame. Raises AssertionError on
    timeout.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        for raw in frames:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if predicate(msg):
                return msg
        time.sleep(poll_ms / 1000.0)
    raise AssertionError(
        f"no frame in {len(frames)} captured frames matched predicate within {timeout_s}s"
    )
```

---

## Task 2: UI test — click APPROVE on a finding tile fires `finding_approval`

**Files:**
- Modify: `frontend/ws_bridge/tests/test_e2e_playwright.py`

- [ ] **Step 1: Write `test_ui_approve_button_fires_finding_approval`**

The dance:
1. Attach `_capture_app_outbound_frames` listener to capture the Flutter WS sends.
2. `page.goto(flutter_url)`.
3. Wait for at least one finding tile to render. Findings panel renders an `APPROVE` button per finding once `mission.activeFindings` populates from the producer's stream. Wait via `page.locator('flt-semantics[role="button"]:has-text("APPROVE")').first.wait_for(state="visible", timeout=20000)`.
4. Click that first APPROVE button.
5. Assert the captured outbound frames include one with `type="finding_approval"`, `action="approve"`, valid `finding_id` matching `^f_drone\d+_\d+$`.
6. Confirm the Flutter app sent EXACTLY one such frame in response to the click (no double-click bug).

Test code:

```python
def test_ui_approve_button_fires_finding_approval(pipeline: Dict[str, Any]) -> None:
    """Clicking 'APPROVE' on a finding tile must produce a single
    finding_approval frame on the Flutter app's WebSocket to the bridge.

    This is the operator's primary demo action: see a victim, approve.
    The network-layer test covers the bridge's handling of an inbound
    finding_approval; this test covers that the actual UI button does
    fire that frame in the first place.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            sent_frames = _capture_app_outbound_frames(page, pipeline["bridge_port"])
            page.goto(pipeline["flutter_url"], wait_until="domcontentloaded", timeout=15000)
            # Wait for the producer's first finding to land in the panel.
            approve_btn = page.locator('flt-semantics[role="button"]:has-text("APPROVE")').first
            approve_btn.wait_for(state="visible", timeout=20000)
            approve_btn.click()
            # Allow the click handler to fire and the WS send to flush.
            page.wait_for_timeout(500)
            # Assert exactly one finding_approval frame was sent.
            approvals = []
            for raw in sent_frames:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "finding_approval":
                    approvals.append(msg)
            assert len(approvals) == 1, (
                f"expected exactly one finding_approval frame; got {len(approvals)}: {approvals!r}"
            )
            ap = approvals[0]
            assert ap["action"] == "approve"
            assert re.match(r"^f_drone\d+_\d+$", ap["finding_id"]), (
                f"finding_id must match schema regex; got {ap['finding_id']!r}"
            )
            assert "command_id" in ap and ap["command_id"]
        finally:
            browser.close()
```

(Add `import re` near the top if not already present.)

---

## Task 3: UI test — language dropdown + text input + TRANSLATE click fires `operator_command`

**Files:**
- Modify: `frontend/ws_bridge/tests/test_e2e_playwright.py`

- [ ] **Step 1: Write `test_ui_translate_button_fires_operator_command_with_language`**

```python
def test_ui_translate_button_fires_operator_command_with_language(pipeline: Dict[str, Any]) -> None:
    """Pick Spanish in the dropdown, type a command, click TRANSLATE.
    The Flutter app must send an operator_command frame with
    language='es' and the typed raw_text.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            sent_frames = _capture_app_outbound_frames(page, pipeline["bridge_port"])
            page.goto(pipeline["flutter_url"], wait_until="domcontentloaded", timeout=15000)
            # The text input is a real <input> with aria-label="Type a command..."
            text_input = page.locator('input[aria-label="Type a command..."]').first
            text_input.wait_for(state="visible", timeout=15000)
            # Open the language dropdown by clicking its trigger (currently shows "English").
            page.locator('flt-semantics[role="button"]:has-text("English")').first.click()
            # Pick Spanish from the popup. Flutter renders dropdown items as buttons.
            page.locator('flt-semantics[role="button"]:has-text("Spanish")').first.click()
            text_input.fill("recall drone1 to base")
            # TRANSLATE button must now be enabled (text is non-empty).
            translate_btn = page.locator('flt-semantics[role="button"]:has-text("TRANSLATE")').first
            translate_btn.click()
            page.wait_for_timeout(500)
            cmd = _wait_for_frame_matching(
                sent_frames,
                lambda m: m.get("type") == "operator_command",
                timeout_s=5.0,
            )
            assert cmd["language"] == "es", f"language must be 'es'; got {cmd['language']!r}"
            assert cmd["raw_text"] == "recall drone1 to base"
            assert "command_id" in cmd and cmd["command_id"]
        finally:
            browser.close()
```

---

## Task 4: UI test — DISMISS button fires `finding_approval` with action=dismiss

**Files:**
- Modify: `frontend/ws_bridge/tests/test_e2e_playwright.py`

This proves the dismiss path works at the UI level (not just approve). It's a near-mirror of Task 2 but asserts `action="dismiss"`.

- [ ] **Step 1: Write `test_ui_dismiss_button_fires_finding_approval_with_dismiss_action`**

```python
def test_ui_dismiss_button_fires_finding_approval_with_dismiss_action(pipeline: Dict[str, Any]) -> None:
    """Clicking 'DISMISS' on a finding tile fires finding_approval with
    action='dismiss'. Sister test to APPROVE — covers the negative
    operator action.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            sent_frames = _capture_app_outbound_frames(page, pipeline["bridge_port"])
            page.goto(pipeline["flutter_url"], wait_until="domcontentloaded", timeout=15000)
            dismiss_btn = page.locator('flt-semantics[role="button"]:has-text("DISMISS")').first
            dismiss_btn.wait_for(state="visible", timeout=20000)
            dismiss_btn.click()
            page.wait_for_timeout(500)
            dismiss = _wait_for_frame_matching(
                sent_frames,
                lambda m: (
                    m.get("type") == "finding_approval"
                    and m.get("action") == "dismiss"
                ),
                timeout_s=5.0,
            )
            assert re.match(r"^f_drone\d+_\d+$", dismiss["finding_id"])
            assert "command_id" in dismiss and dismiss["command_id"]
        finally:
            browser.close()
```

---

## Task 5: UI test — UI shows pending spinner immediately after click

**Files:**
- Modify: `frontend/ws_bridge/tests/test_e2e_playwright.py`

This verifies the UI's optimistic-update path — clicking APPROVE should disable the button (and show a spinner via `_ApprovalIcon` with `ApprovalState.pending`). The button gets `onPressed: null` when `disabled = state == ApprovalState.pending`, so Playwright should observe the button becoming non-clickable.

- [ ] **Step 1: Write `test_ui_approve_disables_button_after_click`**

```python
def test_ui_approve_disables_button_after_click(pipeline: Dict[str, Any]) -> None:
    """After clicking APPROVE, the button must visually transition to a
    disabled state (per MissionState's optimistic update — finding moves
    to ApprovalState.pending which gates onPressed: null).

    This is the operator-feedback contract: judges will mash the button
    and we don't want it to fire 5 times before the bridge ack arrives.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            sent_frames = _capture_app_outbound_frames(page, pipeline["bridge_port"])
            page.goto(pipeline["flutter_url"], wait_until="domcontentloaded", timeout=15000)
            approve_btn = page.locator('flt-semantics[role="button"]:has-text("APPROVE")').first
            approve_btn.wait_for(state="visible", timeout=20000)
            approve_btn.click()
            # Click again immediately. If the button is properly disabled, the
            # second click is a no-op and we should still see exactly ONE
            # finding_approval frame.
            approve_btn.click(timeout=2000, force=False)
            page.wait_for_timeout(800)
            approvals = []
            for raw in sent_frames:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "finding_approval" and msg.get("action") == "approve":
                    approvals.append(msg)
            assert len(approvals) == 1, (
                f"button must disable after first click; got {len(approvals)} approvals"
            )
        finally:
            browser.close()
```

Note: this test deliberately races the click with the disable. If Flutter web's a11y layer doesn't reflect the disabled state quickly enough, the second click might still register at the DOM level but should be no-op'd by Flutter's hit-testing. Worth noting if it flakes — if so, the fallback assertion is that two clicks produce exactly one frame, which is the contract that matters.

---

## Task 6: Run locally and push

- [ ] **Step 1: Run all 14 (existing 9 + new 5... wait, 4 here) tests locally**

Wait — Tasks 2-5 add 4 tests. Total file then has 9 + 4 = 13 tests + 1 SKIP. Let me count: 4 baseline + 5 Phase 4 outbound from PR #8 + 4 from this plan = 13 + 1 SKIP = 14 collected. Update this number when you run it.

```bash
PYTHONPATH=. python3 -m pytest frontend/ws_bridge/tests/test_e2e_playwright.py -m e2e -v
```
Expected: 13 passed, 1 skipped. Runtime should be under 30s on warm cache.

- [ ] **Step 2: Commit and push**

```bash
git add frontend/ws_bridge/tests/test_e2e_playwright.py
git commit -m "test(e2e): add UI-interaction Playwright tests via Flutter web a11y

Four new tests drive the actual dashboard UI through Flutter web's
accessibility tree (SemanticsBinding.ensureSemantics is wired in
main.dart). These complement the existing 9 network-only Playwright
tests by proving:

- Clicking APPROVE on a finding card fires finding_approval
- Clicking DISMISS fires finding_approval with action=dismiss
- Picking Spanish + typing + clicking TRANSLATE fires operator_command
  with language=es
- The APPROVE button properly disables after click (no double-fire)

Implementation hooks the Flutter app's own WebSocket via
page.on('websocket') + framesent and inspects what the UI actually
sends, rather than bypassing the UI by sending JSON over a side-
channel WS like the previous batch did."
git push -u origin feat/playwright-ui-interaction
```

- [ ] **Step 3: Open draft PR + watch CI**

```bash
gh pr create --draft --title "test(e2e): UI-interaction Playwright tests" --body "Adds 4 UI-driven Playwright tests using Flutter web's a11y semantics. Complement the 9 existing network-only tests."
gh run list --workflow=tests --branch feat/playwright-ui-interaction --limit 1
gh run watch <RUN_ID> --exit-status
```

If CI fails, common modes:
- **`flt-semantics[role="button"]` not found** — Flutter SDK version mismatch between local and CI. Mitigation: print the a11y tree on failure for debugging.
- **Click registers but no frame sent** — listener attached too late. Verify `_capture_app_outbound_frames` is called BEFORE `page.goto`.
- **Dropdown selection flakes** — Flutter's dropdown overlay is rendered in a different layer; may need `page.wait_for_selector('text=Spanish')` after opening.
- **Approve/dismiss button not visible within 20s** — producer hasn't published a finding yet. The producer publishes findings every ~1.6s with 0.2s tick, but cold-start can take 10-15s. If 20s is too tight, bump to 30s.

If you exhaust 3 push iterations without green, STOP and report BLOCKED.

- [ ] **Step 4: Mark ready + squash-merge once green**

```bash
gh pr ready
gh pr merge --squash --delete-branch
git checkout main && git pull
```

---

## Risk Surface

1. **Flutter web a11y tree is stable today but not guaranteed forever.** Probed and confirmed working on the current branch. If a future Flutter SDK upgrade changes the `flt-semantics` element shape, these tests will break. Mitigation: documented in test docstrings; if breakage happens, the failure mode is a clear "selector not found" rather than a silent wrong-pass.

2. **`framesent` is a Playwright Chromium DevTools Protocol feature.** Verified available in playwright 1.59.0 (used in current CI per requirements-dev.txt resolution). If a future Playwright pin update breaks this, fall back to instrumenting the Flutter WebSocket from page JS.

3. **The producer's findings drift in arrival timing.** Tasks 2 and 4 wait up to 20s for the first APPROVE/DISMISS button to appear. If CI runners are slow, bump to 30s.

4. **Dropdown rendering may differ between Material Design versions.** The probe confirmed "English" appears as a button-role node; if Flutter changes Dropdown rendering in a future SDK, the locator strategy may need `aria-haspopup` queries instead.

---

## Self-Review

**Spec coverage:**
- ✅ UI clicks fire correct WS frames: Tasks 2, 3, 4
- ✅ UI state transitions: Task 5 (button disables after click)
- ✅ Real-browser interaction (not network bypass): all 4 tests use page.click / page.fill

**Placeholder scan:** None.

**Type/name consistency:** New helpers `_capture_app_outbound_frames`, `_wait_for_frame_matching` use snake_case matching the existing file. Test names follow the existing `test_*` prefix.

**Scope check:** Single file modified. No new dependencies. Same CI job (bridge_e2e). Mechanically additive to PR #8.
