"""Perception node — bundles camera frame, drone state, and peer broadcasts."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np


@dataclass
class DroneState:
    drone_id: str
    lat: float
    lon: float
    alt: float
    battery_pct: float
    heading_deg: float
    current_task: str
    assigned_survey_points_remaining: int
    zone_bounds: dict
    next_waypoint: Optional[dict] = None


@dataclass
class PerceptionBundle:
    frame_jpeg: bytes
    state: DroneState
    peer_broadcasts: list = field(default_factory=list)
    operator_commands: list = field(default_factory=list)
    corrective_context: list = field(default_factory=list)


class PerceptionNode:
    def __init__(self, downsample_size: int = 512):
        self.downsample_size = downsample_size

    def build(
        self,
        raw_frame: np.ndarray,
        state: DroneState,
        peer_broadcasts: list,
        operator_commands: list,
    ) -> PerceptionBundle:
        resized = cv2.resize(raw_frame, (self.downsample_size, self.downsample_size))
        ok, buf = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise RuntimeError("frame encode failed")
        return PerceptionBundle(
            frame_jpeg=buf.tobytes(),
            state=state,
            peer_broadcasts=peer_broadcasts,
            operator_commands=operator_commands,
        )
