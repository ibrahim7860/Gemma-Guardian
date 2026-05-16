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


class _PartialFailPublisher:
    """Spy that succeeds for the first ``ok_count`` publishes, then raises.

    Used to simulate a Redis hiccup mid-flush. After the failure point the
    BufferedPublisher must re-buffer the un-published entries and revert to
    standalone so the next reconciliation tick retries.
    """

    def __init__(self, ok_count: int):
        self.calls: list[tuple[str, dict]] = []
        self._ok_count = ok_count
        self.closed = False

    def publish(self, channel: str, payload: dict) -> None:
        if len(self.calls) >= self._ok_count:
            raise ConnectionError("simulated redis hiccup")
        self.calls.append((channel, payload))

    def close(self) -> None:
        self.closed = True


def test_set_standalone_partial_flush_re_buffers_remaining(buffer, caplog):
    """REGRESSION (review finding #1): if inner.publish() raises mid-flush
    after some entries have been delivered, the BufferedPublisher must
    re-buffer the REMAINING entries (not the ones already published — that
    would double-publish) and revert to standalone for retry on the next
    reconciliation tick.
    """
    import logging

    # Attach caplog's handler directly so records are captured regardless
    # of root-logger handler chain (works around lastResort-only setups).
    target_logger = logging.getLogger("agents.drone_agent.buffered_publisher")
    target_logger.addHandler(caplog.handler)
    target_logger.setLevel(logging.DEBUG)

    # First two publishes succeed, third raises. Entries 3, 4, 5 should be
    # re-buffered.
    inner = _PartialFailPublisher(ok_count=2)
    bp = BufferedPublisher(inner=inner, buffer=buffer)
    bp.set_standalone(True)
    for i in (1, 2, 3, 4, 5):
        bp.publish("drones.drone1.findings", _make_finding(i))
    assert len(buffer) == 5

    # set_standalone(False) attempts the flush; failure does NOT raise out.
    bp.set_standalone(False)

    # Entries 1 and 2 were published successfully.
    ids_published = [p["finding_id"] for (_ch, p) in inner.calls]
    assert ids_published == ["f_drone1_1", "f_drone1_2"]

    # Entries 3, 4, 5 are back in the buffer in original order.
    assert len(buffer) == 3
    out = buffer.drain()
    ids_rebuffered = [p["finding_id"] for (_ch, p) in out]
    assert ids_rebuffered == ["f_drone1_3", "f_drone1_4", "f_drone1_5"]

    # Publisher reverted to standalone for retry on the next tick.
    assert bp.is_standalone is True

    # An ERROR-level log fired so the operator can see it.
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("re-buffering" in r.getMessage() for r in errors)

    # Cleanup: remove the handler to avoid leaking across tests.
    target_logger.removeHandler(caplog.handler)


def test_set_standalone_partial_flush_retry_succeeds_after_recovery(buffer):
    """Once the inner publisher recovers, the next set_standalone(True→False)
    transition replays the re-buffered entries cleanly. No double-publish of
    entries that already succeeded on the first attempt.
    """
    fail_then_ok = _PartialFailPublisher(ok_count=2)
    bp = BufferedPublisher(inner=fail_then_ok, buffer=buffer)
    bp.set_standalone(True)
    for i in (1, 2, 3, 4, 5):
        bp.publish("drones.drone1.findings", _make_finding(i))
    bp.set_standalone(False)  # First attempt: 1, 2 succeed; 3-5 re-buffered.

    # Swap in a healthy publisher and replace bp's inner. (Simulating "Redis
    # came back" without modeling reconnect logic in the test.)
    healthy = _RecordingPublisher()
    bp._inner = healthy

    # Reconciliation tick — same monitor still says active. Set False again.
    # This is safe because bp reverted to standalone after the partial flush.
    bp.set_standalone(False)

    # Healthy inner saw exactly entries 3, 4, 5 in order — no replay of 1-2.
    ids = [p["finding_id"] for (_ch, p) in healthy.calls]
    assert ids == ["f_drone1_3", "f_drone1_4", "f_drone1_5"]
    assert len(buffer) == 0
    assert bp.is_standalone is False


def test_set_standalone_partial_flush_at_first_entry(buffer):
    """Edge case: first publish raises. ALL entries must be re-buffered (none
    were successfully published)."""
    inner = _PartialFailPublisher(ok_count=0)
    bp = BufferedPublisher(inner=inner, buffer=buffer)
    bp.set_standalone(True)
    for i in (1, 2, 3):
        bp.publish("drones.drone1.findings", _make_finding(i))
    bp.set_standalone(False)

    assert inner.calls == []
    assert len(buffer) == 3
    assert bp.is_standalone is True


def test_close_releases_buffer_writer(tmp_path):
    """close() must propagate to the FindingBuffer so the lazily-opened
    file handle is released. Otherwise a long-running drone process leaks
    one file descriptor per standalone window."""
    persist_path = tmp_path / "q.jsonl"
    buf = FindingBuffer(persist_path=persist_path, maxlen=100)
    inner = _RecordingPublisher()
    bp = BufferedPublisher(inner=inner, buffer=buf)
    bp.set_standalone(True)
    bp.publish("drones.drone1.findings", _make_finding(1))
    held = buf._writer
    assert held is not None and not held.closed

    bp.close()
    # Writer released; on-disk JSONL preserved.
    assert buf._writer is None
    assert held.closed
    assert persist_path.read_text().strip() != ""


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
