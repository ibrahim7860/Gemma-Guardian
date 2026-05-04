"""Scenario YAML + ground-truth JSON Pydantic models and loaders.

Authoritative format: docs/14-disaster-scene-design.md, lines 30–157.
Drone-id pattern reuses the regex baked into shared/schemas/_common.json
(``^drone\\d+$``) so a scenario file that round-trips through here is
guaranteed contract-compatible with downstream agents.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DRONE_ID_PATTERN = r"^drone\d+$"

ScriptedEventType = Literal[
    "drone_failure",
    "zone_update",
    "fire_spread",
    "mission_complete",
    "egs_link_drop",
    "egs_link_restore",
]


class GpsPoint2D(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class GpsPoint3D(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    alt: float = Field(ge=0)


class Waypoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    alt: float = Field(ge=0)


class Drone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    drone_id: str = Field(pattern=DRONE_ID_PATTERN)
    home: GpsPoint3D
    waypoints: List[Waypoint] = Field(min_length=1)
    speed_mps: float = Field(gt=0)


class FrameMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tick_range: Tuple[int, int]
    frame_file: str = Field(min_length=1)

    @field_validator("tick_range")
    @classmethod
    def _ordered(cls, v: Tuple[int, int]) -> Tuple[int, int]:
        if v[0] < 0 or v[1] < v[0]:
            raise ValueError(f"tick_range must be (start>=0, end>=start); got {v}")
        return v


class ScriptedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    t: int = Field(ge=0)
    type: ScriptedEventType
    drone_id: Optional[str] = Field(default=None, pattern=DRONE_ID_PATTERN)
    detail: Optional[str] = None


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(min_length=1)
    origin: GpsPoint2D
    area_m: int = Field(gt=0)
    drones: List[Drone] = Field(min_length=1)
    frame_mappings: Dict[str, List[FrameMapping]] = Field(default_factory=dict)
    scripted_events: List[ScriptedEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_drone_ids_unique(self) -> "Scenario":
        ids = [d.drone_id for d in self.drones]
        if len(set(ids)) != len(ids):
            dupes = [i for i in ids if ids.count(i) > 1]
            raise ValueError(f"duplicate drone_id(s) in scenario: {sorted(set(dupes))}")
        return self

    @model_validator(mode="after")
    def _frame_mappings_reference_known_drones(self) -> "Scenario":
        known = {d.drone_id for d in self.drones}
        unknown = set(self.frame_mappings.keys()) - known
        if unknown:
            raise ValueError(f"frame_mappings references unknown drone_id(s): {sorted(unknown)}")
        return self

    @model_validator(mode="after")
    def _scripted_events_reference_known_drones(self) -> "Scenario":
        known = {d.drone_id for d in self.drones}
        unknown = sorted(
            {e.drone_id for e in self.scripted_events if e.drone_id is not None} - known
        )
        if unknown:
            raise ValueError(
                f"scripted_events references unknown drone_id(s): {unknown}; "
                f"known drones: {sorted(known)}"
            )
        return self


# Ground-truth manifest models.

class Victim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    frame_file: str
    in_or_near: str


class Fire(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    frame_file: str
    intensity: Literal["low", "medium", "high"]


class DamagedStructure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    frame_file: str
    damage_level: Literal["minor_damage", "major_damage", "destroyed"]


class BlockedRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    frame_file: str
    blockage_type: Literal["debris", "fire", "flood", "vehicle"]


class GroundTruthExtents(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float


class GroundTruthScriptedEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    t: int = Field(ge=0)
    type: str


class GroundTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    extents: GroundTruthExtents
    victims: List[Victim] = Field(default_factory=list)
    fires: List[Fire] = Field(default_factory=list)
    damaged_structures: List[DamagedStructure] = Field(default_factory=list)
    blocked_routes: List[BlockedRoute] = Field(default_factory=list)
    scripted_events: List[GroundTruthScriptedEvent] = Field(default_factory=list)


def load_scenario(path: Path) -> Scenario:
    raw = yaml.safe_load(Path(path).read_text())
    return Scenario.model_validate(raw)


def load_groundtruth(path: Path) -> GroundTruth:
    raw = json.loads(Path(path).read_text())
    return GroundTruth.model_validate(raw)
