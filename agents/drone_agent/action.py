"""Action node — translates a validated function call into ROS 2 publishes.

ROS 2 publishing is stubbed via a Publisher protocol so the agent runs without rclpy in Day-1 standalone mode.
P1's launch system swaps in the real ROS 2 publisher.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Protocol


class Publisher(Protocol):
    def publish(self, topic: str, payload: dict) -> None: ...


class StdoutPublisher:
    def publish(self, topic: str, payload: dict) -> None:
        print(f"[publish] {topic}: {json.dumps(payload)}")


class ActionNode:
    def __init__(self, drone_id: str, publisher: Publisher | None = None):
        self.drone_id = drone_id
        self.publisher = publisher or StdoutPublisher()

    def execute(self, call: dict, sender_position: dict) -> None:
        name = call["function"]
        args = call.get("arguments") or {}
        method = getattr(self, f"_act_{name}")
        method(args, sender_position)

    def _act_report_finding(self, args: dict, sender_position: dict) -> None:
        finding_id = f"f_{self.drone_id}_{uuid.uuid4().hex[:8]}"
        ts = _now_iso()
        finding = {
            "finding_id": finding_id,
            "source_drone_id": self.drone_id,
            "timestamp": ts,
            "type": args["type"],
            "severity": args["severity"],
            "gps_lat": args["gps_lat"],
            "gps_lon": args["gps_lon"],
            "altitude": 0,
            "confidence": args["confidence"],
            "visual_description": args["visual_description"],
            "validated": True,
            "validation_retries": 0,
            "operator_status": "pending",
        }
        self.publisher.publish(f"/drones/{self.drone_id}/findings", finding)

        broadcast = {
            "broadcast_id": f"{self.drone_id}_b{uuid.uuid4().hex[:6]}",
            "sender_id": self.drone_id,
            "sender_position": sender_position,
            "timestamp": ts,
            "broadcast_type": "finding",
            "payload": {k: finding[k] for k in ("type", "severity", "gps_lat", "gps_lon", "confidence", "visual_description")},
        }
        self.publisher.publish(f"/swarm/broadcasts/{self.drone_id}", broadcast)

    def _act_mark_explored(self, args: dict, sender_position: dict) -> None:
        self.publisher.publish(f"/drones/{self.drone_id}/state_event", {
            "drone_id": self.drone_id,
            "timestamp": _now_iso(),
            "event": "mark_explored",
            "zone_id": args["zone_id"],
            "coverage_pct": args["coverage_pct"],
        })

    def _act_request_assist(self, args: dict, sender_position: dict) -> None:
        broadcast = {
            "broadcast_id": f"{self.drone_id}_b{uuid.uuid4().hex[:6]}",
            "sender_id": self.drone_id,
            "sender_position": sender_position,
            "timestamp": _now_iso(),
            "broadcast_type": "assist_request",
            "payload": args,
        }
        self.publisher.publish(f"/swarm/broadcasts/{self.drone_id}", broadcast)

    def _act_return_to_base(self, args: dict, sender_position: dict) -> None:
        self.publisher.publish(f"/drones/{self.drone_id}/cmd", {
            "drone_id": self.drone_id,
            "timestamp": _now_iso(),
            "command": "return_to_base",
            "reason": args["reason"],
        })

    def _act_continue_mission(self, args: dict, sender_position: dict) -> None:
        return


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
