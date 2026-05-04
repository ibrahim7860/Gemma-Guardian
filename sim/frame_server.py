"""Pre-recorded JPEG frame publisher.

For each drone in the scenario, looks up the frame_file appropriate for the
current tick index from ``scenario.frame_mappings[drone_id]`` and publishes
the raw JPEG bytes on Redis channel ``drones.<id>.camera`` at 1 Hz.

JPEGs are loaded into memory at startup so the publish loop never touches
disk. A missing referenced file fails fast with FileNotFoundError. Drones
with no frame_mappings entry are silently skipped (the runner still publishes
their state on the state channel — they're just not equipped with a camera in
this scenario, which is a valid configuration).

Tick alignment with waypoint_runner: both processes use the same time origin
in scripted demos. The frame server's tick index advances at 1 Hz; the
waypoint runner publishes at 2 Hz. They interleave naturally because both
read the scenario YAML's frame_mappings tick_range definitions in seconds.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

# Add project root to sys.path for direct-script invocation.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import redis

from shared.contracts.config import CONFIG
from shared.contracts.topics import per_drone_camera_channel
from sim.scenario import FrameMapping, Scenario, load_scenario


@dataclass(frozen=True)
class _LoadedMapping:
    tick_start: int
    tick_end: int
    frame_bytes: bytes


class FrameServer:
    """Pre-loads JPEG frames and publishes them per tick on the camera channel."""

    def __init__(
        self,
        scenario: Scenario,
        redis_client: redis.Redis,
        *,
        frames_dir: Path,
    ) -> None:
        self.scenario = scenario
        self.redis = redis_client
        self.frames_dir = Path(frames_dir)
        self._mappings: Dict[str, List[_LoadedMapping]] = {}
        for drone_id, mappings in scenario.frame_mappings.items():
            loaded: List[_LoadedMapping] = []
            for m in mappings:
                path = self.frames_dir / m.frame_file
                if not path.exists():
                    raise FileNotFoundError(
                        f"frame_server: scenario {scenario.scenario_id!r} references missing frame "
                        f"{m.frame_file!r} for {drone_id} (looked at {path})"
                    )
                loaded.append(_LoadedMapping(m.tick_range[0], m.tick_range[1], path.read_bytes()))
            # Sort by start tick for deterministic lookup.
            loaded.sort(key=lambda x: x.tick_start)
            self._mappings[drone_id] = loaded

    def _frame_for_tick(self, drone_id: str, tick_index: int) -> Optional[bytes]:
        loaded = self._mappings.get(drone_id)
        if not loaded:
            return None
        # Find a mapping whose range contains tick_index.
        for m in loaded:
            if m.tick_start <= tick_index <= m.tick_end:
                return m.frame_bytes
        # Past the end → repeat the final mapping's frame.
        return loaded[-1].frame_bytes

    def tick(self, *, tick_index: int) -> None:
        """Publish each drone's frame for the given tick index. Idempotent."""
        for drone_id in self._mappings.keys():
            data = self._frame_for_tick(drone_id, tick_index)
            if data is None:
                continue
            self.redis.publish(per_drone_camera_channel(drone_id), data)


def _parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sim frame server — publishes drones.<id>.camera at 1 Hz.")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--redis-url", default=CONFIG.transport.redis_url)
    parser.add_argument("--frame-hz", type=float, default=1.0)
    parser.add_argument(
        "--frames-dir",
        default=str(_PROJECT_ROOT / "sim" / "fixtures" / "frames"),
        help="Directory containing JPEGs referenced by scenario.frame_mappings",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _resolve_scenario_path(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    candidate = _PROJECT_ROOT / "sim" / "scenarios" / f"{arg}.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"scenario not found: {arg!r} (also looked at {candidate})")


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _parse_args(argv)
    scenario = load_scenario(_resolve_scenario_path(args.scenario))
    redis_client = redis.Redis.from_url(args.redis_url)
    server = FrameServer(scenario, redis_client, frames_dir=Path(args.frames_dir))

    period = 1.0 / args.frame_hz
    print(
        f"[frame_server] scenario={scenario.scenario_id} "
        f"drones_with_frames={list(server._mappings.keys())} "
        f"frame_hz={args.frame_hz} redis={args.redis_url}",
        flush=True,
    )
    start = time.monotonic()
    try:
        while True:
            elapsed = time.monotonic() - start
            tick_index = int(elapsed)
            server.tick(tick_index=tick_index)
            next_boundary = start + (math.floor(elapsed / period) + 1) * period
            time.sleep(max(0.0, next_boundary - time.monotonic()))
    except KeyboardInterrupt:
        print("[frame_server] stopped via SIGINT", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
