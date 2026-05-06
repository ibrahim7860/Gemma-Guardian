"""DroneRuntime — the asyncio orchestrator for the per-drone agent.

Wires three async Redis subscribers (camera, state, peers) plus a sync Redis
publisher into the existing DroneAgent. Two periodic tasks drive activity:

  - `_step_loop`: builds a PerceptionBundle from the latest snapshots and
    calls agent.step() at agent_step_period_s.
  - `_state_republish_loop`: every agent_state_publish_period_s, reads the
    latest sim-shaped payload from `state.latest_raw_sim()`, overwrites the
    agent-owned fields (last_action, last_action_timestamp,
    validation_failures_total, findings_count, current_task), and
    republishes on drones.<id>.state. The republish is gated on
    `last_action != "none"` so the agent never publishes a noisy duplicate
    of the sim's state before doing any agent-owned work.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import redis as _redis_sync
import redis.asyncio as _redis_async

from agents.drone_agent.action import ActionNode
from agents.drone_agent.main import DroneAgent
from agents.drone_agent.perception import PerceptionBundle
from agents.drone_agent.redis_io import (
    CameraSubscriber,
    PeerSubscriber,
    RedisPublisher,
    StateSubscriber,
)
from shared.contracts import validate as schema_validate
from shared.contracts.logging import now_iso_ms
from shared.contracts.topics import per_drone_state_channel
from sim.scenario import Scenario

logger = logging.getLogger(__name__)


_ACTION_TO_LAST_ACTION = {
    "report_finding": "report_finding",
    "mark_explored": "mark_explored",
    "request_assist": "request_assist",
    "return_to_base": "return_to_base",
    "continue_mission": "continue_mission",
}


class DroneRuntime:
    def __init__(
        self,
        *,
        drone_id: str,
        scenario: Scenario,
        zone_bounds: dict,
        sync_client: _redis_sync.Redis,
        async_client: _redis_async.Redis,
        ollama_endpoint: str = "http://localhost:11434",
        model: str = "gemma4:e2b",
        max_retries: int = 3,
        send_image: bool = True,
        agent_step_period_s: float = 1.0,
        agent_state_publish_period_s: float = 0.5,
    ):
        self.drone_id = drone_id
        self.agent = DroneAgent(
            drone_id=drone_id,
            ollama_endpoint=ollama_endpoint,
            model=model,
            max_retries=max_retries,
            send_image=send_image,
        )
        self.agent.action = ActionNode(
            drone_id=drone_id, publisher=RedisPublisher(sync_client),
        )
        self.camera = CameraSubscriber(async_client, drone_id=drone_id)
        self.state = StateSubscriber(
            async_client, drone_id=drone_id,
            zone_bounds=zone_bounds, scenario=scenario,
        )
        self.peers = PeerSubscriber(async_client, drone_id=drone_id, max_size=10)
        self._sync_client = sync_client
        self._step_period_s = agent_step_period_s
        self._republish_period_s = agent_state_publish_period_s
        self._last_action: str = "none"
        self._last_action_timestamp: Optional[str] = None
        # Counter, not a list-walk (eng-review issue 7). Bumped in
        # _observe_step_result whenever the most recent decision was
        # rejected by the validator.
        self._validation_failures_total: int = 0
        self._findings_count: int = 0
        self._stop = asyncio.Event()

    async def run(self) -> None:
        camera_task = asyncio.create_task(self.camera.run(), name=f"{self.drone_id}.camera")
        state_task = asyncio.create_task(self.state.run(), name=f"{self.drone_id}.state")
        peers_task = asyncio.create_task(self.peers.run(), name=f"{self.drone_id}.peers")
        loop_task = asyncio.create_task(self._step_loop(), name=f"{self.drone_id}.loop")
        republish_task = asyncio.create_task(self._state_republish_loop(), name=f"{self.drone_id}.republish")
        try:
            await self._stop.wait()
        finally:
            await self.camera.stop()
            await self.state.stop()
            await self.peers.stop()
            for t in (camera_task, state_task, peers_task, loop_task, republish_task):
                t.cancel()
            await asyncio.gather(
                camera_task, state_task, peers_task, loop_task, republish_task,
                return_exceptions=True,
            )

    async def stop(self) -> None:
        self._stop.set()

    async def _step_loop(self) -> None:
        while not self._stop.is_set():
            try:
                bundle = self._build_bundle()
                if bundle is not None:
                    call = await self.agent.step(bundle)
                    self._observe_step_result(call)
            except Exception:
                logger.exception("agent step failed")
            await asyncio.sleep(self._step_period_s)

    def _observe_step_result(self, call: dict | None) -> None:
        if not call:
            return
        name = call.get("function")
        if name in _ACTION_TO_LAST_ACTION:
            self._last_action = _ACTION_TO_LAST_ACTION[name]
            self._last_action_timestamp = now_iso_ms()
        if name == "report_finding":
            self._findings_count += 1
        # Counter, not a re-scan (eng-review issue 7). The most recent
        # decision is the only one that just changed.
        if self.agent.memory.decisions:
            last = self.agent.memory.decisions[-1]
            if last.get("valid") is False:
                self._validation_failures_total += 1

    async def _state_republish_loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(self._republish_period_s)
            # Skip until the agent has actually done something — prevents a
            # noisy duplicate of the sim's state and keeps StateSubscriber's
            # raw-cache filter (last_action != "none") meaningful.
            if self._last_action == "none":
                continue
            base = self.state.latest_raw_sim()
            if base is None:
                continue
            merged = dict(base)
            merged["timestamp"] = now_iso_ms()
            merged["last_action"] = self._last_action
            merged["last_action_timestamp"] = self._last_action_timestamp
            merged["validation_failures_total"] = self._validation_failures_total
            merged["findings_count"] = self._findings_count
            merged["current_task"] = base.get("current_task") or "survey"
            outcome = schema_validate("drone_state", merged)
            if not outcome.valid:
                logger.warning("agent-state republish skipped (schema invalid): %s",
                               outcome.errors[0].message if outcome.errors else "?")
                continue
            self._sync_client.publish(per_drone_state_channel(self.drone_id), json.dumps(merged))

    def _build_bundle(self) -> Optional[PerceptionBundle]:
        cam = self.camera.latest()
        state = self.state.latest()
        if cam is None or state is None:
            return None
        frame_np, raw_jpeg = cam
        bundle = self.agent.perception.build(
            frame_np, state, peer_broadcasts=self.peers.recent(), operator_commands=[],
        )
        bundle.raw_frame_jpeg = raw_jpeg
        return bundle
