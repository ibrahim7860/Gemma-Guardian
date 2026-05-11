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


class BaseImageExtents(BaseModel):
    """Lat/lon bbox the static aerial image projects onto. Set together with
    `Scenario.base_image_path`; the Flutter map panel locks its bbox to these
    extents (LOCKED DESIGN DECISION D1, docs/plans/2026-05-08-thayyil-fixtures-swap.md).
    """
    model_config = ConfigDict(extra="forbid")
    lat_min: float = Field(ge=-90, le=90)
    lat_max: float = Field(ge=-90, le=90)
    lon_min: float = Field(ge=-180, le=180)
    lon_max: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _ordered_bounds(self) -> "BaseImageExtents":
        if self.lat_max <= self.lat_min:
            raise ValueError(
                f"base_image_extents.lat_min ({self.lat_min}) must be < lat_max ({self.lat_max})"
            )
        if self.lon_max <= self.lon_min:
            raise ValueError(
                f"base_image_extents.lon_min ({self.lon_min}) must be < lon_max ({self.lon_max})"
            )
        return self


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str = Field(min_length=1)
    origin: GpsPoint2D
    area_m: int = Field(gt=0)
    drones: List[Drone] = Field(min_length=1)
    frame_mappings: Dict[str, List[FrameMapping]] = Field(default_factory=dict)
    scripted_events: List[ScriptedEvent] = Field(default_factory=list)
    # Optional static aerial overlay. Both fields are populated together or
    # neither is. Validated by `_base_image_path_and_extents_paired`. The
    # actual asset existence is NOT checked here — Flutter's `errorBuilder`
    # handles missing assets at render time, and the byte-equality CI check
    # in `scripts/tests/test_flutter_asset_sync.py` catches drift between
    # the sim copy and the Flutter assets copy.
    base_image_path: Optional[str] = Field(default=None, min_length=1)
    base_image_extents: Optional[BaseImageExtents] = None

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

    @model_validator(mode="after")
    def _base_image_path_and_extents_paired(self) -> "Scenario":
        path_set = self.base_image_path is not None
        extents_set = self.base_image_extents is not None
        if path_set and not extents_set:
            raise ValueError(
                "base_image_path was set but base_image_extents was not; both go together "
                "(Flutter cannot project the aerial without a bbox)."
            )
        if extents_set and not path_set:
            raise ValueError(
                "base_image_extents was set but base_image_path was not; both go together "
                "(extents alone don't render anything)."
            )
        return self


# Ground-truth manifest models.

# Eval-field types shared across all detection models. The 3 eval fields
# (expected_finding_type / expected_severity / min_confidence) are optional at
# the Pydantic layer — older groundtruth manifests that predate the
# 2026-05-08 expansion still load. Presence on current manifests is enforced
# by sim/tests/test_groundtruth_schema.py.
#
# `expected_severity` is an integer 1-5 to match Contract 4 finding.severity
# (`shared/schemas/_common.json`). Adversarial-review fix: the original plan
# specified strings but those don't compare against the integer Contract 4
# field — Kaleel's GATE 3 perception eval would silently score 0%.
ExpectedFindingType = Literal["victim", "fire", "smoke", "damaged_structure", "blocked_route"]


class _EvalFieldsMixin(BaseModel):
    expected_finding_type: Optional[ExpectedFindingType] = None
    expected_severity: Optional[int] = Field(default=None, ge=1, le=5)
    min_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class Victim(_EvalFieldsMixin):
    model_config = ConfigDict(extra="forbid")
    id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    frame_file: str
    in_or_near: str


class Fire(_EvalFieldsMixin):
    model_config = ConfigDict(extra="forbid")
    id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    frame_file: str
    intensity: Literal["low", "medium", "high"]


class DamagedStructure(_EvalFieldsMixin):
    model_config = ConfigDict(extra="forbid")
    id: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    frame_file: str
    damage_level: Literal["minor_damage", "major_damage", "destroyed"]


class BlockedRoute(_EvalFieldsMixin):
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
    # Optional schema_version is the marker that this manifest was authored
    # post-2026-05-08-fixtures-swap (i.e., expects expected_finding_type /
    # expected_severity / min_confidence on every detection entry).
    schema_version: Optional[str] = None
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


_SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


def resolve_scenario_path(arg: str) -> Path:
    """Resolve a scenario_id or path to an absolute scenario YAML path.

    Accepts either an existing path (returned as-is) or a scenario_id that
    resolves to ``sim/scenarios/<id>.yaml``. Raises FileNotFoundError with
    the path it tried when neither form matches.

    Shared by ``sim/list_drones.py`` and ``agents/mesh_simulator/main.py`` so
    every scenario-aware tool has one resolution rule.
    """
    p = Path(arg)
    if p.exists():
        return p
    candidate = _SCENARIOS_DIR / f"{arg}.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(
        f"scenario not found: {arg!r} (also looked at {candidate})"
    )
