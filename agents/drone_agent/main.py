"""Drone agent main loop. Wires perception → reasoning → validation → action → memory.

Implements the Algorithm 1 retry loop from Nguyen et al. 2026 (see docs/10-validation-and-retry-loop.md).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from pathlib import Path

from agents.drone_agent.action import ActionNode, StdoutPublisher
from agents.drone_agent.memory import MemoryStore
from agents.drone_agent.perception import PerceptionBundle, PerceptionNode
from agents.drone_agent.reasoning import ReasoningNode, render_user_message
from agents.drone_agent.validation import ValidationNode

VALIDATION_LOG_PATH = Path("/tmp/fieldagent_logs/validation_events.jsonl")

logger = logging.getLogger("drone_agent")


def _safe_fallback() -> dict:
    return {"function": "continue_mission", "arguments": {}}


def _log_validation_event(drone_id: str, task: str, attempt: int, result, call: dict | None) -> None:
    VALIDATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with VALIDATION_LOG_PATH.open("a") as f:
        f.write(json.dumps({
            "agent_id": drone_id,
            "task": task,
            "attempt": attempt,
            "outcome": "passed" if result.valid else "failed",
            "failure_reason": result.failure_reason,
            "call": call,
        }) + "\n")


class DroneAgent:
    def __init__(self, drone_id: str, ollama_endpoint: str = "http://localhost:11434", model: str = "gemma4:e2b", max_retries: int = 3, send_image: bool = True, extra_options: dict | None = None):
        self.drone_id = drone_id
        self.perception = PerceptionNode()
        self.reasoning = ReasoningNode(model=model, endpoint=ollama_endpoint, send_image=send_image, extra_options=extra_options)
        self.validation = ValidationNode()
        self.action = ActionNode(drone_id=drone_id, publisher=StdoutPublisher())
        self.memory = MemoryStore(drone_id=drone_id)
        self.max_retries = max_retries

    async def step(self, bundle: PerceptionBundle) -> dict:
        conversation = self.reasoning._initial_messages(bundle)
        last_call: dict | None = None

        for attempt in range(self.max_retries):
            response = await self.reasoning.call(bundle, conversation)
            last_call = self.reasoning.parse_function_call(response)
            result = self.validation.validate(last_call, bundle)
            _log_validation_event(self.drone_id, "report_finding" if last_call else "parse", attempt, result, last_call)

            if result.valid:
                self.validation.record_success(last_call, bundle)
                self.memory.record_decision(last_call, result, attempt)
                self.action.execute(last_call, sender_position={
                    "lat": bundle.state.lat, "lon": bundle.state.lon, "alt": bundle.state.alt,
                })
                return last_call

            assistant_msg = response.get("message", {})
            conversation.append({
                "role": "assistant",
                "content": assistant_msg.get("content", "") or json.dumps(last_call or {}),
            })
            conversation.append({
                "role": "user",
                "content": (
                    f"Your previous response was rejected because: {result.failure_reason}\n\n"
                    f"{result.corrective_prompt}\n\n"
                    "Try again. Call exactly one function."
                ),
            })

        fallback = _safe_fallback()
        self.memory.record_decision(fallback, type("R", (), {"valid": True, "failure_reason": "max_retries_exhausted"})(), self.max_retries)
        self.action.execute(fallback, sender_position={
            "lat": bundle.state.lat, "lon": bundle.state.lon, "alt": bundle.state.alt,
        })
        logger.warning("max retries exhausted; fell back to continue_mission")
        return fallback


async def run_loop(agent: DroneAgent, frame_provider, state_provider, peer_provider, command_provider, period_s: float = 1.0):
    """Production-style loop. frame_provider returns a numpy frame, state_provider returns DroneState, etc."""
    while True:
        frame = await frame_provider()
        state = await state_provider()
        peers = await peer_provider()
        cmds = await command_provider()
        bundle = agent.perception.build(frame, state, peers, cmds)
        try:
            await agent.step(bundle)
        except Exception as e:
            logger.exception("step failed: %s", e)
        await asyncio.sleep(period_s)
