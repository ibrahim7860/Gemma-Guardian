"""Beat 5 Component 5 — ActionNode must source finding_ids from
MemoryStore.next_finding_id (or its injected callable equivalent), NOT
maintain its own parallel counter.

Bundles the deferred TODO "Replace ActionNode._finding_counter with
MemoryStore.next_finding_id()" — verifies the wiring is correct so we
don't drift.
"""
from __future__ import annotations

import re

import pytest

from agents.drone_agent.action import ActionNode
from agents.drone_agent.memory import MemoryStore


class _RecordingPublisher:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def publish(self, channel: str, payload: dict) -> None:
        self.calls.append((channel, payload))


def _report_finding_call() -> dict:
    return {
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


def test_action_uses_injected_memory_for_finding_id(tmp_path, monkeypatch):
    """ActionNode wired with memory.next_finding_id must produce ids that
    advance the MemoryStore's counter — proving there's a single source of
    truth, not a parallel ActionNode counter."""
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", tmp_path / "frames")

    memory = MemoryStore(drone_id="drone1", persist_dir=tmp_path)
    pub = _RecordingPublisher()
    action = ActionNode(
        drone_id="drone1",
        publisher=pub,
        next_id_fn=memory.next_finding_id,
    )

    sender = {"lat": 34.0, "lon": -118.5, "alt": 25.0}
    action.execute(_report_finding_call(), sender_position=sender)
    action.execute(_report_finding_call(), sender_position=sender)

    finding_calls = [c for c in pub.calls if c[0] == "drones.drone1.findings"]
    assert len(finding_calls) == 2
    fid1 = finding_calls[0][1]["finding_id"]
    fid2 = finding_calls[1][1]["finding_id"]

    assert fid1 == "f_drone1_1"
    assert fid2 == "f_drone1_2"

    # And the MemoryStore's counter advanced — proving they share the source.
    assert memory.next_finding_id() == "f_drone1_3"


def test_action_node_has_no_independent_finding_counter():
    """Regression guard: ActionNode must not expose a `_finding_counter`
    attribute that drifts from the memory's counter. The fallback path
    uses `_fallback_counter` (different name + only used when no callable
    is injected); the production wiring path doesn't even touch a local
    counter."""
    from agents.drone_agent.memory import MemoryStore

    memory = MemoryStore(drone_id="drone1", persist_dir=None) \
        if False else None  # avoid touching default log dir in this assertion

    # When wired with an injected callable, ActionNode must not maintain
    # `_finding_counter` (the old field name from before this PR).
    action = ActionNode(
        drone_id="drone1",
        next_id_fn=lambda: "f_drone1_42",
    )
    assert not hasattr(action, "_finding_counter"), (
        "ActionNode should no longer maintain its own _finding_counter; "
        "finding_ids must come from the injected next_id_fn (typically "
        "MemoryStore.next_finding_id)."
    )


def test_action_finding_id_persists_across_action_node_restart(tmp_path, monkeypatch):
    """End-to-end of the durability claim: the same MemoryStore-backed
    counter survives swapping out the ActionNode (mimicking a process
    restart). New ActionNode + same MemoryStore-on-disk → no id collision."""
    monkeypatch.setattr("agents.drone_agent.action.FRAMES_DIR", tmp_path / "frames")
    sender = {"lat": 34.0, "lon": -118.5, "alt": 25.0}

    # First "process": emit two findings.
    mem1 = MemoryStore(drone_id="drone1", persist_dir=tmp_path)
    pub1 = _RecordingPublisher()
    a1 = ActionNode(drone_id="drone1", publisher=pub1, next_id_fn=mem1.next_finding_id)
    a1.execute(_report_finding_call(), sender_position=sender)
    a1.execute(_report_finding_call(), sender_position=sender)
    fids_1 = [
        c[1]["finding_id"] for c in pub1.calls
        if c[0] == "drones.drone1.findings"
    ]
    assert fids_1 == ["f_drone1_1", "f_drone1_2"]

    # Drop everything; instantiate a fresh MemoryStore (re-loads counter
    # from disk) and a fresh ActionNode.
    del mem1, a1, pub1
    mem2 = MemoryStore(drone_id="drone1", persist_dir=tmp_path)
    pub2 = _RecordingPublisher()
    a2 = ActionNode(drone_id="drone1", publisher=pub2, next_id_fn=mem2.next_finding_id)
    a2.execute(_report_finding_call(), sender_position=sender)

    fids_2 = [
        c[1]["finding_id"] for c in pub2.calls
        if c[0] == "drones.drone1.findings"
    ]
    # _3 — picks up where the prior process left off; no collision with _1/_2.
    assert fids_2 == ["f_drone1_3"]
