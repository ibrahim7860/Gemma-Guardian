"""Tests for sim/frame_server.py.

The frame server publishes raw JPEG bytes (not JSON) on
``drones.<id>.camera`` at 1 Hz, looking up the right frame for each
drone+tick from the scenario's frame_mappings.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from shared.contracts.topics import per_drone_camera_channel
from sim.frame_server import FrameServer
from sim.scenario import load_scenario

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FRAMES_DIR = REPO_ROOT / "sim" / "fixtures" / "frames"


def _subscribe(fake_redis, channel: str):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe(channel)
    pubsub.get_message(timeout=0.1)
    return pubsub


def _drain_bytes(pubsub, *, count: int):
    out = []
    while len(out) < count:
        msg = pubsub.get_message(timeout=0.1)
        if msg is None:
            break
        if msg["type"] != "message":
            continue
        out.append(msg["data"])
    return out


@pytest.fixture
def smoke_scenario():
    return load_scenario(REPO_ROOT / "sim" / "scenarios" / "single_drone_smoke.yaml")


class TestFrameServerBasics:
    def test_publishes_jpeg_bytes_on_camera_channel(self, smoke_scenario, fake_redis):
        server = FrameServer(smoke_scenario, fake_redis, frames_dir=FRAMES_DIR)
        ps = _subscribe(fake_redis, per_drone_camera_channel("drone1"))
        server.tick(tick_index=0)
        msgs = _drain_bytes(ps, count=1)
        assert len(msgs) == 1
        # Raw JPEG magic bytes (0xFFD8...).
        assert isinstance(msgs[0], bytes)
        assert msgs[0][:2] == b"\xff\xd8"

    def test_payload_is_not_json(self, smoke_scenario, fake_redis):
        server = FrameServer(smoke_scenario, fake_redis, frames_dir=FRAMES_DIR)
        ps = _subscribe(fake_redis, per_drone_camera_channel("drone1"))
        server.tick(tick_index=0)
        msgs = _drain_bytes(ps, count=1)
        # JSON would start with `{` — JPEG magic must not.
        assert not msgs[0].startswith(b"{")

    def test_serves_correct_frame_per_tick_range(self, smoke_scenario, fake_redis):
        # smoke YAML mappings: tick 0–30 → intact, 31–60 → victim
        server = FrameServer(smoke_scenario, fake_redis, frames_dir=FRAMES_DIR)
        ps = _subscribe(fake_redis, per_drone_camera_channel("drone1"))
        server.tick(tick_index=0)
        server.tick(tick_index=31)
        msgs = _drain_bytes(ps, count=2)
        assert len(msgs) == 2
        intact = (FRAMES_DIR / "placeholder_intact_01.jpg").read_bytes()
        victim = (FRAMES_DIR / "placeholder_victim_01.jpg").read_bytes()
        assert msgs[0] == intact
        assert msgs[1] == victim

    def test_tick_beyond_last_range_repeats_final_frame(self, smoke_scenario, fake_redis):
        server = FrameServer(smoke_scenario, fake_redis, frames_dir=FRAMES_DIR)
        ps = _subscribe(fake_redis, per_drone_camera_channel("drone1"))
        # last range ends at tick 60; tick 999 must still publish *something*
        server.tick(tick_index=999)
        msgs = _drain_bytes(ps, count=1)
        assert len(msgs) == 1
        victim = (FRAMES_DIR / "placeholder_victim_01.jpg").read_bytes()
        assert msgs[0] == victim


class TestFrameServerErrorHandling:
    def test_missing_frame_file_fails_fast_on_init(self, tmp_path: Path, fake_redis):
        spec = {
            "scenario_id": "missing_frame",
            "origin": {"lat": 34.0, "lon": -118.5},
            "area_m": 200,
            "drones": [
                {
                    "drone_id": "drone1",
                    "home": {"lat": 34.0, "lon": -118.5, "alt": 0},
                    "waypoints": [{"id": "sp_001", "lat": 34.001, "lon": -118.5, "alt": 25}],
                    "speed_mps": 5,
                }
            ],
            "frame_mappings": {
                "drone1": [{"tick_range": [0, 60], "frame_file": "does_not_exist.jpg"}],
            },
            "scripted_events": [],
        }
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(spec))
        scenario = load_scenario(p)
        with pytest.raises(FileNotFoundError):
            FrameServer(scenario, fake_redis, frames_dir=FRAMES_DIR)

    def test_drone_with_no_mappings_skipped_silently(self, tmp_path: Path, fake_redis):
        """A drone in the scenario with no frame_mappings entry produces no camera output."""
        spec = {
            "scenario_id": "no_frames",
            "origin": {"lat": 34.0, "lon": -118.5},
            "area_m": 200,
            "drones": [
                {
                    "drone_id": "drone1",
                    "home": {"lat": 34.0, "lon": -118.5, "alt": 0},
                    "waypoints": [{"id": "sp_001", "lat": 34.001, "lon": -118.5, "alt": 25}],
                    "speed_mps": 5,
                }
            ],
            "frame_mappings": {},
            "scripted_events": [],
        }
        p = tmp_path / "x.yaml"
        p.write_text(yaml.safe_dump(spec))
        scenario = load_scenario(p)
        server = FrameServer(scenario, fake_redis, frames_dir=FRAMES_DIR)
        ps = _subscribe(fake_redis, per_drone_camera_channel("drone1"))
        server.tick(tick_index=0)
        msgs = _drain_bytes(ps, count=1)
        assert msgs == []


class TestFrameServerMultiDrone:
    def test_each_drone_gets_its_own_frame(self, fake_redis):
        scenario = load_scenario(REPO_ROOT / "sim" / "scenarios" / "disaster_zone_v1.yaml")
        server = FrameServer(scenario, fake_redis, frames_dir=FRAMES_DIR)
        ps1 = _subscribe(fake_redis, per_drone_camera_channel("drone1"))
        ps2 = _subscribe(fake_redis, per_drone_camera_channel("drone2"))
        server.tick(tick_index=0)
        m1 = _drain_bytes(ps1, count=1)
        m2 = _drain_bytes(ps2, count=1)
        assert len(m1) == 1
        assert len(m2) == 1
        block_a = (FRAMES_DIR / "placeholder_block_a_01.jpg").read_bytes()
        block_b = (FRAMES_DIR / "placeholder_block_b_01.jpg").read_bytes()
        assert m1[0] == block_a
        assert m2[0] == block_b
