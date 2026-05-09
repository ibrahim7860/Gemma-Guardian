import asyncio
import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import TypedDict, Dict, Any, List

from langgraph.graph import StateGraph, START, END

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
        self.graph = self._build_graph()

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

        for f in state.get("incoming_findings", []):
            val_res = self.validation_node.validate_finding(f)
            if val_res.valid:
                ftype = f.get("type")
                if ftype in counts:
                    counts[ftype] += 1
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

            logger.info("process_commands: translation result valid=%s kind=%s cmd=%s",
                        translation.get("valid"), translation.get("kind"),
                        translation.get("structured", {}).get("command"))

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
        """
        try:
            assignment = await assign_survey_points(egs_state_snapshot, self.validation_node)
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
