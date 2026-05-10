"""BufferedPublisher — buffer-while-standalone, FIFO replay on restore.

Component 1 of Beat 5 Path A-full. Wraps any Publisher (Protocol from
action.py) and gates publishes on the `should_buffer(channel)` predicate.
"""
from __future__ import annotations

import pytest

from agents.drone_agent.buffered_publisher import BufferedPublisher
from agents.drone_agent.finding_buffer import FindingBuffer


class _RecordingPublisher:
    """Spy matching the Publisher Protocol — same shape as the one in
    test_action_finding_publish.py:7-11. Reused here so unit tests stay
    independent of Redis."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    def publish(self, channel: str, payload: dict) -> None:
        self.calls.append((channel, payload))

    def close(self) -> None:
        self.closed = True


def _make_finding(idx: int) -> dict:
    return {"finding_id": f"f_drone1_{idx}", "type": "victim", "severity": idx}


@pytest.fixture
def buffer(tmp_path):
    return FindingBuffer(persist_path=tmp_path / "q.jsonl", maxlen=100)


def test_passes_through_when_not_standalone(buffer):
    inner = _RecordingPublisher()
    bp = BufferedPublisher(inner=inner, buffer=buffer)
    bp.publish("drones.drone1.findings", _make_finding(1))
    assert inner.calls == [("drones.drone1.findings", _make_finding(1))]
    assert len(buffer) == 0


def test_buffers_when_standalone(buffer):
    inner = _RecordingPublisher()
    bp = BufferedPublisher(inner=inner, buffer=buffer)
    bp.set_standalone(True)
    for i in (1, 2, 3):
        bp.publish("drones.drone1.findings", _make_finding(i))
    assert inner.calls == []
    assert len(buffer) == 3


def test_flush_drains_to_inner_in_order(buffer):
    inner = _RecordingPublisher()
    bp = BufferedPublisher(inner=inner, buffer=buffer)
    bp.set_standalone(True)
    for i in (1, 2, 3):
        bp.publish("drones.drone1.findings", _make_finding(i))
    bp.set_standalone(False)
    assert len(inner.calls) == 3
    ids = [p["finding_id"] for (_ch, p) in inner.calls]
    assert ids == ["f_drone1_1", "f_drone1_2", "f_drone1_3"]
    assert len(buffer) == 0


def test_should_buffer_predicate_filters_channels(buffer):
    """Only `drones.<id>.findings` should buffer by default. Peer broadcasts
    and cmd channels pass through even while standalone (they're scoped to
    the local mesh, not the EGS link)."""
    inner = _RecordingPublisher()
    bp = BufferedPublisher(inner=inner, buffer=buffer)
    bp.set_standalone(True)

    bp.publish("swarm.broadcasts.drone1", {"broadcast_id": "x"})
    bp.publish("drones.drone1.cmd", {"command": "return_to_base"})
    bp.publish("drones.drone1.findings", _make_finding(1))

    # Peer + cmd passed through; finding was buffered.
    channels = [c for (c, _) in inner.calls]
    assert "swarm.broadcasts.drone1" in channels
    assert "drones.drone1.cmd" in channels
    assert "drones.drone1.findings" not in channels
    assert len(buffer) == 1


def test_close_does_not_lose_buffered_entries(tmp_path):
    """Close should NOT clear the persisted JSONL — a fresh process can
    rehydrate from disk and replay on link restore."""
    persist_path = tmp_path / "q.jsonl"
    buf = FindingBuffer(persist_path=persist_path, maxlen=100)
    inner = _RecordingPublisher()
    bp = BufferedPublisher(inner=inner, buffer=buf)
    bp.set_standalone(True)
    bp.publish("drones.drone1.findings", _make_finding(1))
    bp.publish("drones.drone1.findings", _make_finding(2))

    bp.close()
    assert inner.closed is True

    # File survives the close.
    assert persist_path.exists()
    assert persist_path.read_text().strip() != ""
    # And a fresh buffer pointing at the same path can pick the entries up.
    fresh = FindingBuffer(persist_path=persist_path, maxlen=100)
    assert fresh.restore_from_disk() == 2


def test_set_standalone_idempotent_when_unchanged(buffer):
    inner = _RecordingPublisher()
    bp = BufferedPublisher(inner=inner, buffer=buffer)

    # True → True is a no-op.
    bp.set_standalone(True)
    bp.publish("drones.drone1.findings", _make_finding(1))
    bp.set_standalone(True)
    bp.publish("drones.drone1.findings", _make_finding(2))
    assert inner.calls == []
    assert len(buffer) == 2

    # False → False is a no-op (no second flush, no double-publish).
    bp.set_standalone(False)
    assert len(inner.calls) == 2
    bp.set_standalone(False)
    assert len(inner.calls) == 2
