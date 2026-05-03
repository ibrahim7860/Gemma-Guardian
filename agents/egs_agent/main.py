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

logging.basicConfig(level=getattr(logging, CONFIG.logging.level, "INFO"))
logger = logging.getLogger(__name__)

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
    
    validation_node = EGSValidationNode()
    coordinator = EGSCoordinator(validation_node)
    
    # Initialize initial egs_state (mock data per contract for demo)
    egs_state = {
        "mission_id": CONFIG.mission.scenario_id,
        "mission_status": "active",
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "zone_polygon": [
            [34.1230, -118.5680], [34.1240, -118.5680],
            [34.1240, -118.5670], [34.1230, -118.5670]
        ],
        "survey_points": [
            {"id": "sp_001", "lat": 34.1232, "lon": -118.5675, "status": "unassigned"},
            {"id": "sp_002", "lat": 34.1234, "lon": -118.5673, "status": "unassigned"}
        ],
        "drones_summary": {},
        "findings_count_by_type": {
            "victim": 0, "fire": 0, "smoke": 0, "damaged_structure": 0, "blocked_route": 0
        },
        "recent_validation_events": [],
        "active_zone_ids": []
    }
    
    state_ref = {"egs_state": egs_state}
    
    # Initial trigger to assign points
    state = {
        "egs_state": egs_state,
        "incoming_telemetry": [],
        "incoming_findings": [],
        "incoming_commands": [],
        "messages_to_publish": [],
        "trigger_replan": True
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
            
            # Run graph
            # If no incoming items and no trigger_replan, we skip calling graph to save CPU
            if state["incoming_telemetry"] or state["incoming_findings"] or state["incoming_commands"] or state["trigger_replan"]:
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
