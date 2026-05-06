"""DroneRuntime — the asyncio orchestrator for the per-drone agent.

Wires three async Redis subscribers (camera, state, peers) plus a sync Redis
publisher into the existing DroneAgent. The agent step loop runs at a
configurable cadence; on each step it builds a PerceptionBundle from the
latest snapshots and calls agent.step().

State republish (the merge-back-onto-drones.<id>.state handshake from
Contract 2) is added in Task 11.
"""
from __future__ import annotations

import asyncio
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
from sim.scenario import Scenario

logger = logging.getLogger(__name__)


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
    ):
        self.drone_id = drone_id
        self.agent = DroneAgent(
            drone_id=drone_id,
            ollama_endpoint=ollama_endpoint,
            model=model,
            max_retries=max_retries,
            send_image=send_image,
        )
        # Replace the default StdoutPublisher with the real Redis one.
        self.agent.action = ActionNode(
            drone_id=drone_id, publisher=RedisPublisher(sync_client),
        )
        self.camera = CameraSubscriber(async_client, drone_id=drone_id)
        self.state = StateSubscriber(
            async_client, drone_id=drone_id,
            zone_bounds=zone_bounds, scenario=scenario,
        )
        self.peers = PeerSubscriber(async_client, drone_id=drone_id, max_size=10)
        self._step_period_s = agent_step_period_s
        self._stop = asyncio.Event()

    async def run(self) -> None:
        camera_task = asyncio.create_task(self.camera.run(), name=f"{self.drone_id}.camera")
        state_task = asyncio.create_task(self.state.run(), name=f"{self.drone_id}.state")
        peers_task = asyncio.create_task(self.peers.run(), name=f"{self.drone_id}.peers")
        loop_task = asyncio.create_task(self._step_loop(), name=f"{self.drone_id}.loop")
        try:
            await self._stop.wait()
        finally:
            await self.camera.stop()
            await self.state.stop()
            await self.peers.stop()
            for t in (camera_task, state_task, peers_task, loop_task):
                t.cancel()
            await asyncio.gather(*(camera_task, state_task, peers_task, loop_task), return_exceptions=True)

    async def stop(self) -> None:
        self._stop.set()

    async def _step_loop(self) -> None:
        while not self._stop.is_set():
            try:
                bundle = self._build_bundle()
                if bundle is not None:
                    await self.agent.step(bundle)
            except Exception:
                logger.exception("agent step failed")
            await asyncio.sleep(self._step_period_s)

    def _build_bundle(self) -> Optional[PerceptionBundle]:
        cam = self.camera.latest()
        state = self.state.latest()
        if cam is None or state is None:
            return None
        frame_np, raw_jpeg = cam
        bundle = self.agent.perception.build(
            frame_np, state, peer_broadcasts=self.peers.recent(), operator_commands=[],
        )
        # PerceptionNode no longer encodes raw_frame_jpeg (eng-review issue 6);
        # supply the wire bytes directly so action.py persists them as image_path.
        bundle.raw_frame_jpeg = raw_jpeg
        return bundle
