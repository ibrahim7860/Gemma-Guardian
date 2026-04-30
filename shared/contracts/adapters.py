"""Normalize Ollama tool_calls[] / structured-output content into canonical form.

Canonical form (Layer 1, 2): {"function": <name>, "arguments": {...}}
Canonical form (Layer 3):    {"command":  <name>, "args":      {...}}

The validator (shared.contracts.schemas.validate) operates on canonical form.
Any code path that takes a Gemma 4 response and validates it must first run
the response through normalize(). Raises AdapterError when the response shape
is unrecognized or malformed.
"""
from __future__ import annotations

import json
from typing import Any, Dict

Layer = str  # Literal["drone", "egs", "operator"] — not enforced at runtime


class AdapterError(Exception):
    pass


_KEYS_BY_LAYER: Dict[str, tuple] = {
    "drone": ("function", "arguments"),
    "egs": ("function", "arguments"),
    "operator": ("command", "args"),
}


def normalize(response_or_payload: Any, *, layer: str) -> Dict[str, Any]:
    """Convert an Ollama API response (or already-canonical payload) to canonical form.

    Accepts:
      - Canonical form already: passthrough (validated by key presence).
      - Ollama tool-calls path: {"message": {"tool_calls": [{"function": {"name", "arguments"}}]}}
      - Ollama structured-output path: {"message": {"content": "<json string>"}}

    Raises:
      AdapterError when the input is neither canonical nor a recognized Ollama
      response, when there are multiple tool_calls, or when content is not valid
      JSON or not a JSON object.
    """
    if layer not in _KEYS_BY_LAYER:
        raise AdapterError(f"unknown layer: {layer!r}")
    name_key, args_key = _KEYS_BY_LAYER[layer]

    if not isinstance(response_or_payload, dict):
        raise AdapterError(
            f"expected a dict (canonical form or Ollama response), got {type(response_or_payload).__name__}"
        )

    # Already canonical?
    if name_key in response_or_payload and args_key in response_or_payload:
        return response_or_payload

    # Ollama wrapper {message: {...}}?
    msg = response_or_payload.get("message")
    if not isinstance(msg, dict):
        raise AdapterError(
            f"input is neither canonical (missing {name_key!r}/{args_key!r}) "
            "nor an Ollama response (missing 'message')."
        )

    # Tool-calls path
    tool_calls = msg.get("tool_calls")
    if tool_calls is not None:
        if not isinstance(tool_calls, list) or len(tool_calls) != 1:
            count = len(tool_calls) if isinstance(tool_calls, list) else type(tool_calls).__name__
            raise AdapterError(f"expected exactly one tool_call, got {count}")
        fn = tool_calls[0].get("function", {})
        return {name_key: fn.get("name"), args_key: fn.get("arguments", {})}

    # Structured-output path
    content = msg.get("content")
    if content is not None:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"structured-output content is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise AdapterError(f"structured-output JSON must be an object, got {type(parsed).__name__}")
        # Recurse so {"message": {"content": <json with nested envelope>}} also collapses
        return normalize(parsed, layer=layer)

    raise AdapterError("Ollama 'message' has neither 'tool_calls' nor 'content'.")
