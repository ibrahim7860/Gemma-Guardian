"""Day-1 standalone test (per docs/19): image + mock state → Gemma 4 → validated function call.

Usage:
    python -m agents.drone_agent.standalone_test path/to/image.jpg

Requires Ollama running locally with gemma-4:e2b pulled.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import cv2

from .main import DroneAgent
from .perception import DroneState


def _load_frame(path: str):
    img = cv2.imread(path)
    if img is None:
        raise SystemExit(f"could not read image: {path}")
    return img


def _mock_state() -> DroneState:
    return DroneState(
        drone_id="drone1",
        lat=34.0001,
        lon=-118.5001,
        alt=25.0,
        battery_pct=87.0,
        heading_deg=135.0,
        current_task="survey_zone_a",
        assigned_survey_points_remaining=12,
        zone_bounds={
            "lat_min": 33.9990,
            "lat_max": 34.0020,
            "lon_min": -118.5020,
            "lon_max": -118.4980,
        },
        next_waypoint={"id": "sp_005", "lat": 34.0010, "lon": -118.5000},
    )


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    img_path = sys.argv[1]
    if not Path(img_path).exists():
        raise SystemExit(f"file not found: {img_path}")

    frame = _load_frame(img_path)
    agent = DroneAgent(drone_id="drone1")
    bundle = agent.perception.build(frame, _mock_state(), peer_broadcasts=[], operator_commands=[])
    call = await agent.step(bundle)
    print("\nFinal call:")
    print(json.dumps(call, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
