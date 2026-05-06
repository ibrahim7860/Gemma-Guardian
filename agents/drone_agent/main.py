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
from shared.contracts.logging import ValidationEventLogger, default_log_dir

VALIDATION_LOG_PATH = default_log_dir() / "validation_events.jsonl"

logger = logging.getLogger("drone_agent")


def _safe_fallback() -> dict:
    return {"function": "continue_mission", "arguments": {}}


class DroneAgent:
    def __init__(self, drone_id: str, ollama_endpoint: str = "http://localhost:11434", model: str = "gemma4:e2b", max_retries: int = 3, send_image: bool = True, extra_options: dict | None = None):
        self.drone_id = drone_id
        self.perception = PerceptionNode()
        self.reasoning = ReasoningNode(model=model, endpoint=ollama_endpoint, send_image=send_image, extra_options=extra_options)
        self.validation = ValidationNode()
        self.action = ActionNode(drone_id=drone_id, publisher=StdoutPublisher())
        self.memory = MemoryStore(drone_id=drone_id)
        self.max_retries = max_retries
        self._validation_log = ValidationEventLogger(path=VALIDATION_LOG_PATH)

    async def step(self, bundle: PerceptionBundle) -> dict:
        conversation = self.reasoning._initial_messages(bundle)
        last_call: dict | None = None

        for attempt in range(self.max_retries):
            response = await self.reasoning.call(bundle, conversation)
            last_call = self.reasoning.parse_function_call(response)
            result = self.validation.validate(last_call, bundle)

            function_or_command = (last_call or {}).get("function") or "<no_call>"

            if result.valid:
                outcome = "success_first_try" if attempt == 0 else "corrected_after_retry"
                self._validation_log.log(
                    agent_id=self.drone_id,
                    layer="drone",
                    function_or_command=function_or_command,
                    attempt=attempt + 1,
                    valid=True,
                    rule_id=None,
                    outcome=outcome,
                    raw_call=last_call,
                )
                self.validation.record_success(last_call, bundle)
                self.memory.record_decision(last_call, result, attempt)
                self.action.execute(last_call, sender_position={
                    "lat": bundle.state.lat, "lon": bundle.state.lon, "alt": bundle.state.alt,
                }, raw_frame_jpeg=bundle.raw_frame_jpeg)
                return last_call

            self._validation_log.log(
                agent_id=self.drone_id,
                layer="drone",
                function_or_command=function_or_command,
                attempt=attempt + 1,
                valid=False,
                rule_id=result.failure_reason.value if result.failure_reason else None,
                outcome="in_progress",
                raw_call=last_call,
            )

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

        # Max retries exhausted — log a final failed_after_retries record then fall back.
        self._validation_log.log(
            agent_id=self.drone_id,
            layer="drone",
            function_or_command=(last_call or {}).get("function") or "<no_call>",
            attempt=self.max_retries,
            valid=False,
            rule_id=None,
            outcome="failed_after_retries",
            raw_call=last_call,
        )
        fallback = _safe_fallback()
        self.memory.record_decision(fallback, type("R", (), {"valid": True, "failure_reason": "max_retries_exhausted"})(), self.max_retries)
        self.action.execute(fallback, sender_position={
            "lat": bundle.state.lat, "lon": bundle.state.lon, "alt": bundle.state.alt,
        }, raw_frame_jpeg=bundle.raw_frame_jpeg)
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
