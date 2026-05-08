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

    def test_rejects_scripted_event_drone_id_not_in_drones(self, tmp_path: Path):
        """A drone_failure event referencing a drone that isn't in drones[]
        is silently a no-op at runtime (waypoint_runner._fire skips unknown
        ids), but it's almost always an authoring typo. Fail at load time."""
        bad = yaml.safe_load(_VALID_YAML)
        bad["scripted_events"][0]["drone_id"] = "drone99"
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(bad))
        with pytest.raises(ValidationError, match="drone99"):
            load_scenario(p)

    def test_accepts_scripted_event_without_drone_id(self, tmp_path: Path):
        """zone_update / mission_complete / egs_link_* don't carry a drone_id;
        cross-validation must skip None to keep them legal."""
        ok = yaml.safe_load(_VALID_YAML)
        # remove drone_id from the drone_failure entry → still valid (drone_id
        # is Optional on ScriptedEvent), and shouldn't trigger the new check.
        ok["scripted_events"][0]["drone_id"] = None
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(ok))
        s = load_scenario(p)
        assert s.scripted_events[0].drone_id is None


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


# ---- base_image fields (Task 8 of fixtures-swap plan) -----------------------
# When `base_image_path` is set on a scenario, the Flutter map panel locks its
# bbox to `base_image_extents` (LOCKED DESIGN DECISION D1). The two fields go
# together — neither makes sense alone — so the loader enforces both-or-neither
# and rejects inverted bbox bounds. Existing scenarios without these fields
# still load (backward compat for single_drone_smoke + resilience_v1, which
# don't ship a static aerial today).

_BASE_IMAGE_BLOCK = """\
base_image_path: sim/fixtures/base_images/disaster_zone_v1_base.jpg
base_image_extents:
  lat_min: 33.9990
  lat_max: 34.0010
  lon_min: -118.5010
  lon_max: -118.4990
"""


class TestScenarioBaseImage:
    def test_loads_with_base_image_fields(self, tmp_path: Path):
        p = tmp_path / "scenario.yaml"
        p.write_text(_VALID_YAML + _BASE_IMAGE_BLOCK)
        s = load_scenario(p)
        assert s.base_image_path == "sim/fixtures/base_images/disaster_zone_v1_base.jpg"
        assert s.base_image_extents is not None
        assert s.base_image_extents.lat_min == 33.9990
        assert s.base_image_extents.lon_max == -118.4990

    def test_loads_without_base_image_fields(self, valid_yaml_path: Path):
        """Backward compat: scenarios without base_image_* still load.
        single_drone_smoke + resilience_v1 don't ship a static aerial."""
        s = load_scenario(valid_yaml_path)
        assert s.base_image_path is None
        assert s.base_image_extents is None

    def test_rejects_path_without_extents(self, tmp_path: Path):
        """Path-only is meaningless: Flutter can't project the image without
        a bbox. Catch the typo at load time, not as a silent grid fallback."""
        body = _VALID_YAML + "base_image_path: foo.jpg\n"
        p = tmp_path / "scenario.yaml"
        p.write_text(body)
        with pytest.raises(ValidationError, match="base_image_extents"):
            load_scenario(p)

    def test_rejects_extents_without_path(self, tmp_path: Path):
        """Extents-only is also meaningless: nothing to project."""
        body = _VALID_YAML + (
            "base_image_extents:\n"
            "  lat_min: 33.9990\n"
            "  lat_max: 34.0010\n"
            "  lon_min: -118.5010\n"
            "  lon_max: -118.4990\n"
        )
        p = tmp_path / "scenario.yaml"
        p.write_text(body)
        with pytest.raises(ValidationError, match="base_image_path"):
            load_scenario(p)

    def test_rejects_inverted_lat_bounds(self, tmp_path: Path):
        body = _VALID_YAML + (
            "base_image_path: foo.jpg\n"
            "base_image_extents:\n"
            "  lat_min: 34.0010\n"   # max < min
            "  lat_max: 33.9990\n"
            "  lon_min: -118.5010\n"
            "  lon_max: -118.4990\n"
        )
        p = tmp_path / "scenario.yaml"
        p.write_text(body)
        with pytest.raises(ValidationError, match="lat_min"):
            load_scenario(p)

    def test_rejects_inverted_lon_bounds(self, tmp_path: Path):
        body = _VALID_YAML + (
            "base_image_path: foo.jpg\n"
            "base_image_extents:\n"
            "  lat_min: 33.9990\n"
            "  lat_max: 34.0010\n"
            "  lon_min: -118.4990\n"  # max < min
            "  lon_max: -118.5010\n"
        )
        p = tmp_path / "scenario.yaml"
        p.write_text(body)
        with pytest.raises(ValidationError, match="lon_min"):
            load_scenario(p)

    def test_rejects_extra_unknown_top_level_key(self, tmp_path: Path):
        """Sanity: extra=forbid still bites for typos, even after we add
        the two new fields. Catches `base_image_pat` (missing 'h')."""
        body = _VALID_YAML + "base_image_pat: foo.jpg\n"
        p = tmp_path / "scenario.yaml"
        p.write_text(body)
        with pytest.raises(ValidationError):
            load_scenario(p)

    def test_loads_real_disaster_zone_v1(self):
        """Lockdown: the actual checked-in disaster_zone_v1.yaml carries
        the locked extents that match its groundtruth + the static aerial.
        Catches accidental drift from anyone editing the YAML."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        s = load_scenario(repo_root / "sim" / "scenarios" / "disaster_zone_v1.yaml")
        assert s.base_image_path == "sim/fixtures/base_images/disaster_zone_v1_base.jpg"
        assert s.base_image_extents is not None
        # Locked to disaster_zone_v1 groundtruth.json extents (see
        # sim/scenarios/disaster_zone_v1_groundtruth.json).
        assert s.base_image_extents.lat_min == 33.9990
        assert s.base_image_extents.lat_max == 34.0010
        assert s.base_image_extents.lon_min == -118.5010
        assert s.base_image_extents.lon_max == -118.4990
