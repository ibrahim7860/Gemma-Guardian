"""ActionNode publishes Contract-4 findings with image_path + schema validation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.drone_agent.action import ActionNode
from shared.contracts import validate


class _RecordingPublisher:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def publish(self, channel: str, payload: dict) -> None:
        self.calls.append((channel, payload))


@pytest.fixture
def frames_dir(tmp_path):
    return tmp_path / "frames"


def test_published_finding_validates_against_contract_4(frames_dir, monkeypatch):
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", frames_dir)
    pub = _RecordingPublisher()
    action = ActionNode(drone_id="drone1", publisher=pub)

    call = {
        "function": "report_finding",
        "arguments": {
            "type": "victim",
            "severity": 4,
            "gps_lat": 34.0005,
            "gps_lon": -118.5003,
            "confidence": 0.78,
            "visual_description": "person prone in rubble, partially covered",
        },
    }
    sender_position = {"lat": 34.0005, "lon": -118.5003, "alt": 25.0}
    raw_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"
    action.execute(call, sender_position=sender_position, raw_frame_jpeg=raw_jpeg)

    finding_calls = [c for c in pub.calls if c[0] == "drones.drone1.findings"]
    assert len(finding_calls) == 1
    payload = finding_calls[0][1]

    outcome = validate("finding", payload)
    assert outcome.valid, outcome.errors

    assert payload["image_path"]
    assert Path(payload["image_path"]).exists()
    assert Path(payload["image_path"]).read_bytes() == raw_jpeg


def test_published_peer_broadcast_validates_against_contract_6(frames_dir, monkeypatch):
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", frames_dir)
    pub = _RecordingPublisher()
    action = ActionNode(drone_id="drone1", publisher=pub)
    call = {
        "function": "report_finding",
        "arguments": {
            "type": "fire", "severity": 3, "gps_lat": 34.0,
            "gps_lon": -118.5, "confidence": 0.9,
            "visual_description": "rooftop flames clearly visible",
        },
    }
    action.execute(call, sender_position={"lat": 34.0, "lon": -118.5, "alt": 25.0},
                   raw_frame_jpeg=b"\xff\xd8\xff\xd9")

    bcast = [c for c in pub.calls if c[0] == "swarm.broadcasts.drone1"]
    assert len(bcast) == 1
    outcome = validate("peer_broadcast", bcast[0][1])
    assert outcome.valid, outcome.errors


def test_image_path_skipped_when_no_raw_frame_provided(frames_dir, monkeypatch):
    """Headless tests / replay tools may not pass a raw frame. Action falls
    back to a sentinel string that satisfies the Contract 4 minLength constraint."""
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", frames_dir)
    pub = _RecordingPublisher()
    action = ActionNode(drone_id="drone1", publisher=pub)
    call = {
        "function": "report_finding",
        "arguments": {
            "type": "smoke", "severity": 2, "gps_lat": 34.0,
            "gps_lon": -118.5, "confidence": 0.65,
            "visual_description": "thin grey smoke column rising slowly",
        },
    }
    action.execute(call, sender_position={"lat": 34.0, "lon": -118.5, "alt": 25.0})

    finding_calls = [c for c in pub.calls if c[0] == "drones.drone1.findings"]
    assert len(finding_calls) == 1
    assert finding_calls[0][1]["image_path"] == "<no_capture>"


def test_invalid_finding_payload_raises_before_publish(frames_dir, monkeypatch):
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", frames_dir)
    pub = _RecordingPublisher()
    action = ActionNode(drone_id="drone1", publisher=pub)

    # Severity 7 violates _common.json severity (1..5).
    call = {
        "function": "report_finding",
        "arguments": {
            "type": "victim", "severity": 7, "gps_lat": 34.0,
            "gps_lon": -118.5, "confidence": 0.9,
            "visual_description": "person prone in rubble",
        },
    }
    from shared.contracts import ContractError
    with pytest.raises(ContractError):
        action.execute(call, sender_position={"lat": 34.0, "lon": -118.5, "alt": 25.0},
                       raw_frame_jpeg=b"\xff\xd8\xff\xd9")
    assert pub.calls == []  # nothing published


def test_request_assist_publishes_valid_peer_broadcast(frames_dir, monkeypatch):
    """eng-review test gap: assist_request peer_broadcast schema validation."""
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", frames_dir)
    pub = _RecordingPublisher()
    action = ActionNode(drone_id="drone1", publisher=pub)
    call = {
        "function": "request_assist",
        "arguments": {
            "reason": "victim trapped under heavy debris, need second drone",
            "urgency": "high",
        },
    }
    action.execute(call, sender_position={"lat": 34.0, "lon": -118.5, "alt": 25.0})

    bcast = [c for c in pub.calls if c[0] == "swarm.broadcasts.drone1"]
    assert len(bcast) == 1
    payload = bcast[0][1]
    assert payload["broadcast_type"] == "assist_request"
    assert payload["payload"]["urgency"] == "high"
    outcome = validate("peer_broadcast", payload)
    assert outcome.valid, outcome.errors


def test_return_to_base_publishes_cmd_payload(frames_dir, monkeypatch):
    """eng-review test gap: drones.<id>.cmd publish on return_to_base."""
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", frames_dir)
    pub = _RecordingPublisher()
    action = ActionNode(drone_id="drone1", publisher=pub)
    call = {
        "function": "return_to_base",
        "arguments": {"reason": "low_battery"},
    }
    action.execute(call, sender_position={"lat": 34.0, "lon": -118.5, "alt": 25.0})

    cmd_calls = [c for c in pub.calls if c[0] == "drones.drone1.cmd"]
    assert len(cmd_calls) == 1
    payload = cmd_calls[0][1]
    assert payload["drone_id"] == "drone1"
    assert payload["command"] == "return_to_base"
    assert payload["reason"] == "low_battery"
    assert payload["timestamp"]
