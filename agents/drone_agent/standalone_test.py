"""Day-1 standalone test (per docs/19): image + mock state → Gemma 4 → validated function call.

Usage:
    python -m agents.drone_agent.standalone_test path/to/image.jpg [--model TAG]

Requires Ollama running locally with the chosen model pulled. Default target
is gemma4:e2b (production). On a memory-tight machine, pass --model gemma3:4b
as a multimodal stand-in for wiring validation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
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
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", type=Path)
    ap.add_argument("--model", default="gemma4:e2b", help="Ollama model tag (default: gemma4:e2b).")
    ap.add_argument("--endpoint", default="http://localhost:11434")
    ap.add_argument("--text-only", action="store_true", help="Skip the image (validate tools wiring against text-only models).")
    ap.add_argument("--cpu-only", action="store_true", help="Force CPU inference via num_gpu=0 (workaround for Metal shader bugs on macOS).")
    args = ap.parse_args()

    if not args.image.exists():
        raise SystemExit(f"file not found: {args.image}")

    frame = _load_frame(str(args.image))
    extra = {"num_gpu": 0} if args.cpu_only else {}
    agent = DroneAgent(drone_id="drone1", ollama_endpoint=args.endpoint, model=args.model, send_image=not args.text_only, extra_options=extra)
    bundle = agent.perception.build(frame, _mock_state(), peer_broadcasts=[], operator_commands=[])
    call = await agent.step(bundle)
    print("\nFinal call:")
    print(json.dumps(call, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
