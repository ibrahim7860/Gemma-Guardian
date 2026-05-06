"""Action node — translates a validated function call into Redis pub/sub publishes.

Publishing is stubbed via a Publisher protocol so the agent runs without redis-py in Day-1 standalone mode.
The real Redis publisher (RedisPublisher in redis_io.py) gets injected at boot.
Channel names follow Contract 9 in docs/20-integration-contracts.md (dot-notation, e.g. drones.drone1.findings).

Outbound finding and peer_broadcast payloads are schema-validated against
shared/schemas/finding.json and shared/schemas/peer_broadcast.json before
publishing. Validation failures raise ContractError — the loop logs the
exception and falls back to continue_mission rather than emitting a malformed
message that would break downstream consumers.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Protocol

from shared.contracts import validate_or_raise
from shared.contracts.logging import now_iso_ms
from shared.contracts.topics import (
    per_drone_cmd_channel,
    per_drone_findings_channel,
    swarm_broadcast_channel,
)

from shared.contracts.logging import default_log_dir

FRAMES_DIR = default_log_dir() / "frames"


class Publisher(Protocol):
    def publish(self, channel: str, payload: dict) -> None: ...


class StdoutPublisher:
    def publish(self, channel: str, payload: dict) -> None:
        print(f"[publish] {channel}: {json.dumps(payload)}")


class ActionNode:
    def __init__(self, drone_id: str, publisher: Publisher | None = None):
        self.drone_id = drone_id
        self.publisher = publisher or StdoutPublisher()
        self._finding_counter = 0

    def execute(self, call: dict, sender_position: dict, raw_frame_jpeg: bytes | None = None) -> None:
        name = call["function"]
        args = call.get("arguments") or {}
        method = getattr(self, f"_act_{name}")
        method(args, sender_position, raw_frame_jpeg)

    def _act_report_finding(self, args: dict, sender_position: dict, raw_frame_jpeg: Optional[bytes]) -> None:
        self._finding_counter += 1
        finding_id = f"f_{self.drone_id}_{self._finding_counter}"
        ts = now_iso_ms()

        image_path = self._persist_frame(finding_id, raw_frame_jpeg) if raw_frame_jpeg else "<no_capture>"

        finding = {
            "finding_id": finding_id,
            "source_drone_id": self.drone_id,
            "timestamp": ts,
            "type": args["type"],
            "severity": int(args["severity"]),
            "gps_lat": float(args["gps_lat"]),
            "gps_lon": float(args["gps_lon"]),
            "altitude": float(sender_position.get("alt", 0)),
            "confidence": float(args["confidence"]),
            "visual_description": args["visual_description"],
            "image_path": image_path,
            "validated": True,
            "validation_retries": 0,
            "operator_status": "pending",
        }
        validate_or_raise("finding", finding)
        self.publisher.publish(per_drone_findings_channel(self.drone_id), finding)

        broadcast = {
            "broadcast_id": f"{self.drone_id}_b{uuid.uuid4().hex[:6]}",
            "sender_id": self.drone_id,
            "sender_position": {
                "lat": float(sender_position["lat"]),
                "lon": float(sender_position["lon"]),
                "alt": float(sender_position["alt"]),
            },
            "timestamp": ts,
            "broadcast_type": "finding",
            "payload": {
                "type": finding["type"],
                "severity": finding["severity"],
                "gps_lat": finding["gps_lat"],
                "gps_lon": finding["gps_lon"],
                "confidence": finding["confidence"],
                "visual_description": finding["visual_description"],
            },
        }
        validate_or_raise("peer_broadcast", broadcast)
        self.publisher.publish(swarm_broadcast_channel(self.drone_id), broadcast)

    def _act_mark_explored(self, args: dict, sender_position: dict, raw_frame_jpeg: Optional[bytes]) -> None:
        return

    def _act_request_assist(self, args: dict, sender_position: dict, raw_frame_jpeg: Optional[bytes]) -> None:
        broadcast = {
            "broadcast_id": f"{self.drone_id}_b{uuid.uuid4().hex[:6]}",
            "sender_id": self.drone_id,
            "sender_position": {
                "lat": float(sender_position["lat"]),
                "lon": float(sender_position["lon"]),
                "alt": float(sender_position["alt"]),
            },
            "timestamp": now_iso_ms(),
            "broadcast_type": "assist_request",
            "payload": {
                "reason": args["reason"],
                "urgency": args["urgency"],
                **({"related_finding_id": args["related_finding_id"]}
                   if "related_finding_id" in args else {}),
            },
        }
        validate_or_raise("peer_broadcast", broadcast)
        self.publisher.publish(swarm_broadcast_channel(self.drone_id), broadcast)

    def _act_return_to_base(self, args: dict, sender_position: dict, raw_frame_jpeg: Optional[bytes]) -> None:
        self.publisher.publish(per_drone_cmd_channel(self.drone_id), {
            "drone_id": self.drone_id,
            "timestamp": now_iso_ms(),
            "command": "return_to_base",
            "reason": args["reason"],
        })

    def _act_continue_mission(self, args: dict, sender_position: dict, raw_frame_jpeg: Optional[bytes]) -> None:
        return

    def _persist_frame(self, finding_id: str, raw_jpeg: bytes) -> str:
        FRAMES_DIR.mkdir(parents=True, exist_ok=True)
        out = FRAMES_DIR / f"{finding_id}.jpg"
        out.write_bytes(raw_jpeg)
        return str(out)
