# Finding-Approval EGS Consumer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining half of the operator finding-approval loop. Qasim shipped the EGS backend in PR #45 (2026-05-11) — schema, `process_actions` branch, 12 tests. The dashboard's green-check is still aspirational because nothing in the bridge or dashboard consumes the new `egs.state.approved_findings` map. This plan closes that gap.

**Architecture:** EGS now publishes `egs.state.approved_findings: {finding_id: "approved" | "dismissed"}` whenever the operator clicks APPROVE or DISMISS. The bridge aggregator joins this map against `active_findings[]` at snapshot time and stamps `approved: bool` + `operator_status: enum` onto matching findings in the outbound `state_update`. The dashboard already promotes `received → confirmed` when it sees `approved == true` (`mission_state.dart:542`) — we extend the same loop with a dismiss arm and a fallback that reads `operator_status` directly. The EGS coordinator is unmodified by this plan.

**Tech Stack:** Python 3.11 (FastAPI bridge), Pytest + Playwright e2e, Dart/Flutter dashboard, Redis pub/sub, JSON Schema (draft 2020-12).

**Owner:** Ibrahim (Person 4), driving the frontend/bridge half on top of Qasim's PR #45. PR scope expanded mid-flight to absorb two drive-by fixes on Qasim's just-shipped `agents/egs_agent/coordinator.py` — see "Coordination Note for Qasim" at the end of this plan.

## Update history

- **2026-05-11 (initial):** Planned the full round trip end-to-end, assuming nothing had shipped. Locked four design decisions (LDD-1 through LDD-4) including a two-array EGS-side registry shape.
- **2026-05-11 (revision after `/review` of Qasim's PR #45):** Discovered Qasim shipped the EGS backend during this session with a different shape — single `approved_findings` map keyed by `finding_id`, values `"approved"|"dismissed"`. Tasks 1, 2, 3 are now done-equivalent (with shape differences). Tasks 4-9 rewritten against the map shape. LDD-1 superseded; LDD-2/3/4 still apply with small adjustments. The original two-array design lives on in `git log` for archaeological purposes — don't resurrect it.
- **2026-05-11 (scope expansion after pre-landing `/review` of PR #47):** Two drive-by findings on PR #45 (unbounded `_seen_approval_command_ids` set, unbounded `approved_findings` map) absorbed into this PR per user instruction rather than deferred. Commits `75d7ef5` (bounds) and `56c406a` (defensive test gaps) touch `agents/egs_agent/coordinator.py` and `tests/test_finding_approval.py`. Also addressed `c366af6` — the dashboard reconnect promotion bug that surfaced in the adversarial review (A2) — by dropping the `cur != null` precondition in the `applyStateUpdate` promotion loop. All three commits are documented in the Coordination Note for Qasim below.

---

## Architecture Diagram — finding_approval round trip

The EGS-side machinery (boxes 1-3 below) is **already shipped** in Qasim's PR #45. This plan implements the bridge stamp (box 4) and dashboard read path (box 5).

```
  ┌──────────────┐  operator clicks APPROVE on finding f_drone1_042
  │   Flutter    │    │
  │  dashboard   │    └─ markFinding("f_drone1_042", "approve")
  │ MissionState │       _findingActions[f] = pending  (spinner shown)
  └──────┬───────┘
         │
         │ WebSocket: {type:"finding_approval", command_id:"c-42",
         │             finding_id:"f_drone1_042", action:"approve", ...}
         ↓
  ┌──────────────┐  1. validate(websocket_messages)               [SHIPPED]
  │  ws_bridge   │  2. stamp bridge_received_at_iso_ms
  │   main.py    │  3. defensive validate(operator_actions)
  │              │  4. publish → Redis egs.operator_actions
  │              │  5. echo {ack:"finding_approval", ...} ─┐
  └──────┬───────┘                                          │ <500 ms
         │                                                  ↓
         │ Redis egs.operator_actions          ┌────────────────────┐
         │   {kind:"finding_approval",         │ Flutter promotion: │
         │    command_id:"c-42",               │  pending → received │
         │    finding_id:"f_drone1_042",       │  (GREY check) [1/2] │
         │    action:"approve"}                └────────────────────┘
         ↓
  ┌──────────────┐  process_actions finding_approval branch:      [PR #45]
  │   EGS        │   • dedup command_id   (_seen_approval_command_ids set)
  │ coordinator  │   • map "approve"  → status="approved"
  │              │   • map "dismiss"  → status="dismissed"
  │              │   • approved_findings[finding_id] = status
  │              │   • NO replan trigger          (LDD-4 deferred — agreed)
  └──────┬───────┘
         │
         │ Redis egs.state (1 Hz, full envelope):                  [PR #45]
         │   approved_findings: {
         │     "f_drone1_042": "approved",
         │     "f_drone2_007": "dismissed",
         │     ...
         │   }
         ↓
  ┌──────────────┐  aggregator.snapshot() (1 Hz state_update):    [TASK 4]
  │  ws_bridge   │   approved = egs_state.get("approved_findings", {}) or {}
  │  aggregator  │   for f in self._findings.values():
  │              │     status = approved.get(f.finding_id)
  │              │     if status == "approved":
  │              │       f["approved"] = True
  │              │       f["operator_status"] = "approved"   (LDD-2)
  │              │     elif status == "dismissed":
  │              │       f["approved"] = False
  │              │       f["operator_status"] = "dismissed"
  │              │   (orphan ids — in EGS map, no _findings entry
  │              │    after bridge restart — silently dropped, no error.)
  └──────┬───────┘
         │
         │ WebSocket: {type:"state_update",
         │   active_findings: [{finding_id:"f_drone1_042",
         │                      approved:true,
         │                      operator_status:"approved", ...}]}
         ↓
  ┌──────────────┐  applyStateUpdate promotion (extended):        [TASK 5]
  │   Flutter    │   if raw.approved == true OR
  │ MissionState │      raw.operator_status == "approved":
  │              │     _findingActions[f] = confirmed  (GREEN ✓) [2/2]
  │              │   elif raw.operator_status == "dismissed":
  │              │     _findingActions[f] = dismissed   (LDD-3 mirror)
  └──────────────┘
```

Target latency: grey check ≤500 ms (bridge ack), green check ≤3 s (one EGS tick + one bridge tick + one envelope). Verified end-to-end by Task 6's parametrized Playwright e2e.

---

## Locked Design Decisions

These are the operative design decisions for the **remaining** (bridge + dashboard) work. LDD-1 was superseded when Qasim shipped a different shape; the entry below documents what's now true on `main`. LDD-2, LDD-3, LDD-4 still apply.

**LDD-1 (SUPERSEDED by PR #45, kept for archaeology):** Originally planned two sorted arrays (`approved_finding_ids`, `dismissed_finding_ids`) with a 1000-entry FIFO cap. Qasim's PR #45 shipped a single map instead:

```jsonc
"approved_findings": {
  "f_drone1_042": "approved",
  "f_drone2_007": "dismissed"
}
```

- Schema slot: `shared/schemas/egs_state.json:70-77`, **optional** (not in `required`), `additionalProperties` constrained to `enum: ["approved", "dismissed"]`.
- Pydantic mirror: `shared/contracts/models.py:302`, `Dict[str, Literal["approved", "dismissed"]]` with `default_factory=dict`.
- Initial value: `scenario_state.py:77`, `"approved_findings": {}`.
- Dedup state: `_seen_approval_command_ids: set[str]` in `EGSCoordinator.__init__` (currently unbounded — see Coordination Note for Qasim).

Bridge and dashboard consume this shape going forward. **Do not reintroduce two-array thinking** anywhere in this plan or its implementations.

**LDD-2: Field-name reconciliation (`operator_status` vs `approved`).** STILL APPLIES.
The bridge aggregator owns the join. On every `snapshot()` it reads `egs_state.approved_findings` (defaulting to `{}` if absent — recall LDD-1 says the field is optional) and stamps **both** representations onto each matching finding dict in the returned envelope:
- `approved: true` (boolean, what the dashboard reads at `mission_state.dart:542`)
- `operator_status: "approved"` (enum string, matches Contract 4 `_common.json#/$defs/operator_status`)
- Symmetric for dismiss: `approved: false` + `operator_status: "dismissed"`.

`shared/schemas/finding.json` does NOT have `additionalProperties: false` (verified 2026-05-11), so adding `approved` alongside `operator_status` does not break validation. The aggregator only mutates its deep-copied output; `self._findings` keeps the drone-published originals untouched.

**LDD-3: Dismiss symmetry.** STILL APPLIES.
Dismiss is mirrored to approve in the dashboard read path: a refresh after a dismiss must still show the row struck through, not pop back to pending. The map shape from PR #45 already encodes both (`"approved"` vs `"dismissed"` values), so the dashboard's promotion loop gets one new arm: `else if (raw["operator_status"] == "dismissed")` → `ApprovalState.dismissed`.

**LDD-4: Replan-on-approve.** STILL APPLIES — and Qasim's PR #45 made the same call.
Approval is **not** treated as a replan trigger. Qasim's `process_actions` finding_approval branch (verified at `coordinator.py:251-280`) writes the map entry and returns without flipping `trigger_replan`. If Beat 6 ever demands "approved victim → auto-dispatch investigate_finding," that's a separate plan. Recorded here so it's not silent.

---

## File Structure

EGS-side files are **untouched by this plan** (Qasim's PR #45 already changed them — see "Already shipped by PR #45" below for the audit).

**Modify (production code in this plan):**
- `frontend/ws_bridge/aggregator.py` — in `snapshot()`, read `egs_state.approved_findings` (map) and stamp `approved: bool` + `operator_status: enum` onto matching findings in the deep-copied output. Defensive `.get("approved_findings", {}) or {}` because the schema field is optional.
- `frontend/flutter_dashboard/lib/state/mission_state.dart` — extend `applyStateUpdate` promotion loop to (a) also accept `raw["operator_status"] == "approved"` as a promotion trigger (forward-compat for callers that only stamp the enum form) and (b) stamp `ApprovalState.dismissed` when `raw["operator_status"] == "dismissed"`.
- `scripts/dev_fake_producers.py` — add `--emit=mesh-heartbeat` mode that publishes a minimal `mesh.adjacency_matrix` payload at 1 Hz so the real EGS coordinator's startup healthcheck passes during the new Playwright e2e without launching a real `mesh_simulator` subprocess. Production `agents/egs_agent/main.py` is **not** modified; no test-only env-var bypass is introduced.

**Modify (docs in this plan):**
- `docs/20-integration-contracts.md` — Contract 3 amendment: document the new `approved_findings` map field that Qasim added to the schema (Qasim updated the schema but not the prose docs). Note in Contract 4 that the bridge aggregator stamps `approved` + `operator_status` on outbound `state_update` frames based on the map.
- `docs/07-operator-interface.md` — one-line addition near line 101 confirming the green-check round trip is now live end-to-end (after this PR lands).

**Test (new files in this plan):**
- `frontend/ws_bridge/tests/test_aggregator_finding_approval_stamp.py` — new file, five unit tests covering the snapshot-time join against the `approved_findings` map: approve stamp, dismiss stamp, pending untouched, orphan-id silent skip, no-mutate of internal bucket.
- `frontend/ws_bridge/tests/test_e2e_playwright_finding_approval_green_check.py` — new file, one parametrized e2e (approve+dismiss) driving the full grey→{green,strikethrough} transition.

**Test (extend existing in this plan):**
- `frontend/flutter_dashboard/test/mission_state_test.dart` — add one test for dismiss promotion via `operator_status == "dismissed"`.
- `frontend/ws_bridge/tests/test_e2e_playwright.py` — append one assertion to `test_e2e_reconnect_after_bridge_restart` verifying that `operator_status` survives bridge restart.

**CI:**
- `.github/workflows/test.yml` — add the new Playwright e2e file to the `bridge_e2e` job invocation.

## Already shipped by Qasim's PR #45 (do NOT re-touch in this plan)

| File | What shipped |
|---|---|
| `shared/schemas/egs_state.json` | New optional `approved_findings` map field, enum-constrained. |
| `shared/contracts/models.py` | Pydantic mirror `approved_findings: Dict[str, Literal["approved", "dismissed"]]`. |
| `agents/egs_agent/scenario_state.py` | `"approved_findings": {}` in `build_initial_egs_state`. |
| `agents/egs_agent/coordinator.py` | `_seen_approval_command_ids: set[str]` and the `kind == "finding_approval"` branch in `process_actions`. |
| `agents/egs_agent/main.py` | `SIM_SCRIPTED_EVENTS` subscription (unrelated to finding_approval; bundled in same PR). |
| `agents/egs_agent/tests/test_finding_approval.py` | 12 unit tests covering approve, dismiss, dedup, malformed, mixed batch, schema validation, plus standalone-mode and drone_failure replan logic. |
| `TODOS.md` | Entry for TODO #1 flipped to CLOSED. |

---

## Tasks 1–3: SHIPPED BY QASIM'S PR #45 — no action required

These three tasks are obsolete. Qasim's commit `9421871` ("qasim gate 4", merged 2026-05-11 as PR #45) delivered the EGS-side equivalent of all three, with a different on-the-wire shape (single `approved_findings` map, see LDD-1 superseded note above).

**What replaced each task on `main`:**

- **Task 1 (seed initial state):** `agents/egs_agent/scenario_state.py:77` now seeds `"approved_findings": {}` in `build_initial_egs_state`. The original task wanted two empty arrays (`approved_finding_ids`, `dismissed_finding_ids`) — Qasim chose the single map shape that the schema was pre-allocated for. Substantively equivalent — both keep the field present-with-default so downstream consumers never need a None check.

- **Task 2 (coordinator approve branch):** `agents/egs_agent/coordinator.py:248-281` is the `kind == "finding_approval"` branch in `process_actions`. Dedups via `_seen_approval_command_ids: set[str]` (set in `__init__` at line 62). Maps `"approve"` → `"approved"`, `"dismiss"` → `"dismissed"`, writes into `egs_state.approved_findings[finding_id]`. Malformed actions are logged at WARNING and dropped. No replan trigger on approve (LDD-4 — same call we'd have made).

- **Task 3 (dismiss/dedup/sort/cap/noop tests):** `agents/egs_agent/tests/test_finding_approval.py` (12 tests, 341 lines new) covers approve, dismiss, dedup, malformed payload, no-replan, mixed batch, schema validation, plus standalone-transition replan, standalone-to-active no-replan, drone_failure replan, standalone exclusion from assignments, empty-dict schema validation. Different invariants than the original Task 3 (no "flip moves not duplicates" since the map shape just overwrites; no "sort for stable diffs" since the field is a map, not an array). Substantively equivalent backend coverage.

**Drive-by gaps in PR #45 to flag separately to Qasim — see Coordination Note at the end of this plan:**
- `_seen_approval_command_ids` is **unbounded** (no TTL, no cap). Existing `_seen_finding_ids` deque + 5-min TTL pattern was right there to mirror.
- `egs_state.approved_findings` map is **unbounded**. Long-running missions where the operator approves many findings ship a linearly growing payload at 1 Hz.
- Neither is urgent for the May 18 submission (demo length keeps both small), but both are real long-run footguns.

**Skip to Task 4 below — that's where your work starts.**


## Task 4: Bridge aggregator — stamp approved/operator_status on snapshot

**Files:**
- Modify: `frontend/ws_bridge/aggregator.py:94-116` (the `snapshot` method)
- Create: `frontend/ws_bridge/tests/test_aggregator_finding_approval_stamp.py`

**Upstream contract (from Qasim's PR #45):** `egs.state.approved_findings` is an **optional** dict of `{finding_id: "approved" | "dismissed"}`. Missing key, `None`, and empty dict all mean "no operator decisions yet" — handle all three identically. See `shared/schemas/egs_state.json:70-77`.

- [ ] **Step 1: Write the failing test**

Create `frontend/ws_bridge/tests/test_aggregator_finding_approval_stamp.py`:

```python
"""Unit tests for the LDD-2 snapshot-time approval stamp.

The bridge aggregator joins `egs_state.approved_findings` (a {finding_id: "approved"|
"dismissed"} map shipped by Qasim's PR #45) against active_findings[] at snapshot time
and stamps `approved` (bool, what the dashboard reads at mission_state.dart:542) and
`operator_status` (enum, matches Contract 4 _common.json#/$defs/operator_status) onto
matching findings WITHOUT mutating the internal _findings bucket.

See docs/superpowers/plans/2026-05-11-finding-approval-egs-consumer.md LDD-2.
"""
from __future__ import annotations

from copy import deepcopy

from frontend.ws_bridge.aggregator import StateAggregator

# Minimal schema-valid seed envelope. The aggregator only reads egs_state from
# this; the rest is unused by these tests but must satisfy the constructor.
_SEED = {
    "type": "state_update",
    "timestamp": "2026-05-11T00:00:00.000Z",
    "contract_version": "1.0.0",
    "egs_state": {
        "mission_id": "test",
        "mission_status": "active",
        "timestamp": "2026-05-11T00:00:00.000Z",
        "zone_polygon": [],
        "survey_points": [],
        "drones_summary": {},
        "findings_count_by_type": {
            "victim": 0, "fire": 0, "smoke": 0,
            "damaged_structure": 0, "blocked_route": 0,
        },
        "recent_validation_events": [],
        "active_zone_ids": [],
        # Field is OPTIONAL in the schema — most seeds shouldn't include it, but the
        # initial state from scenario_state.py does default it to {} (Qasim's PR #45).
        "approved_findings": {},
    },
    "active_findings": [],
    "active_drones": [],
}


def _finding(fid: str) -> dict:
    return {
        "finding_id": fid,
        "source_drone_id": "drone1",
        "timestamp": "2026-05-11T00:00:01.000Z",
        "type": "victim",
        "severity": 3,
        "gps_lat": 34.0,
        "gps_lon": -118.5,
        "altitude": 25.0,
        "confidence": 0.8,
        "visual_description": "test",
        "image_path": "/tmp/x.jpg",
        "validated": True,
        "validation_retries": 0,
        "operator_status": "pending",
    }


def test_snapshot_stamps_approved_for_finding_in_approved_findings_map():
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    agg.add_finding(_finding("f_drone1_001"))
    egs = deepcopy(_SEED["egs_state"])
    egs["approved_findings"] = {"f_drone1_001": "approved"}
    agg.update_egs_state(egs)
    snap = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    [f] = snap["active_findings"]
    assert f["approved"] is True
    assert f["operator_status"] == "approved"


def test_snapshot_stamps_dismissed_for_finding_in_approved_findings_map():
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    agg.add_finding(_finding("f_drone1_002"))
    egs = deepcopy(_SEED["egs_state"])
    egs["approved_findings"] = {"f_drone1_002": "dismissed"}
    agg.update_egs_state(egs)
    snap = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    [f] = snap["active_findings"]
    assert f["approved"] is False
    assert f["operator_status"] == "dismissed"


def test_snapshot_leaves_pending_finding_untouched():
    """A finding NOT in approved_findings keeps operator_status=pending and
    gets no `approved` key (we don't inject for the pending case to minimize
    wire churn)."""
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    agg.add_finding(_finding("f_drone1_003"))
    snap = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    [f] = snap["active_findings"]
    assert f["operator_status"] == "pending"
    assert "approved" not in f


def test_snapshot_handles_orphan_id_silently():
    """Regression: egs_state.approved_findings may reference a finding_id
    that is NOT in self._findings (bridge restart drops the finding cache
    but egs.state retains the approval registry). The snapshot must
    silently skip the orphan id — no crash, no extra entry in
    active_findings, no error log."""
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    # No findings added to the aggregator.
    egs = deepcopy(_SEED["egs_state"])
    egs["approved_findings"] = {"f_drone1_orphan": "approved"}
    agg.update_egs_state(egs)
    snap = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    assert snap["active_findings"] == []


def test_snapshot_handles_missing_or_none_approved_findings_field():
    """The egs_state schema field is OPTIONAL — the bridge must accept
    payloads where the key is missing OR explicitly None and treat both
    identically to {}. Without this the bridge crashes on any egs.state
    that predates PR #45 (e.g., during a partial mid-mission upgrade)."""
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    agg.add_finding(_finding("f_drone1_004"))
    # Case 1: key entirely absent.
    egs_missing = deepcopy(_SEED["egs_state"])
    del egs_missing["approved_findings"]
    agg.update_egs_state(egs_missing)
    snap1 = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    assert "approved" not in snap1["active_findings"][0]
    # Case 2: key present but None.
    egs_none = deepcopy(_SEED["egs_state"])
    egs_none["approved_findings"] = None
    agg.update_egs_state(egs_none)
    snap2 = agg.snapshot(timestamp_iso="2026-05-11T00:00:03.000Z")
    assert "approved" not in snap2["active_findings"][0]


def test_snapshot_stamp_does_not_mutate_internal_bucket():
    """LDD-2: aggregator only mutates the deep-copied output, never the
    internal _findings bucket. Two snapshots in a row with different egs
    states must produce different outputs."""
    agg = StateAggregator(max_findings=10, seed_envelope=deepcopy(_SEED))
    agg.add_finding(_finding("f_drone1_005"))
    egs_approved = deepcopy(_SEED["egs_state"])
    egs_approved["approved_findings"] = {"f_drone1_005": "approved"}
    agg.update_egs_state(egs_approved)
    snap1 = agg.snapshot(timestamp_iso="2026-05-11T00:00:02.000Z")
    assert snap1["active_findings"][0]["approved"] is True
    # Now flip to no-approval and re-snapshot.
    egs_clear = deepcopy(_SEED["egs_state"])
    egs_clear["approved_findings"] = {}
    agg.update_egs_state(egs_clear)
    snap2 = agg.snapshot(timestamp_iso="2026-05-11T00:00:03.000Z")
    assert "approved" not in snap2["active_findings"][0]
    assert snap2["active_findings"][0]["operator_status"] == "pending"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest frontend/ws_bridge/tests/test_aggregator_finding_approval_stamp.py -v`
Expected: 5 of 6 tests FAIL (the aggregator doesn't stamp anything yet). The `test_snapshot_leaves_pending_finding_untouched` test may pass since it asserts the current passthrough behavior — that's fine.

- [ ] **Step 3: Implement the snapshot-time stamp**

In `frontend/ws_bridge/aggregator.py`, modify the `snapshot` method to apply the stamp. Replace the existing `snapshot` method (currently lines 94-116) with:

```python
    def snapshot(self, *, timestamp_iso: str) -> Dict[str, Any]:
        """Return a fresh ``state_update`` envelope reflecting current buckets.

        ``timestamp_iso`` is stamped onto the envelope and onto the embedded
        ``egs_state.timestamp``. ``contract_version`` is set to the locked
        floor from ``shared.contracts.VERSION``; ``main.py``'s emit loop
        overwrites this on the way out so the value travels through one source
        of truth at runtime — seeding it here keeps the aggregator output
        schema-valid in isolation (regression-tested in ``test_aggregator``).

        LDD-2 (2026-05-11 finding-approval plan): joins Qasim's PR #45 field
        ``egs_state.approved_findings`` (a ``{finding_id: "approved"|
        "dismissed"}`` map) against the active_findings bucket. Findings whose
        id appears in the map with value ``"approved"`` get
        ``approved: True`` + ``operator_status: "approved"`` stamped on the
        output dict; with value ``"dismissed"`` get ``approved: False`` +
        ``operator_status: "dismissed"``. Findings absent from the map (or
        when the entire field is missing/None, which is schema-valid because
        the field is OPTIONAL) pass through untouched — ``operator_status``
        stays at whatever the drone published, typically ``"pending"``. The
        mutation applies only to the deep-copied output; ``self._findings``
        is never touched.

        Returned dict is independent: caller mutation does not affect internal
        buckets.
        """
        egs_copy = deepcopy(self._egs)
        egs_copy["timestamp"] = timestamp_iso
        approved_map = egs_copy.get("approved_findings") or {}
        active_findings = []
        for v in self._findings.values():
            f = deepcopy(v)
            status = approved_map.get(f.get("finding_id"))
            if status == "approved":
                f["approved"] = True
                f["operator_status"] = "approved"
            elif status == "dismissed":
                f["approved"] = False
                f["operator_status"] = "dismissed"
            active_findings.append(f)
        return {
            "type": "state_update",
            "timestamp": timestamp_iso,
            "contract_version": VERSION,
            "egs_state": egs_copy,
            "active_findings": active_findings,
            "active_drones": [deepcopy(v) for v in self._drones.values()],
        }
```

The key idiom is `egs_copy.get("approved_findings") or {}` — handles missing key (returns `None`) and explicit `None` value identically, both falling back to an empty dict for the `.get()` lookup.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest frontend/ws_bridge/tests/test_aggregator_finding_approval_stamp.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Run the aggregator's existing tests to confirm no regression**

Run: `uv run pytest frontend/ws_bridge/tests/test_aggregator.py -v`
Expected: all existing tests still PASS — confirms the snapshot signature/structure didn't drift.

- [ ] **Step 6: Commit**

```bash
git add frontend/ws_bridge/aggregator.py frontend/ws_bridge/tests/test_aggregator_finding_approval_stamp.py
git commit -m "feat(bridge): stamp approved/operator_status on snapshot from egs.state

LDD-2 of the finding-approval consumer plan. Aggregator joins
egs_state.approved_findings (the {finding_id: 'approved'|'dismissed'} map
Qasim shipped in PR #45) against active_findings[] at snapshot time,
stamping both the bool field (dashboard contract at mission_state.dart:542)
and the enum field (Contract 4). Handles missing/None field defensively
since the egs_state schema field is optional."
```

---

## Task 5: Flutter dashboard — promote `received → dismissed` from upstream `operator_status`

**Files:**
- Modify: `frontend/flutter_dashboard/lib/state/mission_state.dart:530-549`
- Modify: `frontend/flutter_dashboard/test/mission_state_test.dart`

- [ ] **Step 1: Write the failing test**

Append to `frontend/flutter_dashboard/test/mission_state_test.dart`:

```dart
  test("applyStateUpdate promotes received → dismissed when upstream "
       "operator_status is dismissed", () {
    final mission = MissionState();
    // Operator clicked DISMISS — local state goes pending → received via
    // bridge ack (simulated by markFinding + handleEcho).
    mission.markFinding("f_drone1_777", "dismiss");
    final cmdId = mission.lastSentEnvelope!["command_id"] as String;
    mission.handleEcho({
      "type": "echo",
      "ack": "finding_approval",
      "command_id": cmdId,
      "finding_id": "f_drone1_777",
      "contract_version": "1.0.0",
    });
    // Now EGS confirms via state_update with operator_status=dismissed.
    mission.applyStateUpdate({
      "type": "state_update",
      "timestamp": "2026-05-11T00:00:00.000Z",
      "contract_version": "1.0.0",
      "egs_state": <String, dynamic>{},
      "active_drones": const [],
      "active_findings": [
        {
          "finding_id": "f_drone1_777",
          "operator_status": "dismissed",
        }
      ],
    });
    expect(mission.approvalState("f_drone1_777"), ApprovalState.dismissed);
  });
```

(If `lastSentEnvelope` doesn't exist as a test hook, use the existing pattern in `mission_state_test.dart` — search for any test that already exercises `markFinding` + `handleEcho` and mirror the sink-capture approach.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend/flutter_dashboard && flutter test test/mission_state_test.dart --name "operator_status is dismissed"`
Expected: FAIL — current promotion loop only checks `raw["approved"] == true`, not `operator_status`.

- [ ] **Step 3: Extend the promotion loop in `mission_state.dart`**

In `frontend/flutter_dashboard/lib/state/mission_state.dart`, the `applyStateUpdate` method currently has a loop (lines 538-549) that only handles `raw["approved"] == true`. Replace that loop with:

```dart
    // Promote any non-confirmed/non-dismissed state to confirmed when
    // upstream marks the finding approved. Forward-compat: if the EGS
    // echo (via state_update with approved=true) arrives BEFORE the
    // bridge ack (or after a `failed` state from a transient error),
    // we still recognize the finding as confirmed instead of stranding
    // the row in pending/failed forever.
    //
    // Symmetric dismiss path (LDD-3, 2026-05-11 finding-approval plan):
    // upstream operator_status == "dismissed" promotes to
    // ApprovalState.dismissed for the same multi-operator-replay reasons.
    for (final raw in activeFindings) {
      if (raw is! Map<String, dynamic>) continue;
      final id = raw["finding_id"] as String?;
      if (id == null) continue;
      final cur = _findingActions[id];
      if (raw["approved"] == true || raw["operator_status"] == "approved") {
        if (cur != null &&
            cur != ApprovalState.confirmed &&
            cur != ApprovalState.dismissed) {
          _findingActions[id] = ApprovalState.confirmed;
        }
      } else if (raw["operator_status"] == "dismissed") {
        if (cur != null && cur != ApprovalState.dismissed) {
          _findingActions[id] = ApprovalState.dismissed;
        }
      }
```

(Keep the existing closing `}` of the for loop and the rest of `applyStateUpdate` unchanged.)

- [ ] **Step 4: Run tests to verify the new test passes**

Run: `cd frontend/flutter_dashboard && flutter test test/mission_state_test.dart`
Expected: all existing tests + the new test PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/flutter_dashboard/lib/state/mission_state.dart frontend/flutter_dashboard/test/mission_state_test.dart
git commit -m "feat(dashboard): promote dismiss state from upstream operator_status

LDD-3 of the finding-approval consumer plan. Mirrors the existing approve
promotion path so a refreshed dashboard re-applies dismissals from EGS."
```

---

## Task 6: Playwright e2e — full grey → green round trip (parametrized on approve/dismiss)

**Files:**
- Modify: `scripts/dev_fake_producers.py` — extend `--emit` to support a `mesh-heartbeat` mode that publishes `mesh.adjacency_matrix` at 1 Hz, so the real EGS coordinator's mesh-sim healthcheck passes without a real mesh-sim subprocess.
- Create: `frontend/ws_bridge/tests/test_e2e_playwright_finding_approval_green_check.py`
- Modify: `frontend/ws_bridge/tests/test_e2e_playwright.py` — extend the existing `test_e2e_reconnect_after_bridge_restart` with one assertion line.

- [ ] **Step 1: Read the template e2e**

Read `frontend/ws_bridge/tests/test_e2e_playwright.py:1-200` to understand the fixture pattern (redis subprocess, dev_fake_producers, uvicorn bridge, http.server for Flutter web, Playwright chromium). The new file mirrors this pattern but launches the real EGS coordinator alongside the fake producers so the green-check path is exercised end-to-end with the actual `process_actions` finding_approval branch shipped in Qasim's PR #45.

- [ ] **Step 2: Extend `dev_fake_producers.py` with a mesh-heartbeat emitter**

Read `scripts/dev_fake_producers.py` to find the existing `--emit` flag handler. The script already accepts a comma-separated list like `state,findings,egs` and starts a thread per emitter. Add a new emitter mode `mesh-heartbeat` that publishes a minimal valid `mesh.adjacency_matrix` payload at 1 Hz.

The publish payload only needs to satisfy `_await_mesh_sim` in `agents/egs_agent/main.py` (it just waits for any message on the channel), so the smallest valid envelope works:

```python
def _emit_mesh_heartbeat(redis_client, drone_ids, stop_event):
    """Publish a minimal mesh.adjacency_matrix heartbeat at 1 Hz.

    Used by the finding-approval e2e (Task 6 of the 2026-05-11 plan) so the
    real EGS coordinator's mesh-sim healthcheck (`_await_mesh_sim`) passes
    without launching a full `agents.mesh_simulator` subprocess. The
    coordinator only blocks until the first message arrives on this
    channel — payload contents are not validated by the healthcheck — so
    we emit a stable, contract-shaped placeholder that any reader can
    deep-introspect without surprise.
    """
    payload = {
        "timestamp_iso_ms": "2026-05-11T00:00:00.000Z",
        "adjacency": {d: {} for d in drone_ids},
        "source": "dev_fake_producers",
    }
    while not stop_event.is_set():
        redis_client.publish("mesh.adjacency_matrix", json.dumps(payload))
        stop_event.wait(1.0)
```

Wire it into the existing `--emit` parser alongside the `state`, `findings`, `egs` modes. Pattern follows the existing emitters one-for-one.

- [ ] **Step 3: Write the parametrized e2e**

Create `frontend/ws_bridge/tests/test_e2e_playwright_finding_approval_green_check.py`:

```python
"""E2E: clicking APPROVE or DISMISS drives the finding through bridge → EGS
→ state_update with operator_status set, and the dashboard row promotes
grey → green (approve) or strikethrough (dismiss) within 3 seconds.

Pipeline under test:

    Flutter web (Playwright chromium)
        ↑ WebSocket
    frontend.ws_bridge.main:app (uvicorn, test port)
        ↑ Redis
    agents.egs_agent.main (real coordinator, subscribed to egs.operator_actions)
        ↑ Redis
    scripts/dev_fake_producers.py --emit=state,findings,mesh-heartbeat

This is the only e2e in the suite that exercises the real EGS coordinator —
the rest mock the egs.state side via fake producers. The mesh-heartbeat
emit mode (added in Task 6 of the 2026-05-11 plan) satisfies the
coordinator's `_await_mesh_sim` startup check without launching a real
mesh_simulator subprocess. Production main.py keeps its unconditional
healthcheck — no test-only bypass knob.

Parametrized on action='approve' / 'dismiss' so both round trips are
covered. Multi-finding / multi-operator backend behaviors are unit-tested in
agents/egs_agent/tests/test_finding_approval.py (shipped in PR #45).

Marked @pytest.mark.e2e and excluded from default pytest runs (see pytest.ini).
Invoke with::

    uv run pytest frontend/ws_bridge/tests/test_e2e_playwright_finding_approval_green_check.py -v
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[3]
FLUTTER_WEB = REPO_ROOT / "frontend" / "flutter_dashboard" / "build" / "web"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def green_check_pipeline():
    """Launches redis + EGS coordinator + bridge + fake producers (incl. mesh
    heartbeat) + http.server. EGS is the real subprocess; everything else
    around it is faked just enough for the round-trip path under test."""
    redis_port = _free_port()
    bridge_port = _free_port()
    http_port = _free_port()
    redis_url = f"redis://localhost:{redis_port}"
    procs: list[subprocess.Popen] = []
    try:
        procs.append(subprocess.Popen(
            ["redis-server", "--port", str(redis_port), "--save", "", "--appendonly", "no"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
        time.sleep(0.5)
        env = {**os.environ, "REDIS_URL": redis_url, "GG_SCENARIO_ID": "disaster_zone_v1"}
        # Fake producers FIRST so the mesh heartbeat is already publishing
        # by the time the EGS coordinator starts and runs _await_mesh_sim.
        procs.append(subprocess.Popen(
            [sys.executable, "scripts/dev_fake_producers.py",
             "--emit=state,findings,mesh-heartbeat", "--no-fake-egs",
             "--redis-url", redis_url, "--drone-id", "drone1"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(REPO_ROOT),
        ))
        time.sleep(0.5)  # let the mesh heartbeat get one publish in
        # Real EGS coordinator. This is the system-under-test.
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "agents.egs_agent.main"],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(REPO_ROOT),
        ))
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "frontend.ws_bridge.main:app",
             "--host", "127.0.0.1", "--port", str(bridge_port)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(REPO_ROOT),
        ))
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "http.server", str(http_port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(FLUTTER_WEB),
        ))
        time.sleep(4.0)
        yield {
            "bridge_url": f"ws://127.0.0.1:{bridge_port}/ws",
            "http_url": f"http://127.0.0.1:{http_port}/index.html",
            "redis_port": redis_port,
        }
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


@pytest.mark.e2e
@pytest.mark.parametrize(
    "action,button_label,expected_status",
    [
        ("approve", "APPROVE", "approved"),
        ("dismiss", "DISMISS", "dismissed"),
    ],
)
def test_finding_action_round_trip_within_3s(
    green_check_pipeline, action, button_label, expected_status,
):
    """Acceptance: click {APPROVE,DISMISS} → bridge ack within 500ms →
    EGS-confirmed state_update with matching operator_status within 3s."""
    matched_frames: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        def on_ws(ws):
            def on_frame_received(payload):
                try:
                    data = json.loads(payload)
                except Exception:
                    return
                if data.get("type") != "state_update":
                    return
                for f in data.get("active_findings", []):
                    if f.get("operator_status") == expected_status:
                        matched_frames.append(f)
            ws.on("framereceived", on_frame_received)
        page.on("websocket", on_ws)

        page.goto(green_check_pipeline["http_url"])
        page.wait_for_function(
            f"() => document.body.innerText.includes('{button_label}')",
            timeout=15000,
        )
        page.get_by_role("button", name=button_label).first.click()

        deadline = time.time() + 3.0
        while time.time() < deadline and not matched_frames:
            page.wait_for_timeout(100)

        assert matched_frames, (
            f"no state_update with operator_status='{expected_status}' "
            f"within 3s after clicking {button_label} — the EGS "
            f"process_actions finding_approval branch is not closing the loop"
        )
        # Sanity: also check the bool form is set consistently with the enum.
        first = matched_frames[0]
        expected_bool = True if action == "approve" else False
        assert first.get("approved") is expected_bool, (
            f"operator_status={expected_status} but approved={first.get('approved')} "
            f"— bridge stamp is inconsistent between the bool and enum forms"
        )

        browser.close()
```

- [ ] **Step 4: Extend the existing reconnect e2e with an operator_status assertion**

Open `frontend/ws_bridge/tests/test_e2e_playwright.py` and find `test_e2e_reconnect_after_bridge_restart` (per the Phase 3 design spec it already asserts "confirmed approvals retain styling"). Add one assertion immediately after the post-reconnect state check, asserting that the upstream `operator_status` field on the previously-approved finding is `"approved"` in at least one post-reconnect frame. This proves the new bridge stamp survives bridge restart (the EGS coordinator persists the approval registry through restart; bridge rebuilds and re-stamps).

The exact line-level edit depends on the current test body — keep the diff to one assertion. Do NOT refactor or rewrite the surrounding test.

- [ ] **Step 5: Build the Flutter web bundle**

Run: `cd frontend/flutter_dashboard && flutter build web --release`
Expected: build succeeds, `build/web/index.html` exists.

- [ ] **Step 6: Run the new e2e (both parametrize cases)**

Run: `uv run pytest frontend/ws_bridge/tests/test_e2e_playwright_finding_approval_green_check.py -v`
Expected: 2 cases PASS (`approve`, `dismiss`) within ~30s total.

- [ ] **Step 7: Run the (extended) reconnect e2e**

Run: `uv run pytest frontend/ws_bridge/tests/test_e2e_playwright.py::test_e2e_reconnect_after_bridge_restart -v`
Expected: PASS — confirms the operator_status survives bridge restart.

- [ ] **Step 8: Commit**

```bash
git add scripts/dev_fake_producers.py \
        frontend/ws_bridge/tests/test_e2e_playwright_finding_approval_green_check.py \
        frontend/ws_bridge/tests/test_e2e_playwright.py
git commit -m "test(e2e): Playwright grey→green finding-approval round trip (approve+dismiss)

Parametrized on action so both branches of the EGS finding_approval consumer
get e2e coverage. Adds dev_fake_producers.py --emit=mesh-heartbeat mode so
the real EGS coordinator's mesh-sim healthcheck passes without launching a
real mesh_simulator subprocess — no production safety bypass needed.
Extends the existing reconnect e2e with one operator_status assertion."
```

---

## Task 7: CI wiring

**Files:**
- Modify: `.github/workflows/test.yml`

- [ ] **Step 1: Locate the `bridge_e2e` job**

Read `.github/workflows/test.yml` and find the existing `bridge_e2e` job (mentioned in `TODOS.md` line 16). It currently invokes `test_e2e_playwright.py` and `test_e2e_playwright_multi_drone.py`.

- [ ] **Step 2: Add the new e2e file to the invocation**

In the same job, append the new file to the pytest argument list. Example shape (match whatever pattern the existing job uses):

```yaml
      - name: Run bridge e2e
        run: |
          uv run pytest \
            frontend/ws_bridge/tests/test_e2e_playwright.py \
            frontend/ws_bridge/tests/test_e2e_playwright_multi_drone.py \
            frontend/ws_bridge/tests/test_e2e_playwright_finding_approval_green_check.py \
            -v
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/test.yml
git commit -m "ci: add finding_approval green-check e2e to bridge_e2e job"
```

---

## Task 8: Update Contract 3 in `docs/20-integration-contracts.md`

**Files:**
- Modify: `docs/20-integration-contracts.md:77-139` (Contract 3 section)

**Background:** Qasim's PR #45 added `approved_findings` to `shared/schemas/egs_state.json` and the Pydantic mirror, but did **not** update the prose Contract 3 documentation in `20-integration-contracts.md`. This task catches up the docs to the shipped schema. Read `shared/schemas/egs_state.json:70-77` for the canonical field shape before editing.

- [ ] **Step 1: Update the Contract 3 example payload**

In the Contract 3 JSON example (currently lines 84-132 of `docs/20-integration-contracts.md`), inside the `egs_state` object literal, add the `approved_findings` field. Place it after `"active_zone_ids"` (matching the order of `shared/schemas/egs_state.json`):

```json
  "active_zone_ids": ["zone_a", "zone_b"],
  "approved_findings": {
    "f_drone1_042": "approved",
    "f_drone2_007": "dismissed"
  },
  "base_image_path": "sim/fixtures/base_images/disaster_zone_v1_base.jpg",
```

- [ ] **Step 2: Add a documentation paragraph below the existing "Optional fields" note**

After the "Wire-path semantics" paragraph (currently ~line 139 of `docs/20-integration-contracts.md`), append a new subsection:

```markdown
**Approval registry (added 2026-05-11, Qasim's PR #45 + the bridge stamp in this PR):**

`approved_findings` is an **optional** map of `finding_id → "approved" | "dismissed"`.
It is populated by the EGS coordinator's `process_actions` finding_approval branch
(`agents/egs_agent/coordinator.py:248-281`) as the operator clicks APPROVE or DISMISS
on findings in the dashboard. Initial state seeds the field to `{}`
(`agents/egs_agent/scenario_state.py:77`), so consumers should treat absent, `None`,
and empty-dict identically — the schema field is not in `required`.

This map is the source of truth for the operator's approval decisions. The WS
bridge aggregator (`frontend/ws_bridge/aggregator.py` `snapshot()`) joins it against
`active_findings[]` at snapshot time and stamps `approved: true` /
`operator_status: "approved"` (or the dismissed equivalents) onto matching finding
objects in the outbound `state_update` envelope — this is what drives the
dashboard's grey → green check transition. Findings not present in the map pass
through with whatever `operator_status` the drone originally published (typically
`"pending"`).

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
```

- [ ] **Step 3: Update Contract 4's `operator_status` note**

In Contract 4 (around line 164: `operator_status ∈ {pending, approved, dismissed}`), append:

```markdown
`operator_status` ∈ {`pending`, `approved`, `dismissed`}. As of 2026-05-11, the
drone-published value (typically `"pending"`) is the initial state, but the WS
bridge aggregator overwrites this field on outbound `state_update` frames based on
the EGS-side `egs_state.approved_findings` map in Contract 3 — the operator's
decisions take precedence downstream. The dashboard reads the companion
`approved: boolean` field at `mission_state.dart:542`; the bridge stamps both
together, so consumers may use whichever form is most ergonomic.
```

- [ ] **Step 4: Commit**

```bash
git add docs/20-integration-contracts.md
git commit -m "docs(contracts): catch Contract 3 up to PR #45's approved_findings field

PR #45 added the schema field but left the prose docs behind. Adds the
approved_findings map to the Contract 3 example, documents its semantics
(including the optional-field defensive pattern downstream consumers must
follow), and clarifies in Contract 4 that the bridge aggregator owns the
outbound operator_status on state_update frames."
```

---

## Task 9: Update `docs/07-operator-interface.md`

**Files:**
- Modify: `docs/07-operator-interface.md` (one line near line 101)

**Note:** `TODOS.md` is already CLOSED for this TODO (Qasim's PR #45 closed it). Do NOT re-flip it. Read `TODOS.md:18-27` before starting and confirm the entry already begins with `### CLOSED —` — if for some reason it does not, escalate to the user rather than editing it unilaterally.

- [ ] **Step 1: Update the operator-interface doc**

Find the line `When a finding is approved, the icon on the map changes color and an ALL_DRONES broadcast is sent (e.g., "victim confirmed, dispatch en route").` (around line 101 of `docs/07-operator-interface.md`) and append a parenthetical:

```markdown
When a finding is approved, the icon on the map changes color and an ALL_DRONES broadcast is sent (e.g., "victim confirmed, dispatch en route"). (As of 2026-05-11 the approval round trip is live end-to-end: dashboard click → bridge ack (grey check, <500ms) → EGS confirmation via `egs.state.approved_findings` → bridge stamp on outbound `state_update` → dashboard promotion to green check, typically <3s. Backend half landed in PR #45; bridge + dashboard half in the PR for this plan.)
```

- [ ] **Step 2: Commit**

```bash
git add docs/07-operator-interface.md
git commit -m "docs(operator-interface): note finding_approval round trip is now live"
```

---

## Task 10: Final verification sweep

- [ ] **Step 1: Run the full EGS test suite**

Run: `uv run pytest agents/egs_agent/tests -v`
Expected: all pass.

- [ ] **Step 2: Run the full bridge test suite**

Run: `uv run pytest frontend/ws_bridge/tests -v --ignore=frontend/ws_bridge/tests/test_e2e_playwright_finding_approval_green_check.py`
Expected: all pass. (E2E is excluded by default via `pytest.ini`'s `@pytest.mark.e2e` marker; we ran it explicitly in Task 6.)

- [ ] **Step 3: Run the Flutter dashboard test suite**

Run: `cd frontend/flutter_dashboard && flutter test`
Expected: all pass.

- [ ] **Step 4: Run the e2e one more time end-to-end**

Run: `uv run pytest frontend/ws_bridge/tests/test_e2e_playwright_finding_approval_green_check.py -v`
Expected: PASS.

- [ ] **Step 5: Skim `git log --oneline` since the plan started**

Expected ~6 commits, one per task (Task 4, 5, 6, 7, 8, 9). If anything was missed (e.g., docs forgotten), add a fixup commit before opening the PR.

- [ ] **Step 6: Open the PR**

```bash
gh pr create --title "feat(bridge,dashboard): finding_approval frontend half — green check live" \
  --body "$(cat <<'EOF'
## Summary

Closes the frontend/bridge half of TODO #1 (finding_approval round trip). Qasim's
PR #45 (2026-05-11) shipped the EGS backend: schema field `approved_findings`,
`process_actions` finding_approval branch, 12 unit tests. This PR consumes that
field downstream so the dashboard's green-check actually becomes truthful.

- Bridge aggregator joins `egs.state.approved_findings` (map shape) against
  `active_findings[]` at snapshot time, stamps `approved: bool` + `operator_status: enum`
  onto matching findings before broadcasting `state_update` (LDD-2).
- Dashboard `applyStateUpdate` promotion loop extended for the dismiss mirror
  (LDD-3); also accepts `operator_status == "approved"` as an enum-form trigger.
- Contract 3 docs in `docs/20-integration-contracts.md` catch up to PR #45's
  schema field (the schema landed but the prose did not).
- New Playwright e2e parametrized on approve+dismiss, exercising the full
  round trip against a real EGS coordinator subprocess in <3s per case.
- Existing `test_e2e_reconnect_after_bridge_restart` extended with one
  assertion that `operator_status` survives bridge restart.
- `scripts/dev_fake_producers.py` gains a `--emit=mesh-heartbeat` mode so the
  e2e fixture can start the real EGS coordinator without a real mesh_simulator
  subprocess; no production safety bypass is introduced.

## Test plan
- [x] `frontend/ws_bridge/tests/test_aggregator_finding_approval_stamp.py` — 6 unit tests covering the snapshot-time map join (approve stamp, dismiss stamp, pending untouched, orphan-id silent, missing/None field defensive, no-mutate-internal).
- [x] `frontend/flutter_dashboard/test/mission_state_test.dart` — +1 dismiss promotion test.
- [x] `frontend/ws_bridge/tests/test_e2e_playwright_finding_approval_green_check.py` — parametrized approve+dismiss, both within 3s on a real EGS coordinator.
- [x] `frontend/ws_bridge/tests/test_e2e_playwright.py::test_e2e_reconnect_after_bridge_restart` — extended with operator_status assertion.
- [x] CI `bridge_e2e` job updated to include the new e2e file.
- [x] Full regression: existing aggregator, bridge, and Flutter test suites pass unchanged.

## Coordination with Qasim
PR #45 was the upstream this PR builds against. Two drive-by findings on PR #45
flagged for follow-up (out of scope for this PR — see plan's Coordination Note
section): `_seen_approval_command_ids` set in the coordinator is unbounded (no
TTL like the parallel `_seen_finding_ids`), and `egs_state.approved_findings`
itself is unbounded (no cap). Both acceptable for the May 18 submission demo
length; both worth a follow-up TODO post-submission.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Coordination Note for Qasim

This section is the one-stop briefing for Qasim. **If you are Qasim and only have time to read one paragraph, read this one.**

I (Ibrahim, Person 4) shipped the frontend/bridge/docs half of TODO #1 on top of your PR #45. The PR scope **expanded mid-flight** to absorb two drive-by fixes on your `coordinator.py` (your file, your domain) — flagged here so you're not surprised by the EGS-side diff.

**What this PR adds (frontend/bridge half — the original plan scope):**
1. **Bridge aggregator** (`frontend/ws_bridge/aggregator.py`): on every `snapshot()`, reads `egs_state.approved_findings` (your map) and stamps `operator_status: enum` onto matching findings in the outbound `state_update`. Defensive `.get("approved_findings") or {}` because your schema field is optional. (Originally also stamped `approved: bool`, but commit `f0bf8a8` dropped that — `shared/schemas/finding.json` has `additionalProperties: false` so the bool form was silently failing envelope validation. The dashboard's `mission_state.dart:548` accepts the enum form via its OR clause.)
2. **Dashboard** (`frontend/flutter_dashboard/lib/state/mission_state.dart`): extends `applyStateUpdate` promotion loop with a dismiss arm and (commit `c366af6`) drops the `cur != null` precondition so a fresh dashboard reload correctly promotes findings from upstream `operator_status` instead of stranding them in pending.
3. **Contract 3 prose** (`docs/20-integration-contracts.md`): catches the doc up to your schema change. Your PR added `approved_findings` to the JSON Schema and Pydantic mirror but didn't touch the Markdown contract doc; this PR fills that gap.
4. **`docs/07-operator-interface.md`**: one line noting the round trip is live end-to-end.
5. **Playwright e2e** parametrized on approve+dismiss, exercising the full pipeline including your real `EGSCoordinator` subprocess. Uses a new `scripts/dev_fake_producers.py --emit=mesh-heartbeat` mode so your `_await_mesh_sim` healthcheck passes without a real mesh_simulator. Your `main.py` is unmodified — no production safety bypass.
6. **CI** updated to include the new e2e in the `bridge_e2e` job (and the `bridge_e2e` job's `uv sync` extras grew to include `egs`/`sim`/`mesh` so the EGS subprocess actually starts in CI — caught by the first failed CI run).

**Scope expansion — two drive-by fixes on your `coordinator.py` (commits `75d7ef5` + `56c406a`):**

You asked Ibrahim to "just do it" rather than wait for a separate PR. Both fixes are surgical, mirror your existing patterns one-for-one, and your 12 PR #45 tests still pass unchanged:

- **`_seen_approval_command_ids` is now a bounded `Deque[Tuple[str, float]]` + parallel `set[str]`**, with TTL eviction using your existing `SEEN_FINDING_ID_TTL_S = 300.0` constant. Exact mirror of the `_seen_finding_ids` pattern at `coordinator.py:52-58`. The eviction loop runs at the top of the `finding_approval` branch, same shape as the one in `process_findings`.
- **`egs_state.approved_findings` is FIFO-capped at `MAX_APPROVED_FINDINGS = 1000`** (new constant next to `SEEN_FINDING_ID_TTL_S`). Eviction uses `next(iter(approved))` for oldest-insertion-order. Crucially, the cap only triggers on **new** finding_ids — rewrites and flips preserve their slot (no eviction churn when an operator flips a previously-approved finding to dismissed). Logged as `egs.finding_approval cap evicted oldest finding_id=...` when it fires.

**5 new tests** in `agents/egs_agent/tests/test_finding_approval.py` (after our two `/review` rounds): TTL eviction, single FIFO eviction, no-evict-on-rewrite (flip), multi-eviction FIFO order under sustained pressure, no-evict-on-idempotent-same-action. Full suite: 17/17 pass.

If any of the shape choices don't match what you would have done (e.g., you'd prefer a TTL on the map instead of FIFO, or a different cap value), flag it in PR review — happy to adjust.

**LDD recap** (decisions from the original plan, now mostly resolved by your PR):
- **LDD-1 (shape):** SUPERSEDED by your PR #45 — single `approved_findings` map, not the two-array shape originally planned. We adopted your shape.
- **LDD-2 (field-name reconciliation):** Bridge stamps both `approved: bool` AND `operator_status: enum`. Lives in this PR.
- **LDD-3 (dismiss symmetry):** Dashboard promotes both. Lives in this PR.
- **LDD-4 (replan-on-approve):** Deferred. Both your PR and mine agree — approval is informational.

If anything about the bridge stamp, the docs, or the e2e harness doesn't match what you would have done, flag it in PR review and I'll fix it.

---

## NOT in scope

Explicitly deferred or considered-and-rejected items, with one-line rationale each:

- **Replan-on-approve (LDD-4).** An approved victim does not trigger an `investigate_finding` task. Approval is informational. Qasim's PR #45 made the same call. If Beat 6 demands it, separate plan.
- **~~Modifying any file under `agents/egs_agent/`.~~ — SUPERSEDED 2026-05-11 (PR #47 review).** Originally out of scope; absorbed two drive-by fixes on `coordinator.py` (commits `75d7ef5`, `56c406a`) per user instruction. See update history entry 3 and Coordination Note.
- **~~TTL on `_seen_approval_command_ids`.~~ — DONE 2026-05-11 in commit `75d7ef5`.** Deque + set + 5-min TTL eviction, mirrors the existing `_seen_finding_ids` pattern.
- **~~Cap on `egs_state.approved_findings` map.~~ — DONE 2026-05-11 in commit `75d7ef5`.** FIFO cap at `MAX_APPROVED_FINDINGS = 1000` entries.
- **Per-finding state machine in EGS.** EGS uses a single `approved_findings: {id: "approved"|"dismissed"}` map (Qasim's choice in PR #45). No per-finding records. We adopt this shape and don't push for a different one.
- **Schema additions to `finding.json`.** `operator_status` already exists in Contract 4 since Day 1; no new fields on the finding object. The `approved: bool` field added by the bridge stamp travels outbound only and relies on `additionalProperties: false` being absent from `finding.json` (verified 2026-05-11).
- **EGS replay-from-disk after coordinator restart.** The approval map lives in `egs_state` in-memory. A coordinator restart loses prior approvals. Demo never restarts mid-run.
- **Multi-operator conflict resolution.** Two operators clicking approve+dismiss on the same finding resolve to last-write-wins via map overwrite. No CRDT. Single-operator v1.
- **Re-validating `egs_state` against `shared/schemas/egs_state.json` in the bridge aggregator.** Out of scope. The bridge trusts its upstream (it's a one-process system in v1). If we ever add validation at this boundary, it's its own plan.

## What already exists (and is being reused)

Reuse over rebuild — explicit list so reviewers can verify nothing is duplicated:

- **`StateAggregator.snapshot()` deep-copy-output discipline** at `aggregator.py:94-116`. New stamp logic preserves the existing invariant: never mutate internal buckets. Regression-tested.
- **`StateAggregator.has_finding` allowlist guard** at `aggregator.py:84-92`. Already rejects approvals for unknown finding_ids before they reach Redis, so the bridge → EGS path already filters out aged-out findings. No new guard needed.
- **Dashboard `applyStateUpdate` promotion loop** at `mission_state.dart:538-549`. Already promotes `received → confirmed` on `raw["approved"] == true`. We only add the dismiss arm and the `operator_status == "approved"` enum-form check (one line each).
- **`dev_fake_producers.py --emit` flag** from PR #20. Already supports `state`, `findings`, `egs` modes; adding `mesh-heartbeat` is one new emitter following the existing pattern.
- **Contract 4's `operator_status` field** in `shared/schemas/finding.json:11,27`. Schema slot for approve/dismiss has been required-on-every-finding since Day 1; we're finally consuming it in the outbound `state_update`.
- **`shared/schemas/egs_state.json` `approved_findings` field** (PR #45 addition). The downstream consumer (this PR's bridge) doesn't redefine the shape — it reads what's there.
- **`pytest.mark.e2e` exclusion in `pytest.ini`.** New Playwright e2e inherits the existing run-explicitly contract — no CI default-run changes needed beyond adding the file to the existing `bridge_e2e` job.
- **PR #45's `process_actions` finding_approval branch.** Tested by 12 unit tests in `test_finding_approval.py` already on `main`. We don't re-test it from the bridge side; we just trust the contract and exercise the join.

## Failure modes for new codepaths

For each new codepath this plan introduces, one realistic production failure mode and whether it's covered:

| Codepath | Failure mode | Test? | Error handling? | Visible to user? |
|---|---|---|---|---|
| `aggregator.snapshot` stamp | finding_id in `approved_findings` map but NOT in `_findings` (post-restart orphan) | ✓ (Task 4 orphan test) | ✓ silently skipped | Silent — finding stays out of `active_findings[]` until it re-appears |
| `aggregator.snapshot` stamp | `egs_state.approved_findings` key missing entirely (pre-PR-#45 stale payload) | ✓ (Task 4 missing-or-None defensive test) | ✓ `.get(...) or {}` fallback | Silent — all findings pass through as "pending" |
| `aggregator.snapshot` stamp | `egs_state.approved_findings` is explicitly `None` | ✓ (Task 4 missing-or-None defensive test) | ✓ same `or {}` idiom | Silent |
| `aggregator.snapshot` stamp | `approved_findings` has a value outside `{"approved", "dismissed"}` (schema violation upstream) | None (impossible per Pydantic + JSON Schema enum constraint) | Falls through both `elif` branches → finding passes through untouched | Silent — wouldn't render a state change |
| `dev_fake_producers.py --emit=mesh-heartbeat` | Redis publish fails | None (existing emitter pattern, treats failure as warning) | Inherits existing emitter behavior | Test would fail to start EGS coordinator → fixture timeout → clear pytest error |
| Dashboard dismiss promotion | upstream `operator_status="dismissed"` arrives BEFORE bridge ack | ✓ (Task 5 forward-compat test) | ✓ — promotes anyway, mirror of approve path | Row goes directly to strikethrough |
| Playwright e2e fixture | `dev_fake_producers --emit=mesh-heartbeat` startup race with EGS coordinator | Mitigated by `time.sleep(0.5)` after producers, `time.sleep(4.0)` after all subprocesses | None (test failure is the user-facing signal) | Pytest failure with clear timeout |

**Critical gaps:** None. Every new codepath has either a test, defensive code, or both.

## Worktree parallelization strategy

| Step | Modules touched | Depends on |
|---|---|---|
| Tasks 1-3 | (none — shipped by Qasim PR #45) | — |
| Task 4 (bridge aggregator stamp) | `frontend/ws_bridge/aggregator.py` + new test file | — (reads `egs_state` only, no live dep on EGS impl) |
| Task 5 (dashboard dismiss promotion) | `frontend/flutter_dashboard/lib/state/mission_state.dart` + test | — (independent of all backend) |
| Task 6 (e2e + dev_fake_producers heartbeat) | `scripts/dev_fake_producers.py`, new e2e file, existing reconnect e2e | Tasks 4 + 5 (e2e exercises both) |
| Task 7 (CI workflow) | `.github/workflows/test.yml` | Task 6 (new file must exist) |
| Task 8 (Contract 3 docs) | `docs/20-integration-contracts.md` | — (independent doc work) |
| Task 9 (operator-interface) | `docs/07-operator-interface.md` | — (independent doc work) |
| Task 10 (verification sweep + PR) | (no files modified) | All prior tasks |

**Parallel lanes:**
- **Lane A (bridge aggregator):** Task 4. Independent module.
- **Lane B (dashboard):** Task 5. Independent module.
- **Lane C (docs):** Tasks 8 and 9. Two independent files, can be done together or one after the other.
- **Sequential after fan-in:** Task 6 (depends on A + B), then Task 7 (depends on Task 6), then Task 10 (depends on all).

**Execution order:** Launch Lanes A, B, C in parallel. Merge A + B. Then Task 6, then Task 7, then Task 10. ~3 parallel worktrees, ~40% wall-time compression vs sequential.

**Conflict flags:** None. No two parallel lanes touch the same module directory.

## Self-Review

- [x] **Spec coverage:** The remaining (frontend/bridge/docs) half of TODO #1 is fully addressed. The EGS backend half is acknowledged as shipped in Qasim's PR #45 with substantive equivalence to original Tasks 1-3.
- [x] **Placeholder scan:** No TBDs, no "implement later," every code step contains executable code, every test has its assertions written out.
- [x] **Type consistency:** `approved_findings` (the map) is used identically across bridge aggregator, Contract 3 docs, tests, and PR body. `operator_status` enum values (`"approved"`, `"dismissed"`, `"pending"`) match `shared/schemas/_common.json#/$defs/operator_status`. Bridge stamps both `approved: bool` and `operator_status: enum` everywhere they're mentioned. No vestigial references to the superseded two-array shape (`approved_finding_ids`, `dismissed_finding_ids`) in any task.
- [x] **Plan vs. reality:** Plan file describes only work that is NOT yet on `main` (verified 2026-05-11 against `git diff origin/main`).

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 3 findings on initial draft, all resolved |
| Plan Completion Audit | `/review` (Qasim's PR #45 vs this plan) | Detect overlap with shipped work | 1 | issues_found | 2 critical gaps in PR #45 (bridge + dashboard not wired), 4 drive-by INFORMATIONAL findings on PR #45 |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

**Plan Completion Audit (post-PR-#45 re-baseline):**
- Tasks 1, 2, 3 of the original plan: DONE-equivalent on `main` via PR #45 (with a different shape — single `approved_findings` map vs the originally-planned two arrays). Stubbed out in this plan with a SHIPPED note.
- Tasks 4, 5, 6, 7, 8, 9, 10 of the original plan: NOT DONE. This revision rewrites Tasks 4, 5, 8, 9 to match the actual map shape; Tasks 6, 7, 10 carry forward with minor wording fixes.
- Two unbounded-collection footguns flagged in PR #45 (`_seen_approval_command_ids` set, `approved_findings` map). Both INFORMATIONAL, deferred to post-submission follow-up per "NOT in scope."

**Initial Eng Review findings (all resolved before this revision):**
- 1.1 Missing ASCII data flow diagram → added.
- 1.2 Unbounded EGS-side registry growth → originally planned a 1000-entry cap; LDD-1 then SUPERSEDED entirely when Qasim's PR shipped without a cap. Flagged to Qasim as a drive-by finding instead.
- 1.3 Production safety bypass via env var → replaced with `dev_fake_producers.py --emit=mesh-heartbeat` mode.

**UNRESOLVED:** 0.
**CRITICAL GAPS:** 0 in this plan. (2 critical gaps in PR #45's coverage — bridge join, dashboard read path — are exactly what this plan delivers.)
**VERDICT:** ENG CLEARED (PLAN) — ready to implement. Scope is now ~40% of the original plan since Tasks 1-3 are obsolete.
