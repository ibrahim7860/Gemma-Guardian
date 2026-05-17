import argparse
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
import redis.asyncio as redis

from shared.contracts import CONFIG
from shared.contracts.topics import (
    PER_DRONE_STATE, PER_DRONE_FINDINGS, EGS_STATE,
    SIM_SCRIPTED_EVENTS,
)
from agents.egs_agent.validation import EGSValidationNode
from agents.egs_agent.coordinator import EGSCoordinator
from agents.egs_agent.scenario_state import build_initial_egs_state

logging.basicConfig(level=getattr(logging, CONFIG.logging.level, "INFO"))
logger = logging.getLogger(__name__)

# Wave 3a (Component 4): silent-zero diagnostic log cadence. Every 30s the
# EGS emits "egs.findings_consumed total=N" — even at zero — so that a
# broken channel migration or a mid-run mesh-sim crash is visible in logs
# instead of being mistaken for "no findings yet".
FINDINGS_CONSUMED_LOG_PERIOD_S = 30.0


async def _await_mesh_sim(redis_client, timeout_s: float = 5.0) -> None:
    """Wait for at least one heartbeat on ``mesh.adjacency_matrix``.

    The mesh sim publishes adjacency at 1 Hz unconditionally (see
    ``agents/mesh_simulator/main.py`` ``_adjacency_thread``). Absence after
    ``timeout_s`` means the gateway isn't running — every gated finding
    would silently never reach EGS — so we fail fast with a remediation
    hint instead of starting the main loop.
    """
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("mesh.adjacency_matrix")
    deadline = time.time() + timeout_s
    try:
        while time.time() < deadline:
            msg = await pubsub.get_message(
                timeout=0.5, ignore_subscribe_messages=True,
            )
            if msg is not None:
                return
    finally:
        try:
            await pubsub.unsubscribe("mesh.adjacency_matrix")
        except Exception:  # pragma: no cover — defensive cleanup
            pass
    raise RuntimeError(
        "mesh_simulator not detected on mesh.adjacency_matrix within "
        f"{timeout_s}s. Findings WILL NOT be delivered to EGS without it. "
        "Start it: `python -m agents.mesh_simulator`."
    )


async def findings_consumed_log_loop(
    coordinator: EGSCoordinator,
    period_s: float = FINDINGS_CONSUMED_LOG_PERIOD_S,
) -> None:
    """Periodic silent-zero diagnostic.

    Reads ``coordinator._findings_accepted_total`` and emits
    ``egs.findings_consumed total=N`` once per ``period_s`` seconds. Fires
    even when N is zero — that's the diagnostic signature for broken
    migrations or mesh-sim crashes mid-run.
    """
    while True:
        await asyncio.sleep(period_s)
        total = coordinator._findings_accepted_total
        logger.info("egs.findings_consumed total=%d", total)

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
                # Deep copy to avoid mutating the coordinator's in-memory state
                pub_state = {k: v for k, v in state.items() if k != "pending_commands"}
                pub_state["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                await redis_client.publish(EGS_STATE, json.dumps(pub_state))
        except Exception as e:
            logger.error(f"Error publishing EGS state: {e}")
        await asyncio.sleep(1.0)

def _parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inject-overcount-once", action="store_true",
        help="Phase 3c debug fallback: deterministically injects a hallucination into the first LLM assignment."
    )
    parser.add_argument(
        "--scenario", default=None,
        help="Scenario YAML name (overrides CONFIG.mission.scenario_id). Required when sim/drones use a "
             "non-default scenario so EGS publishes the matching zone_polygon."
    )
    return parser.parse_known_args()[0]

async def main():
    args = _parse_args()
    if args.inject_overcount_once:
        logger.warning(
            "Phase 3c: --inject-overcount-once enabled. First replan's attempt-1 "
            "LLM output will be mutated to fire ASSIGNMENT_TOTAL_MISMATCH."
        )

    logger.info("Starting EGS Agent...")
    redis_client = redis.from_url(CONFIG.transport.redis_url)

    # Wave 3a (Component 4): mesh-sim availability healthcheck.
    # Fail fast if the gateway isn't up — without it the .delivered channel
    # is silent and every finding is dropped.
    await _await_mesh_sim(redis_client)

    pubsub = redis_client.pubsub()

    # Pattern subscribe
    await pubsub.psubscribe("drones.*.state")
    # PR1 channel migration: findings now flow via the mesh-simulator-gated
    # `.delivered` channel. The mesh sim psubs the raw `drones.*.findings`
    # publish from drones and republishes verbatim on `.delivered`. PR1 is a
    # pure refactor — gating arrives in PR2.
    logger.info("egs subscribing to %s for findings", "drones.*.findings.delivered")
    await pubsub.psubscribe("drones.*.findings.delivered")
    await pubsub.subscribe("egs.operator_commands") # Assuming this channel exists for incoming commands
    await pubsub.subscribe("egs.operator_actions")
    # Loop-back channel: _replan_impl publishes survey-point assignments here
    # after the LLM call so the main loop can update egs_state.survey_points
    # without coupling the background task to state_ref. Per Contract 9 this
    # is the existing "egs.replan_events" debug-only channel; we put a
    # structured envelope on it so the main loop can recognize and apply it.
    await pubsub.subscribe("egs.replan_events")
    # Gate 4: subscribe to scripted events so drone_failure triggers replan
    # immediately (Gate 4 pass criterion: "EGS replanning successfully
    # reassigns survey points after scripted drone failure event").
    await pubsub.subscribe(SIM_SCRIPTED_EVENTS)
    
    validation_node = EGSValidationNode()
    coordinator = EGSCoordinator(
        validation_node,
        redis_client=redis_client,
        inject_overcount_once=args.inject_overcount_once,
    )
    
    # Initial state derived from the active scenario YAML (Contract 3-compliant).
    # --scenario CLI overrides CONFIG.mission.scenario_id so EGS publishes a
    # zone_polygon matching what the sim and drones are using. Without this,
    # the drones' update_from_polygon overwrites their CLI-derived zone with
    # the (mismatched) CONFIG zone, and validator rejects in-scenario findings
    # as GPS_OUTSIDE_ZONE. See docs/runbooks/runpod-resume.md "Phase 6 fix".
    scenario_id = args.scenario or CONFIG.mission.scenario_id
    egs_state = build_initial_egs_state(scenario_id)
    
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
    # Wave 3a (Component 4): silent-zero diagnostic log task.
    asyncio.create_task(findings_consumed_log_loop(coordinator))
    
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
                elif channel.endswith(".findings.delivered"):
                    # PR1: EGS now consumes the mesh-sim-gated copy.
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
                elif channel == SIM_SCRIPTED_EVENTS:
                    # Gate 4: react to scripted events. drone_failure injects
                    # synthetic offline telemetry so the existing
                    # active → offline replan trigger fires immediately.
                    event_type = data.get("type")
                    if event_type == "drone_failure":
                        drone_id = data.get("drone_id")
                        if drone_id:
                            logger.info(
                                "egs.scripted_event drone_failure drone_id=%s",
                                drone_id,
                            )
                            state["incoming_telemetry"].append({
                                "drone_id": drone_id,
                                "agent_status": "offline",
                                "battery_pct": 0,
                            })
            
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
