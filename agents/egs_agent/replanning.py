import json
import logging
from typing import Dict, Any, List
import httpx

from shared.contracts import (
    CONFIG, RuleID, normalize, validate, AssignSurveyPoints, ReplanMission,
    AdapterError, RULE_REGISTRY
)
from agents.egs_agent.validation import EGSValidationNode

logger = logging.getLogger(__name__)

async def assign_survey_points(
    egs_state: Dict[str, Any],
    validation_node: EGSValidationNode
) -> Dict[str, Any]:
    """Generates the survey point assignment using Gemma 4 E4B."""
    
    survey_points = egs_state.get("survey_points", [])
    drones = egs_state.get("drones_summary", {})
    
    active_drones = [d for d, info in drones.items() if info.get("status") == "active"]
    available_points = [p["id"] for p in survey_points if p.get("status") in ("unassigned", "failed")]
    
    if not available_points or not active_drones:
        return {}

    system_prompt = f"""You are the swarm coordinator. 
Assign the following survey points to the active drones.
Active Drones: {active_drones}
Survey Points: {available_points}

Rules:
1. Every point must be assigned to exactly one drone.
2. Balance the workload so drones have approximately the same number of points.
3. No duplicate points.
"""

    endpoint = f"{CONFIG.inference.ollama_egs_endpoint}/api/chat"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Generate the assignment."}
    ]
    
    retries = 0
    max_retries = CONFIG.validation.max_retries
    
    while retries <= max_retries:
        payload = {
            "model": CONFIG.inference.egs_model,
            "messages": messages,
            "stream": False,
            "format": "json"
        }
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(endpoint, json=payload, timeout=45.0)
                resp.raise_for_status()
                data = resp.json()
                
                # Normalize
                canonical = normalize(data, layer="egs")
                
                # Structural Validation
                val_res = validation_node.validate_egs_function_call(canonical)
                if not val_res.valid:
                    rule = RULE_REGISTRY.get(val_res.failure_reason)
                    correction = rule.corrective_template.format(
                        field_path="", message=val_res.detail
                    ) if rule else val_res.detail
                    messages.append({"role": "assistant", "content": json.dumps(canonical)})
                    messages.append({"role": "user", "content": correction})
                    retries += 1
                    continue
                
                # Semantic / Stateful Validation
                if canonical.get("function") != "assign_survey_points":
                    messages.append({"role": "assistant", "content": json.dumps(canonical)})
                    messages.append({"role": "user", "content": "You must use the assign_survey_points function."})
                    retries += 1
                    continue
                    
                args = canonical.get("arguments", {})
                assignments = args.get("assignments", [])
                
                # ASSIGNMENT_TOTAL_MISMATCH
                assigned_pts = sum([len(a.get("survey_point_ids", [])) for a in assignments])
                if assigned_pts != len(available_points):
                    rule = RULE_REGISTRY[RuleID.ASSIGNMENT_TOTAL_MISMATCH]
                    correction = rule.corrective_template.format(assigned=assigned_pts, total=len(available_points))
                    messages.append({"role": "assistant", "content": json.dumps(canonical)})
                    messages.append({"role": "user", "content": correction})
                    retries += 1
                    continue
                
                # ASSIGNMENT_DUPLICATE_POINT
                all_assigned = []
                for a in assignments:
                    all_assigned.extend(a.get("survey_point_ids", []))
                if len(all_assigned) != len(set(all_assigned)):
                    rule = RULE_REGISTRY[RuleID.ASSIGNMENT_DUPLICATE_POINT]
                    # We could find the actual duplicate, but just use template
                    correction = rule.corrective_template.format(point_id="some_point")
                    messages.append({"role": "assistant", "content": json.dumps(canonical)})
                    messages.append({"role": "user", "content": correction})
                    retries += 1
                    continue
                    
                # ASSIGNMENT_DRONE_MISSING
                assigned_drones = [a.get("drone_id") for a in assignments]
                missing = [d for d in active_drones if d not in assigned_drones]
                if missing:
                    rule = RULE_REGISTRY[RuleID.ASSIGNMENT_DRONE_MISSING]
                    correction = rule.corrective_template.format(drone_id=missing[0])
                    messages.append({"role": "assistant", "content": json.dumps(canonical)})
                    messages.append({"role": "user", "content": correction})
                    retries += 1
                    continue

                # Everything valid!
                return canonical

        except AdapterError as e:
            messages.append({"role": "assistant", "content": "I failed to generate valid json."})
            messages.append({"role": "user", "content": f"Return a proper JSON object. Error: {e}"})
            retries += 1
        except Exception as e:
            logger.error(f"Error during replanning: {e}")
            retries += 1
            
    # Failed after retries - fallback deterministic (round robin)
    logger.error("LLM Replanning failed after retries, using deterministic fallback.")
    fallback_assignments = [{"drone_id": d, "survey_point_ids": []} for d in active_drones]
    for i, pt in enumerate(available_points):
        fallback_assignments[i % len(active_drones)]["survey_point_ids"].append(pt)
        
    return {
        "function": "assign_survey_points",
        "arguments": {
            "assignments": fallback_assignments
        }
    }
