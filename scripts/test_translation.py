"""Quick diagnostic: tests the full translation pipeline in isolation."""
import asyncio
import json
import httpx
from shared.contracts import CONFIG
from shared.contracts.adapters import normalize, AdapterError

async def main():
    endpoint = f"{CONFIG.inference.ollama_egs_endpoint}/api/chat"
    print(f"[1] Ollama endpoint: {endpoint}")
    print(f"[2] Model: {CONFIG.inference.egs_model}")

    # Step A: Can we even reach Ollama?
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{CONFIG.inference.ollama_egs_endpoint}/api/tags", timeout=10.0)
            tags = resp.json()
            models = [m["name"] for m in tags.get("models", [])]
            print(f"[3] Available models: {models}")
            if CONFIG.inference.egs_model not in models:
                print(f"[!!] Model '{CONFIG.inference.egs_model}' NOT found! Pull it with: ollama pull {CONFIG.inference.egs_model}")
                return
    except Exception as e:
        print(f"[!!] Cannot reach Ollama: {e}")
        return

    # Step B: Send a real translation request — uses the EXACT same prompt as command_translator.py
    language = "Spanish"
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
Active drones: ['drone1', 'drone2', 'drone3']
"""
    payload = {
        "model": CONFIG.inference.egs_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Return drone1 to base immediately"}
        ],
        "stream": False,
        "format": "json"
    }

    print("[4] Sending translation request to Ollama (this may take a minute on first run)...")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(endpoint, json=payload, timeout=180.0)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"[!!] Ollama request failed: {e}")
        return

    raw_content = data.get("message", {}).get("content", "")
    print(f"[5] Raw LLM content:\n    {raw_content}")

    # Step C: Try normalizing
    try:
        canonical = normalize(data, layer="operator")
        print(f"[6] Normalized canonical:\n    {json.dumps(canonical, indent=2)}")
    except AdapterError as e:
        print(f"[!!] Normalization failed: {e}")
        return

    # Step D: Strip preview fields and check what remains
    preview_text = canonical.pop("preview_text", "N/A")
    preview_text_in_op = canonical.pop("preview_text_in_operator_language", "N/A")
    print(f"[7] preview_text: {preview_text}")
    print(f"[8] preview_text_in_operator_language: {preview_text_in_op}")
    print(f"[9] Canonical after stripping:\n    {json.dumps(canonical, indent=2)}")

    # Step E: Try schema validation
    from shared.contracts import validate
    outcome = validate("operator_commands", canonical)
    print(f"[10] Schema valid: {outcome.valid}")
    if not outcome.valid:
        for err in outcome.errors:
            print(f"     Error: {err.message}")
    else:
        print("[SUCCESS] Translation pipeline works end-to-end!")

asyncio.run(main())
