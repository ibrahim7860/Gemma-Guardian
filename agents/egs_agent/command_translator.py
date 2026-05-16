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

# Per-attempt timeout for Gemma 4 E4B operator-command translation calls.
# Operator command translation runs E4B end-to-end (system prompt + state
# summary + retries) and can legitimately need >30s on slow boxes — see
# TODOS.md "command_translator.py:70". Mirrored from the same value that
# used to live inline at the post() call.
#
# Sibling constant: agents/egs_agent/replanning.py:EGS_HTTPX_PER_ATTEMPT_TIMEOUT_S = 30.0
# is intentionally tighter — replan attempts run inside an outer wait_for guard
# (GH #32 fix, Hazim commit d86a7d9), while this operator-translation path has
# no outer guard and may need the longer budget.
COMMAND_TRANSLATOR_HTTPX_PER_ATTEMPT_TIMEOUT_S = 180.0

async def translate_operator_command(
    operator_text: str,
    language: str,
    egs_state: Dict[str, Any],
    validation_node: EGSValidationNode
) -> Dict[str, Any]:
    """Translates natural language to an OperatorCommand schema."""
    
    system_prompt = f"""You are the EGS command translator for a disaster response drone swarm.
Your job is to translate the operator's natural language into one of the available commands.

Available commands and their REQUIRED args (you must include ALL required fields):
- restrict_zone: args = {{"zone_id": "<string>"}}
- exclude_zone: args = {{"zone_id": "<string>"}}
- recall_drone: args = {{"drone_id": "<droneN>", "reason": "<why>"}}
- set_priority: args = {{"finding_type": "<victim|fire|structural_damage|hazmat|road_blockage>", "priority_level": "<critical|high|medium|low>"}}
- set_language: args = {{"lang_code": "<2-letter ISO code>"}}
- unknown_command: args = {{"operator_text": "<original text>", "suggestion": "<what you think they meant>"}}

If you cannot understand the command, return unknown_command.

Your output MUST be a JSON object with these keys:
- "command": one of the command names above
- "args": object with ALL required fields for that command
- "preview_text": a short English summary of the command
- "preview_text_in_operator_language": the same summary translated into the operator's language ({language})

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
                resp = await client.post(endpoint, json=payload, timeout=COMMAND_TRANSLATOR_HTTPX_PER_ATTEMPT_TIMEOUT_S)
                resp.raise_for_status()
                data = resp.json()
                
                # Extract content string for logging/fallback
                content_str = data.get("message", {}).get("content", "{}")
                
                # Use shared normalize
                canonical = normalize(data, layer="operator")
                
                # Extract and strip extra fields to satisfy strict schema validation
                preview_text = canonical.pop("preview_text", "Translating command")
                preview_text_in_op = canonical.pop("preview_text_in_operator_language", f"Translation for {language}")
                
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

                # Everything structurally valid!
                # Per schema contract: unknown_command must always be valid=false
                is_valid = cmd_name != "unknown_command"
                return {
                    "kind": "command_translation",
                    "structured": canonical,
                    "valid": is_valid,
                    "preview_text": preview_text,
                    "preview_text_in_operator_language": preview_text_in_op,
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
        "kind": "command_translation",
        "structured": {"command": "unknown_command", "args": {"operator_text": operator_text, "suggestion": "Failed to translate."}},
        "valid": False,
        "preview_text": "Failed to translate command",
        "preview_text_in_operator_language": "Failed to translate",
    }
