import json
import logging
from typing import Dict, Any, List

import httpx

from shared.contracts import (
    CONFIG, RuleID, normalize, validate, OperatorCommand,
    AdapterError, RULE_REGISTRY
)
from agents.egs_agent.validation import EGSValidationNode

logger = logging.getLogger(__name__)

async def translate_operator_command(
    operator_text: str,
    language: str,
    egs_state: Dict[str, Any],
    validation_node: EGSValidationNode
) -> Dict[str, Any]:
    """Translates natural language to an OperatorCommand schema."""
    
    system_prompt = f"""You are the EGS command translator for a disaster response drone swarm.
Your job is to translate the operator's natural language into one of the available commands:
restrict_zone, exclude_zone, recall_drone, set_priority, set_language, or unknown_command.
If you cannot understand the command, return unknown_command with a suggestion.

Current swarm state summary:
Active drones: {list(egs_state.get('drones_summary', {}).keys())}
"""
    
    endpoint = f"{CONFIG.inference.ollama_egs_endpoint}/api/chat"
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": operator_text}
    ]
    
    retries = 0
    max_retries = CONFIG.validation.max_retries
    
    while retries <= max_retries:
        payload = {
            "model": CONFIG.inference.egs_model,
            "messages": messages,
            "stream": False
        }
        
        # Depending on configuration, we either use tools or structured output
        # For simplicity, we fallback to just asking for JSON matching the schema
        # but in a real scenario we'd inject the schema here.
        payload["format"] = "json"
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(endpoint, json=payload, timeout=30.0)
                resp.raise_for_status()
                data = resp.json()
                
                # Use shared normalize
                canonical = normalize(data, layer="operator")
                
                # Structural Validation
                val_res = validation_node.validate_operator_command(canonical)
                if not val_res.valid:
                    rule = RULE_REGISTRY.get(val_res.failure_reason)
                    correction = rule.corrective_template.format(
                        field_path="", message=val_res.detail
                    ) if rule else val_res.detail
                    messages.append({"role": "assistant", "content": json.dumps(canonical)})
                    messages.append({"role": "user", "content": correction})
                    retries += 1
                    continue
                
                # Semantic / Stateful validation
                cmd_name = canonical.get("command")
                args = canonical.get("args", {})
                
                if cmd_name == "recall_drone":
                    drone_id = args.get("drone_id")
                    status = egs_state.get("drones_summary", {}).get(drone_id, {}).get("status")
                    if status != "active":
                        rule = RULE_REGISTRY[RuleID.RECALL_DRONE_NOT_ACTIVE]
                        correction = rule.corrective_template.format(
                            drone_id=drone_id, status=status
                        )
                        messages.append({"role": "assistant", "content": json.dumps(canonical)})
                        messages.append({"role": "user", "content": correction})
                        retries += 1
                        continue

                # Everything valid!
                return {
                    "type": "command_translation",
                    "structured": canonical,
                    "valid": True,
                    "preview_text": f"Translating to {cmd_name}",
                    "preview_text_in_operator_language": f"Translation for {language}",
                }

        except AdapterError as e:
            messages.append({"role": "assistant", "content": "I failed to generate valid json."})
            messages.append({"role": "user", "content": f"Return a proper JSON object. Error: {e}"})
            retries += 1
        except Exception as e:
            logger.error(f"Error during command translation: {e}")
            raise e
            
    # Failed after retries
    return {
        "type": "command_translation",
        "structured": {"command": "unknown_command", "args": {"operator_text": operator_text, "suggestion": "Failed to translate."}},
        "valid": False,
        "preview_text": "Failed to translate command",
        "preview_text_in_operator_language": "Failed to translate",
    }
