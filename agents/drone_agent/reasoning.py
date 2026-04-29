"""Reasoning node — calls Gemma 4 E2B via Ollama with the drone tool schema."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import httpx

from .perception import PerceptionBundle

PROMPT_DIR = Path(__file__).resolve().parents[2] / "shared" / "prompts"
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "shared" / "schemas"

DRONE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "report_finding",
            "description": "Report something you observed (victim, fire, smoke, damaged structure, blocked route).",
            "parameters": {
                "type": "object",
                "required": ["type", "severity", "gps_lat", "gps_lon", "confidence", "visual_description"],
                "properties": {
                    "type": {"type": "string", "enum": ["victim", "fire", "smoke", "damaged_structure", "blocked_route"]},
                    "severity": {"type": "integer", "minimum": 1, "maximum": 5},
                    "gps_lat": {"type": "number"},
                    "gps_lon": {"type": "number"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "visual_description": {"type": "string", "minLength": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_explored",
            "parameters": {
                "type": "object",
                "required": ["zone_id", "coverage_pct"],
                "properties": {
                    "zone_id": {"type": "string"},
                    "coverage_pct": {"type": "number", "minimum": 0.0, "maximum": 100.0},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_assist",
            "parameters": {
                "type": "object",
                "required": ["reason", "urgency"],
                "properties": {
                    "reason": {"type": "string"},
                    "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
                    "related_finding_id": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "return_to_base",
            "parameters": {
                "type": "object",
                "required": ["reason"],
                "properties": {
                    "reason": {"type": "string", "enum": ["low_battery", "mission_complete", "ordered", "mechanical", "weather"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "continue_mission",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def load_system_prompt() -> str:
    return (PROMPT_DIR / "drone_agent_system.md").read_text()


def load_user_template() -> str:
    return (PROMPT_DIR / "drone_agent_user_template.md").read_text()


def render_user_message(bundle: PerceptionBundle) -> str:
    template = load_user_template()
    return template.format(
        state_json=json.dumps(_state_dict(bundle.state), indent=2),
        zone_bounds_json=json.dumps(bundle.state.zone_bounds, indent=2),
        n_remaining=bundle.state.assigned_survey_points_remaining,
        next_waypoint=json.dumps(bundle.state.next_waypoint) if bundle.state.next_waypoint else "none",
        peer_broadcasts_summary=_summarize_broadcasts(bundle.peer_broadcasts),
        operator_commands_summary=_summarize_operator_commands(bundle.operator_commands),
    )


def _state_dict(s) -> dict:
    return {
        "drone_id": s.drone_id,
        "position": {"lat": s.lat, "lon": s.lon, "alt": s.alt},
        "battery_pct": s.battery_pct,
        "heading_deg": s.heading_deg,
        "current_task": s.current_task,
    }


def _summarize_broadcasts(broadcasts: list) -> str:
    if not broadcasts:
        return "(none)"
    lines = []
    for b in broadcasts[-5:]:
        lines.append(f"- {b.get('sender_id')}: {b.get('broadcast_type')} {json.dumps(b.get('payload', {}))}")
    return "\n".join(lines)


def _summarize_operator_commands(cmds: list) -> str:
    if not cmds:
        return "(none)"
    return "\n".join(f"- {c}" for c in cmds[-3:])


class ReasoningNode:
    def __init__(self, model: str = "gemma-4:e2b", endpoint: str = "http://localhost:11434", timeout_s: float = 30.0):
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.timeout_s = timeout_s
        self.system_prompt = load_system_prompt()

    async def call(self, bundle: PerceptionBundle, conversation: list[dict] | None = None) -> dict[str, Any]:
        """Returns Ollama's raw response dict. Caller parses tool_calls."""
        if conversation is None:
            conversation = self._initial_messages(bundle)

        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(
                f"{self.endpoint}/api/chat",
                json={
                    "model": self.model,
                    "messages": conversation,
                    "tools": DRONE_TOOLS,
                    "stream": False,
                    "options": {"temperature": 0.2},
                },
            )
            r.raise_for_status()
            return r.json()

    def _initial_messages(self, bundle: PerceptionBundle) -> list[dict]:
        b64 = base64.b64encode(bundle.frame_jpeg).decode("ascii")
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": render_user_message(bundle), "images": [b64]},
        ]

    @staticmethod
    def parse_function_call(response: dict) -> dict | None:
        msg = response.get("message", {})
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return None
        first = tool_calls[0].get("function", {})
        name = first.get("name")
        args = first.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                return None
        if not name:
            return None
        return {"function": name, "arguments": args or {}}
