"""Tests for sim/scenario.py — Pydantic ScenarioModel + GroundTruth loader.

Covers schema validation against the format documented in
docs/14-disaster-scene-design.md (lines 30–157), including failure modes
that would otherwise corrupt downstream simulation runs.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from sim.scenario import (
    GroundTruth,
    Scenario,
    load_groundtruth,
    load_scenario,
)


_VALID_YAML = """\
scenario_id: test_zone
origin: {lat: 34.0000, lon: -118.5000}
area_m: 200
drones:
  - drone_id: drone1
    home: {lat: 34.0001, lon: -118.5001, alt: 0}
    waypoints:
      - {id: sp_001, lat: 34.0002, lon: -118.5002, alt: 25}
      - {id: sp_002, lat: 34.0004, lon: -118.5002, alt: 25}
    speed_mps: 5
  - drone_id: drone2
    home: {lat: 34.0001, lon: -118.4990, alt: 0}
    waypoints:
      - {id: sp_010, lat: 34.0002, lon: -118.4991, alt: 25}
    speed_mps: 5
frame_mappings:
  drone1:
    - {tick_range: [0, 30], frame_file: a.jpg}
    - {tick_range: [31, 60], frame_file: b.jpg}
  drone2:
    - {tick_range: [0, 60], frame_file: c.jpg}
scripted_events:
  - {t: 45, type: drone_failure, drone_id: drone1, detail: battery_depleted}
  - {t: 60, type: zone_update, detail: fire_spread}
"""


@pytest.fixture
def valid_yaml_path(tmp_path: Path) -> Path:
    p = tmp_path / "scenario.yaml"
    p.write_text(_VALID_YAML)
    return p


class TestLoadScenarioHappyPath:
    def test_loads_valid_yaml(self, valid_yaml_path: Path):
        s = load_scenario(valid_yaml_path)
        assert isinstance(s, Scenario)
        assert s.scenario_id == "test_zone"
        assert s.area_m == 200
        assert len(s.drones) == 2
        assert s.drones[0].drone_id == "drone1"
        assert s.drones[0].speed_mps == 5
        assert len(s.drones[0].waypoints) == 2
        assert s.drones[0].waypoints[0].id == "sp_001"

    def test_frame_mappings_keyed_by_drone(self, valid_yaml_path: Path):
        s = load_scenario(valid_yaml_path)
        assert set(s.frame_mappings.keys()) == {"drone1", "drone2"}
        assert s.frame_mappings["drone1"][0].tick_range == (0, 30)
        assert s.frame_mappings["drone1"][0].frame_file == "a.jpg"

    def test_scripted_events_parsed(self, valid_yaml_path: Path):
        s = load_scenario(valid_yaml_path)
        assert len(s.scripted_events) == 2
        assert s.scripted_events[0].t == 45
        assert s.scripted_events[0].type == "drone_failure"
        assert s.scripted_events[0].drone_id == "drone1"


class TestLoadScenarioRejections:
    def test_rejects_missing_scenario_id(self, tmp_path: Path):
        bad = yaml.safe_load(_VALID_YAML)
        del bad["scenario_id"]
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(bad))
        with pytest.raises(ValidationError):
            load_scenario(p)

    def test_rejects_drone_id_not_matching_pattern(self, tmp_path: Path):
        bad = yaml.safe_load(_VALID_YAML)
        bad["drones"][0]["drone_id"] = "DRONE_X"
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(bad))
        with pytest.raises(ValidationError):
            load_scenario(p)

    def test_rejects_duplicate_drone_ids(self, tmp_path: Path):
        bad = yaml.safe_load(_VALID_YAML)
        bad["drones"][1]["drone_id"] = "drone1"
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(bad))
        with pytest.raises(ValidationError):
            load_scenario(p)

    def test_rejects_lat_out_of_range(self, tmp_path: Path):
        bad = yaml.safe_load(_VALID_YAML)
        bad["drones"][0]["home"]["lat"] = 95.0
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(bad))
        with pytest.raises(ValidationError):
            load_scenario(p)

    def test_rejects_negative_speed(self, tmp_path: Path):
        bad = yaml.safe_load(_VALID_YAML)
        bad["drones"][0]["speed_mps"] = -1
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(bad))
        with pytest.raises(ValidationError):
            load_scenario(p)

    def test_rejects_inverted_tick_range(self, tmp_path: Path):
        bad = yaml.safe_load(_VALID_YAML)
        bad["frame_mappings"]["drone1"][0]["tick_range"] = [30, 0]
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(bad))
        with pytest.raises(ValidationError):
            load_scenario(p)

    def test_rejects_unknown_scripted_event_type(self, tmp_path: Path):
        bad = yaml.safe_load(_VALID_YAML)
        bad["scripted_events"][0]["type"] = "nuclear_strike"
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(bad))
        with pytest.raises(ValidationError):
            load_scenario(p)


_VALID_GROUNDTRUTH = textwrap.dedent("""
{
  "scenario_id": "test_zone",
  "extents": {"lat_min": 33.999, "lat_max": 34.001, "lon_min": -118.501, "lon_max": -118.499},
  "victims": [
    {"id": "v01", "lat": 34.0002, "lon": -118.5002, "frame_file": "a.jpg", "in_or_near": "block_a"}
  ],
  "fires": [
    {"id": "f01", "lat": 34.0006, "lon": -118.5003, "frame_file": "fire.jpg", "intensity": "medium"}
  ],
  "damaged_structures": [
    {"id": "ds_a2", "lat": 34.0002, "lon": -118.5002, "frame_file": "b.jpg", "damage_level": "major_damage"}
  ],
  "blocked_routes": [
    {"id": "br01", "lat": 34.0003, "lon": -118.5001, "frame_file": "a.jpg", "blockage_type": "debris"}
  ],
  "scripted_events": [
    {"t": 45, "type": "drone_failure", "drone_id": "drone1"}
  ]
}
""").strip()


class TestLoadGroundTruth:
    def test_loads_valid_json(self, tmp_path: Path):
        p = tmp_path / "gt.json"
        p.write_text(_VALID_GROUNDTRUTH)
        gt = load_groundtruth(p)
        assert isinstance(gt, GroundTruth)
        assert gt.scenario_id == "test_zone"
        assert gt.victims[0].id == "v01"
        assert gt.fires[0].intensity == "medium"
        assert gt.damaged_structures[0].damage_level == "major_damage"

    def test_rejects_invalid_intensity(self, tmp_path: Path):
        bad = json.loads(_VALID_GROUNDTRUTH)
        bad["fires"][0]["intensity"] = "apocalyptic"
        p = tmp_path / "gt.json"
        p.write_text(json.dumps(bad))
        with pytest.raises(ValidationError):
            load_groundtruth(p)

    def test_rejects_invalid_damage_level(self, tmp_path: Path):
        bad = json.loads(_VALID_GROUNDTRUTH)
        bad["damaged_structures"][0]["damage_level"] = "scratched"
        p = tmp_path / "gt.json"
        p.write_text(json.dumps(bad))
        with pytest.raises(ValidationError):
            load_groundtruth(p)
