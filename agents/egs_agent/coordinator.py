import asyncio
import json
import logging
import time
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone
from typing import TypedDict, Dict, Any, List, Deque, Optional, Tuple

from langgraph.graph import StateGraph, START, END

from shared.contracts.logging import ValidationEventLogger, default_log_dir
from shared.contracts.topics import per_drone_tasks_channel
from agents.egs_agent.validation import EGSValidationNode
from agents.egs_agent.replanning import assign_survey_points
from agents.egs_agent.command_translator import translate_operator_command

logger = logging.getLogger(__name__)

# How often refresh_validation_events actually re-reads the JSONL log.
# Per eng-review Q2 (2026-05-07): every 5th graph tick keeps file I/O bounded
# on long runs while staying well under the dashboard's 1Hz publish budget
# (worst-case 5 ticks of staleness, typically <1s).
VALIDATION_REFRESH_EVERY_N_TICKS = 5

# Wave 3a (Component 4): how long a finding_id remains memoized before we
# forget we've seen it. 5 minutes is generous against realistic outage
# windows (resilience_v1's drop window is 60s) while bounding memory at
# ~5000 keys × ~50 bytes = ~250 KB even at 1000 findings/min.
SEEN_FINDING_ID_TTL_S = 300.0

# Bounded approval registry: cap egs_state.approved_findings at this many
# entries (FIFO eviction). Defends against long-running missions where
# the operator approves many findings, which would otherwise grow the
# state_update envelope size linearly. 1000 is ~50x larger than any
# realistic demo so the cap is purely defensive.
MAX_APPROVED_FINDINGS: int = 1000

# GH #32 / Bug 3 fix (Phase D resilience-scenario blocker): outer timeout on
# the spawned replan task. assign_survey_points has its own internal per-attempt
# httpx timeout (replanning.EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S = 30 s) plus a
# retry budget (CONFIG.validation.max_retries = 3, so 4 attempts), but Ollama
# can *hang* without erroring under VRAM eviction stalls — the await never
# returns, the `finally` never clears `_replan_in_flight`, and every
# subsequent replan trigger gets dedup-skipped indefinitely. This outer
# wait_for() forces a bounded lifetime on the in-flight slot. On TimeoutError
# the `finally` clears the flag and the next replan trigger gets a fresh
# attempt.
#
# Sized at 240 s = 4 min so the retry loop's worst-case wall time (4 × 30 s
# = 120 s when every attempt hangs to its httpx timeout) AND the deterministic
# round-robin fallback at the bottom of `assign_survey_points` both fit
# comfortably before the outer guard fires. The arithmetic invariant is pinned
# by `agents/egs_agent/tests/test_coordinator_replan_hang.py::
# test_per_attempt_timeout_fits_inside_outer_guard` — see that test's docstring
# and `docs/sim-resilience-run-notes.md` §"2026-05-13" for the original live
# evidence that the pre-fix 180 s per-attempt timeout starved the fallback path.
REPLAN_OVERALL_TIMEOUT_S: float = 240.0

# Headroom required between the retry loop's worst-case wall time and the outer
# guard so the deterministic round-robin fallback at
# `agents/egs_agent/replanning.py` (after `while retries <= max_retries:`) has
# bounded wall time to execute + publish tasks before the outer guard cancels
# the inner task. The fallback itself is O(survey_points × active_drones) and
# completes in well under a second on the demo scale (25 points × 3 drones), so
# 30 s is conservatively oversized — but cheap to enforce as an invariant.
REPLAN_FALLBACK_HEADROOM_S: float = 30.0

# Phase 1 (GATE 4 wow moment): how long the dashboard banner lingers after a
# replan finishes. Module-level so tests can monkeypatch it to a tiny value
# without hardcoding 3.0 inline. 3 seconds matches the demo storyboard's
# Beat 3c hold: long enough for the operator's eye to read "PASSED" in green,
# short enough that the banner doesn't loiter into the next narration beat.
REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S: float = 3.0


class EGSState(TypedDict):
    egs_state: Dict[str, Any]
    incoming_telemetry: List[Dict[str, Any]]
    incoming_findings: List[Dict[str, Any]]
    incoming_commands: List[Dict[str, Any]]
    incoming_actions: List[Dict[str, Any]]
    messages_to_publish: List[Dict[str, Any]] # e.g. {"channel": "...", "data": "..."}
    trigger_replan: bool

class EGSCoordinator:
    def __init__(self, validation_node: EGSValidationNode, redis_client=None):
        self.validation_node = validation_node
        self.redis_client = redis_client
        self._replan_in_flight = False  # re-entrancy guard for fire-and-forget replan
        self._validation_refresh_counter = 0  # gates refresh_validation_events node
        # Wave 3a (Component 4): finding_id deduplication.
        # We keep both a deque (for FIFO eviction) and a set (for O(1)
        # membership) — deque keeps eviction simple; set keeps the hot path
        # fast. Without this, replayed findings (drone-side buffer flush on
        # link restore) would double-increment findings_count_by_type.
        self._seen_finding_ids: Deque[Tuple[str, float]] = deque()
        self._seen_finding_id_set: set[str] = set()
        # Wave 3a (Component 4): silent-zero diagnostic counter.
        # Incremented for each finding that survives dedup AND validation;
        # main.py's 30s periodic task reads this to emit
        # "egs.findings_consumed total=N" so a broken migration or mesh-sim
        # crash mid-run becomes observable instead of silent.
        self._findings_accepted_total = 0
        # Bounded dedup for finding_approval command_ids, mirrors the existing
        # _seen_finding_ids deque+set pattern (TTL = SEEN_FINDING_ID_TTL_S).
        # Without TTL eviction the set leaks linearly with operator clicks.
        self._seen_approval_command_ids: Deque[Tuple[str, float]] = deque()
        self._seen_approval_command_id_set: set[str] = set()
        # Phase 1 (GATE 4 wow moment): transient per-attempt log surfaced on
        # egs_state.replan_in_flight_attempt_log. Populated by replanning.py
        # via the log sink injected on each replan; cleared
        # REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S seconds after the in-flight slot
        # frees so the dashboard's wow-moment banner has time to render the
        # final PASSED/FAILED state. List[Dict] not List[ReplanAttempt] —
        # contracts/models.ReplanAttempt is the wire-shape mirror; this
        # bucket stores already-shaped dicts so the snapshot in
        # refresh_validation_events can deep-copy without round-tripping
        # through Pydantic on every tick.
        self._replan_attempt_log: List[Dict[str, Any]] = []
        # Handle for the pending asyncio.call_later clear. We CANCEL this if a
        # new replan starts during the 3s grace window — otherwise the second
        # replan's fresh entries would be wiped out mid-stream.
        self._pending_clear_handle: Optional[asyncio.TimerHandle] = None
        # Validation event logger for Layer 2 (EGS function calls). Mirrors
        # the drone_agent/main.py wiring at line 47 so ASSIGNMENT_TOTAL_MISMATCH
        # events finally show up in validation_events.jsonl. Path honours the
        # GG_LOG_DIR env var via default_log_dir() so tests can isolate.
        self._validation_log = ValidationEventLogger(
            path=default_log_dir() / "validation_events.jsonl"
        )
        self.graph = self._build_graph()

    # ---- Phase 1 (GATE 4 wow moment): replan attempt-log lifecycle --------

    def _append_replan_attempt(self, attempt: Dict[str, Any]) -> None:
        """Sink callback handed to replanning.assign_survey_points.

        Appends one ReplanAttempt-shaped dict to the transient log. Called
        once per retry-loop branch (validation failure or final success).
        Any pending clear timer is cancelled here — a fresh replan in the
        3-second grace window must NOT have its first entries wiped by the
        previous replan's pending clear.
        """
        if self._pending_clear_handle is not None:
            self._pending_clear_handle.cancel()
            self._pending_clear_handle = None
        self._replan_attempt_log.append(attempt)

    def _clear_replan_attempt_log(self) -> None:
        """TimerHandle callback that empties the transient log."""
        self._replan_attempt_log = []
        self._pending_clear_handle = None

    def _schedule_replan_attempt_log_clear(self) -> None:
        """Schedule the post-replan clear using asyncio.call_later.

        Cancels any pending clear first so back-to-back replans don't double-
        schedule. The actual delay is read at call time from the module-level
        constant so tests can monkeypatch it.
        """
        if self._pending_clear_handle is not None:
            self._pending_clear_handle.cancel()
            self._pending_clear_handle = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop — nothing to schedule. Tests that exercise the
            # lifecycle always have a loop; production always has one too.
            # `get_running_loop` (not `get_event_loop`) is the supported way
            # to obtain the current loop from async code per Python 3.10+ —
            # the deprecated form would emit a DeprecationWarning.
            return
        self._pending_clear_handle = loop.call_later(
            REPLAN_ATTEMPT_LOG_CLEAR_DELAY_S,
            self._clear_replan_attempt_log,
        )

    def _build_graph(self):
        workflow = StateGraph(EGSState)

        workflow.add_node("process_telemetry", self.process_telemetry)
        workflow.add_node("process_findings", self.process_findings)
        workflow.add_node("process_commands", self.process_commands)
        workflow.add_node("process_actions", self.process_actions)
        workflow.add_node("refresh_validation_events", self.refresh_validation_events)
        workflow.add_node("replan", self.replan)

        workflow.add_edge(START, "process_telemetry")
        workflow.add_edge("process_telemetry", "process_findings")
        workflow.add_edge("process_findings", "process_commands")
        workflow.add_edge("process_commands", "process_actions")
        workflow.add_edge("process_actions", "refresh_validation_events")

        def should_replan(state: EGSState):
            if state.get("trigger_replan", False):
                return "replan"
            return END

        workflow.add_conditional_edges("refresh_validation_events", should_replan)
        workflow.add_edge("replan", END)

        return workflow.compile()

    def process_telemetry(self, state: EGSState) -> EGSState:
        egs_state = state["egs_state"].copy()
        trigger_replan = state.get("trigger_replan", False)

        drones_summary = egs_state.setdefault("drones_summary", {})

        for t in state.get("incoming_telemetry", []):
            drone_id = t.get("drone_id")
            if not drone_id:
                continue

            # check for heartbeat loss could be done here or in main loop
            # for demo, we just update state
            prev_status = drones_summary.get(drone_id, {}).get("status")
            new_status = t.get("agent_status", "active")

            drones_summary[drone_id] = {
                "status": new_status,
                "battery": t.get("battery_pct"),
            }

            # If drone went offline, replan!
            if prev_status == "active" and new_status == "offline":
                trigger_replan = True

            # Gate 4 (standalone tolerance): if a drone transitions from
            # active to standalone it can no longer receive Redis task
            # messages, so its assigned survey points must be
            # redistributed to reachable drones.
            if prev_status == "active" and new_status == "standalone":
                trigger_replan = True

            # First time we see this drone *and* it's reporting "active": initial replan.
            if prev_status is None and new_status == "active":
                trigger_replan = True

            # If battery low, we might notify or trigger replan
            if t.get("battery_pct", 100) < 20:
                logger.warning(f"Drone {drone_id} battery low!")

        return {**state, "egs_state": egs_state, "trigger_replan": trigger_replan, "incoming_telemetry": []}

    def process_findings(self, state: EGSState) -> EGSState:
        egs_state = state["egs_state"].copy()
        counts = egs_state.setdefault("findings_count_by_type", {
            "victim": 0, "fire": 0, "smoke": 0, "damaged_structure": 0, "blocked_route": 0
        })

        # Wave 3a (Component 4): finding_id dedup before validation.
        # Compute now_s once per call. FIFO-evict expired entries from the
        # head of the deque (O(k) where k = expired this call) and mirror
        # the eviction in the membership set so the two structures stay in
        # sync. The set is the hot-path lookup; the deque is the time-
        # ordered eviction record.
        now_s = time.time()
        while self._seen_finding_ids and (
            now_s - self._seen_finding_ids[0][1] >= SEEN_FINDING_ID_TTL_S
        ):
            expired_fid, _ = self._seen_finding_ids.popleft()
            self._seen_finding_id_set.discard(expired_fid)

        for f in state.get("incoming_findings", []):
            fid = f.get("finding_id")
            if fid is not None and fid in self._seen_finding_id_set:
                logger.info(
                    "egs.findings duplicate dropped finding_id=%s", fid,
                )
                continue
            val_res = self.validation_node.validate_finding(f)
            if val_res.valid:
                ftype = f.get("type")
                if ftype in counts:
                    counts[ftype] += 1
                    if fid is not None:
                        self._seen_finding_ids.append((fid, now_s))
                        self._seen_finding_id_set.add(fid)
                    self._findings_accepted_total += 1
                    logger.info(
                        "egs.findings accepted source=%s type=%s finding_id=%s "
                        "gps=(%s,%s) total_%s=%d",
                        f.get("source_drone_id"), ftype, f.get("finding_id"),
                        f.get("gps_lat"), f.get("gps_lon"), ftype, counts.get(ftype, 0),
                    )
            else:
                logger.info(
                    "egs.findings rejected reason=%s detail=%s",
                    val_res.failure_reason, val_res.detail,
                )

        return {**state, "egs_state": egs_state, "incoming_findings": []}

    async def process_commands(self, state: EGSState) -> EGSState:
        egs_state = state["egs_state"].copy()
        msgs_to_pub = state.get("messages_to_publish", []).copy()
        trigger_replan = state.get("trigger_replan", False)

        incoming = state.get("incoming_commands", [])
        if incoming:
            logger.info("process_commands: received %d command(s)", len(incoming))

        for c in incoming:
            op_txt = c.get("raw_text", "")
            lang = c.get("language", "en")
            cmd_id = c.get("command_id", "")
            logger.info("process_commands: translating cmd_id=%s lang=%s text=%r", cmd_id, lang, op_txt)

            translation = await translate_operator_command(op_txt, lang, state["egs_state"], self.validation_node)
            translation["command_id"] = cmd_id
            translation["contract_version"] = "1.0.0"
            translation["egs_published_at_iso_ms"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

            # Sanitize structured.args to only keep schema-allowed fields.
            # The LLM sometimes adds extra keys (e.g., "reason" on exclude_zone)
            # that pass EGS validation but fail the bridge's strict re-validation.
            _ALLOWED_ARGS = {
                "restrict_zone": {"zone_id"},
                "exclude_zone": {"zone_id"},
                "recall_drone": {"drone_id", "reason"},
                "set_priority": {"finding_type", "priority_level"},
                "set_language": {"lang_code"},
                "unknown_command": {"operator_text", "suggestion"},
            }
            structured = translation.get("structured", {})
            cmd_name = structured.get("command", "")
            allowed = _ALLOWED_ARGS.get(cmd_name)
            if allowed and isinstance(structured.get("args"), dict):
                structured["args"] = {k: v for k, v in structured["args"].items() if k in allowed}

            logger.info("process_commands: translation result valid=%s kind=%s cmd=%s",
                        translation.get("valid"), translation.get("kind"), cmd_name)
            logger.info("process_commands: FULL PAYLOAD: %s", json.dumps(translation))

            # Output translation back to WebSocket bridge (or just log it)
            msgs_to_pub.append({
                "channel": "egs.command_translations",
                "data": translation
            })
            logger.info("process_commands: queued for publish on egs.command_translations")

            if translation.get("valid"):
                pending = egs_state.setdefault("pending_commands", {})
                pending[cmd_id] = translation["structured"]

        return {**state, "egs_state": egs_state, "trigger_replan": trigger_replan, "incoming_commands": [], "messages_to_publish": msgs_to_pub}

    def process_actions(self, state: EGSState) -> EGSState:
        egs_state = state["egs_state"].copy()
        trigger_replan = state.get("trigger_replan", False)

        for action in state.get("incoming_actions", []):
            kind = action.get("type", action.get("kind"))
            if kind == "operator_command_dispatch":
                cmd_id = action.get("command_id")
                pending = egs_state.get("pending_commands", {})
                if cmd_id in pending:
                    cmd = pending.pop(cmd_id)
                    cmd_name = cmd.get("command")
                    if cmd_name in ["restrict_zone", "exclude_zone", "recall_drone"]:
                        trigger_replan = True
            elif kind == "finding_approval":
                # Gate 4 (TODOS.md:19): consume finding_approval actions so
                # approved findings flow back into egs.state and the
                # dashboard's green-check becomes truthful.
                # TTL-evict stale command_ids before lookup. Same pattern as
                # process_findings' _seen_finding_ids eviction.
                now_s = time.time()
                while self._seen_approval_command_ids and (
                    now_s - self._seen_approval_command_ids[0][1]
                    >= SEEN_FINDING_ID_TTL_S
                ):
                    expired_cid, _ = self._seen_approval_command_ids.popleft()
                    self._seen_approval_command_id_set.discard(expired_cid)

                cmd_id = action.get("command_id")
                if cmd_id and cmd_id in self._seen_approval_command_id_set:
                    logger.info(
                        "egs.finding_approval duplicate dropped command_id=%s",
                        cmd_id,
                    )
                    continue
                finding_id = action.get("finding_id")
                approval_action = action.get("action")  # "approve" or "dismiss"
                if finding_id and approval_action in ("approve", "dismiss"):
                    approved = egs_state.setdefault("approved_findings", {})
                    # Map the operator_actions schema value to the egs_state
                    # schema value ("approve" → "approved", "dismiss" → "dismissed").
                    status = "approved" if approval_action == "approve" else "dismissed"
                    # FIFO cap on the approved_findings map to defend against long
                    # runs with many operator decisions. Order is dict-insertion
                    # (Python 3.7+ guarantee) so popping arbitrary items via iter()
                    # gives us oldest-first eviction.
                    if (
                        finding_id not in approved
                        and len(approved) >= MAX_APPROVED_FINDINGS
                    ):
                        oldest = next(iter(approved))
                        del approved[oldest]
                        logger.info(
                            "egs.finding_approval cap evicted oldest finding_id=%s",
                            oldest,
                        )
                    approved[finding_id] = status
                    if cmd_id:
                        self._seen_approval_command_ids.append((cmd_id, now_s))
                        self._seen_approval_command_id_set.add(cmd_id)
                    logger.info(
                        "egs.finding_approval confirmed finding_id=%s action=%s",
                        finding_id,
                        status,
                    )
                else:
                    logger.warning(
                        "egs.finding_approval malformed: finding_id=%s action=%s",
                        finding_id,
                        approval_action,
                    )

        return {**state, "egs_state": egs_state, "trigger_replan": trigger_replan, "incoming_actions": []}

    def refresh_validation_events(self, state: EGSState) -> EGSState:
        """Every Nth tick, refresh `egs_state.recent_validation_events` from
        the Contract 11 JSONL log on disk. Off-ticks are pass-through so the
        graph never reads the file on every iteration.
        """
        self._validation_refresh_counter += 1
        if self._validation_refresh_counter % VALIDATION_REFRESH_EVERY_N_TICKS != 0:
            return state
        # Imported lazily so tests can monkeypatch
        # `agents.egs_agent.validation_log_tail.LOG_PATH` and have it picked up
        # without reaching into the symbol bound at coordinator-import time.
        from agents.egs_agent import validation_log_tail
        egs_state = state["egs_state"].copy()
        egs_state["recent_validation_events"] = validation_log_tail.tail(n=10)
        # Phase 1 (GATE 4 wow moment): mirror the transient attempt log onto
        # the egs_state snapshot so the bridge picks it up on the next 1Hz
        # publish. Deep-copy so consumers can't mutate our internal bucket.
        egs_state["replan_in_flight_attempt_log"] = deepcopy(self._replan_attempt_log)
        return {**state, "egs_state": egs_state}

    async def replan(self, state: EGSState) -> EGSState:
        """Fire-and-forget: spawn the LLM-driven replan in the background and
        return immediately so the coordinator tick doesn't block on the 5-15s
        Gemma 4 E4B call. A re-entrancy guard prevents stacking parallel replans.

        The flag is set synchronously here (not inside `_replan_impl`) so that
        a second tick firing before the spawned task gets its first await slot
        cannot also pass the guard. `asyncio.create_task` only schedules; the
        coroutine's first line runs on the next loop iteration, which is too
        late to gate fast back-to-back replans.
        """
        if self._replan_in_flight:
            logger.info("egs.replan skipped (already in flight)")
            return {**state, "trigger_replan": False}
        self._replan_in_flight = True
        snapshot = deepcopy(state["egs_state"])
        asyncio.create_task(self._replan_impl(snapshot))
        return {**state, "trigger_replan": False}

    async def _replan_impl(self, egs_state_snapshot: Dict[str, Any]) -> None:
        """Background task: call assign_survey_points + publish per-drone tasks
        directly to Redis (bypassing per-tick messages_to_publish).

        `_replan_in_flight` is set by the caller (`replan`) before this task
        is scheduled; we only clear it here in the `finally` block.

        GH #32 / Bug 3 fix: wrap the assign_survey_points await in
        `asyncio.wait_for` so a hung Ollama call (VRAM eviction stall, daemon
        wedge) cannot lock the in-flight slot indefinitely. Without this,
        every subsequent replan trigger — including drone_failure-triggered
        replans — gets dedup-skipped forever. See module-level
        REPLAN_OVERALL_TIMEOUT_S for sizing rationale.
        """
        try:
            try:
                assignment = await asyncio.wait_for(
                    assign_survey_points(
                        egs_state_snapshot,
                        self.validation_node,
                        validation_logger=self._validation_log,
                        log_sink=self._append_replan_attempt,
                    ),
                    timeout=REPLAN_OVERALL_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "egs.replan abandoned after %.0fs (assign_survey_points hung "
                    "— probably Ollama VRAM eviction stall). In-flight slot will "
                    "be cleared so the next trigger can run.",
                    REPLAN_OVERALL_TIMEOUT_S,
                )
                return
            if not assignment:
                return
            if not self.redis_client:
                logger.warning(
                    "egs.replan: assignment computed but redis_client is None; "
                    "tasks dropped (this is a wiring bug, not a runtime condition)"
                )
                return
            args = assignment.get("arguments", {})
            assignments_list = args.get("assignments", [])
            for a in assignments_list:
                drone_id = a.get("drone_id")
                points = a.get("survey_point_ids", [])
                now = datetime.now(timezone.utc)
                task_payload = {
                    "task_id": f"task_{now.timestamp()}",
                    "drone_id": drone_id,
                    "issued_at": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "task_type": "survey",
                    "assigned_survey_points": [{"id": p, "lat": 0.0, "lon": 0.0} for p in points],
                    "priority_override": None,
                    "valid_until": "2026-12-31T23:59:59.000Z",
                }
                await self.redis_client.publish(
                    per_drone_tasks_channel(drone_id),
                    json.dumps(task_payload),
                )
            # Survey-points status loop-back: tell the main loop to flip
            # `egs_state.survey_points[*].status` from "unassigned" to
            # "assigned" with the matching `assigned_to`. main.py subscribes
            # to "egs.replan_events" and applies this envelope via
            # _apply_survey_assignments. Avoids coupling this background task
            # to main.py's state_ref dict.
            await self.redis_client.publish(
                "egs.replan_events",
                json.dumps({
                    "type": "survey_assignments",
                    "assignments": [
                        {
                            "drone_id": a.get("drone_id"),
                            "survey_point_ids": a.get("survey_point_ids", []),
                        }
                        for a in assignments_list
                    ],
                    "issued_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%S.000Z"
                    ),
                }),
            )
        except Exception as e:
            logger.exception("egs.replan background task failed: %s", e)
        finally:
            self._replan_in_flight = False
            # Phase 1 (GATE 4 wow moment): banner stays visible for a short
            # grace window after replan completes (success or fallback), then
            # the transient log clears so the dashboard hides the banner.
            # _append_replan_attempt cancels this handle if a fresh replan
            # starts inside the grace window — back-to-back replans don't
            # drop each other's entries.
            self._schedule_replan_attempt_log_clear()
