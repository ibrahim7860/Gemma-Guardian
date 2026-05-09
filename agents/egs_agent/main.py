import asyncio
import json
import logging
from datetime import datetime
import redis.asyncio as redis

from shared.contracts import CONFIG
from shared.contracts.topics import (
    PER_DRONE_STATE, PER_DRONE_FINDINGS, EGS_STATE,
)
from agents.egs_agent.validation import EGSValidationNode
from agents.egs_agent.coordinator import EGSCoordinator
from agents.egs_agent.scenario_state import build_initial_egs_state

logging.basicConfig(level=getattr(logging, CONFIG.logging.level, "INFO"))
logger = logging.getLogger(__name__)

def _apply_survey_assignments(egs_state, assignments):
    """Mutate egs_state.survey_points to reflect a fresh assignment from
    `_replan_impl`. Each `assignments` item is {drone_id, survey_point_ids}.
    Points present in the input are flipped to status="assigned" and
    assigned_to=drone_id; points absent are left untouched (in particular,
    we do NOT roll back previously-assigned points that the new assignment
    skipped — that's the LLM's failure mode, not ours).
    """
    if not assignments:
        return
    point_to_drone = {}
    for a in assignments:
        drone_id = a.get("drone_id")
        for pid in a.get("survey_point_ids", []):
            point_to_drone[pid] = drone_id
    for pt in egs_state.get("survey_points", []):
        drone_id = point_to_drone.get(pt.get("id"))
        if drone_id is None:
            continue
        pt["assigned_to"] = drone_id
        pt["status"] = "assigned"


async def publish_egs_state(redis_client, state_ref):
    """Publish the aggregated EGS state to the websocket bridge at 1Hz."""
    while True:
        try:
            state = state_ref.get("egs_state")
            if state:
                state["timestamp"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
                await redis_client.publish(EGS_STATE, json.dumps(state))
        except Exception as e:
            logger.error(f"Error publishing EGS state: {e}")
        await asyncio.sleep(1.0)

async def main():
    logger.info("Starting EGS Agent...")
    redis_client = redis.from_url(CONFIG.transport.redis_url)
    pubsub = redis_client.pubsub()
    
    # Pattern subscribe
    await pubsub.psubscribe("drones.*.state")
    await pubsub.psubscribe("drones.*.findings")
    await pubsub.subscribe("egs.operator_commands") # Assuming this channel exists for incoming commands
    await pubsub.subscribe("egs.operator_actions")
    # Loop-back channel: _replan_impl publishes survey-point assignments here
    # after the LLM call so the main loop can update egs_state.survey_points
    # without coupling the background task to state_ref. Per Contract 9 this
    # is the existing "egs.replan_events" debug-only channel; we put a
    # structured envelope on it so the main loop can recognize and apply it.
    await pubsub.subscribe("egs.replan_events")
    
    validation_node = EGSValidationNode()
    coordinator = EGSCoordinator(validation_node, redis_client=redis_client)
    
    # Initial state derived from the active scenario YAML (Contract 3-compliant).
    egs_state = build_initial_egs_state(CONFIG.mission.scenario_id)
    
    state_ref = {"egs_state": egs_state}
    
    # Coordinator now triggers initial replan on first agent_status="active"
    # telemetry, so we no longer need the unconditional startup flag.
    state = {
        "egs_state": egs_state,
        "incoming_telemetry": [],
        "incoming_findings": [],
        "incoming_commands": [],
        "incoming_actions": [],
        "messages_to_publish": [],
        "trigger_replan": False
    }
    
    asyncio.create_task(publish_egs_state(redis_client, state_ref))
    
    logger.info("Entering main event loop...")
    while True:
        try:
            # Batch process incoming messages
            messages = []
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            while msg:
                messages.append(msg)
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.01)
                
            for msg in messages:
                channel = msg['channel'].decode('utf-8')
                data = json.loads(msg['data'].decode('utf-8'))
                
                if ".state" in channel:
                    state["incoming_telemetry"].append(data)
                elif ".findings" in channel:
                    state["incoming_findings"].append(data)
                elif "operator_commands" in channel:
                    state["incoming_commands"].append(data)
                elif "operator_actions" in channel:
                    state["incoming_actions"].append(data)
                elif channel == "egs.replan_events" and data.get("type") == "survey_assignments":
                    # Apply assignment to in-memory survey_points so subsequent
                    # publish_egs_state ticks reflect the new status. This is
                    # the survey-point-status loop-back: _replan_impl publishes
                    # a {type: "survey_assignments", assignments: [...]} envelope
                    # after the LLM returns; we mutate egs_state here.
                    _apply_survey_assignments(state["egs_state"], data.get("assignments", []))
                    state_ref["egs_state"] = state["egs_state"]
            
            # Run graph
            # If no incoming items and no trigger_replan, we skip calling graph to save CPU
            if state["incoming_telemetry"] or state["incoming_findings"] or state["incoming_commands"] or state["incoming_actions"] or state["trigger_replan"]:
                state = await coordinator.graph.ainvoke(state)
                state_ref["egs_state"] = state["egs_state"]
                
                # Process outputs
                for out_msg in state.get("messages_to_publish", []):
                    await redis_client.publish(out_msg["channel"], json.dumps(out_msg["data"]))
                state["messages_to_publish"] = []
                
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            await asyncio.sleep(1.0)

if __name__ == "__main__":
    asyncio.run(main())
