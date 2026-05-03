from typing import TypedDict, Dict, Any, List
import logging
from datetime import datetime

from langgraph.graph import StateGraph, START, END

from shared.contracts.topics import per_drone_tasks_channel
from agents.egs_agent.validation import EGSValidationNode
from agents.egs_agent.replanning import assign_survey_points
from agents.egs_agent.command_translator import translate_operator_command

logger = logging.getLogger(__name__)

class EGSState(TypedDict):
    egs_state: Dict[str, Any]
    incoming_telemetry: List[Dict[str, Any]]
    incoming_findings: List[Dict[str, Any]]
    incoming_commands: List[Dict[str, Any]]
    messages_to_publish: List[Dict[str, Any]] # e.g. {"channel": "...", "data": "..."}
    trigger_replan: bool

class EGSCoordinator:
    def __init__(self, validation_node: EGSValidationNode):
        self.validation_node = validation_node
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(EGSState)

        workflow.add_node("process_telemetry", self.process_telemetry)
        workflow.add_node("process_findings", self.process_findings)
        workflow.add_node("process_commands", self.process_commands)
        workflow.add_node("replan", self.replan)

        workflow.add_edge(START, "process_telemetry")
        workflow.add_edge("process_telemetry", "process_findings")
        workflow.add_edge("process_findings", "process_commands")
        
        def should_replan(state: EGSState):
            if state.get("trigger_replan", False):
                return "replan"
            return END

        workflow.add_conditional_edges("process_commands", should_replan)
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
                "last_seen": t.get("timestamp")
            }
            
            # If drone went offline, replan!
            if prev_status == "active" and new_status == "offline":
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
                logger.info(f"Accepted finding: {ftype} from {f.get('source_drone_id')}")
            else:
                logger.info(f"Rejected duplicate finding: {val_res.detail}")

        return {**state, "egs_state": egs_state, "incoming_findings": []}

    async def process_commands(self, state: EGSState) -> EGSState:
        msgs_to_pub = state.get("messages_to_publish", []).copy()
        trigger_replan = state.get("trigger_replan", False)
        
        for c in state.get("incoming_commands", []):
            op_txt = c.get("raw_text", "")
            lang = c.get("language", "en")
            cmd_id = c.get("command_id", "")
            
            translation = await translate_operator_command(op_txt, lang, state["egs_state"], self.validation_node)
            translation["command_id"] = cmd_id
            translation["contract_version"] = "1.0.0"
            
            # Output translation back to WebSocket bridge (or just log it)
            msgs_to_pub.append({
                "channel": "egs.operator_actions", # example channel
                "data": translation
            })
            
            if translation.get("valid"):
                # some commands trigger replan
                cmd_name = translation["structured"].get("command")
                if cmd_name in ["restrict_zone", "exclude_zone", "recall_drone"]:
                    trigger_replan = True
                    
        return {**state, "trigger_replan": trigger_replan, "incoming_commands": [], "messages_to_publish": msgs_to_pub}

    async def replan(self, state: EGSState) -> EGSState:
        logger.info("Executing replan...")
        egs_state = state["egs_state"].copy()
        msgs_to_pub = state.get("messages_to_publish", []).copy()
        
        assignment = await assign_survey_points(egs_state, self.validation_node)
        
        if assignment:
            args = assignment.get("arguments", {})
            assignments = args.get("assignments", [])
            
            for a in assignments:
                drone_id = a.get("drone_id")
                points = a.get("survey_point_ids", [])
                
                # Update local survey point status
                for pt in egs_state.get("survey_points", []):
                    if pt["id"] in points:
                        pt["assigned_to"] = drone_id
                        pt["status"] = "assigned"
                
                # Publish task assignment to drone
                msgs_to_pub.append({
                    "channel": per_drone_tasks_channel(drone_id),
                    "data": {
                        "task_id": f"task_{datetime.utcnow().timestamp()}",
                        "drone_id": drone_id,
                        "issued_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                        "task_type": "survey",
                        "assigned_survey_points": [{"id": p, "lat": 0.0, "lon": 0.0} for p in points], # simplified
                        "priority_override": None,
                        "valid_until": "2026-12-31T23:59:59.000Z"
                    }
                })
        
        return {**state, "egs_state": egs_state, "trigger_replan": False, "messages_to_publish": msgs_to_pub}

