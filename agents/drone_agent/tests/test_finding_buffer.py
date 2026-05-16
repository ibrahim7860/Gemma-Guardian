"""FindingBuffer — JSONL persistence + FIFO drain + crash-restore semantics.

Component 1 of Beat 5 Path A-full. Buffers findings produced during a drone's
EGS-link-down window and replays them in order on restore.
"""
from __future__ import annotations

import json

import pytest

from agents.drone_agent.finding_buffer import FindingBuffer


def _read_jsonl(path):
    text = path.read_text()
    if not text.strip():
        return []
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _make_finding(idx: int) -> dict:
    """A minimal finding-shaped dict. Buffer doesn't care about schema; tests
    only need stable shape + a recognizable index for ordering assertions."""
    return {"finding_id": f"f_drone1_{idx}", "type": "victim", "severity": idx}


def test_append_persists_to_jsonl(tmp_path):
    buf = FindingBuffer(persist_path=tmp_path / "q.jsonl", maxlen=10)
    for i in range(1, 4):
        buf.append("drones.drone1.findings", _make_finding(i))
    assert len(buf) == 3
    rows = _read_jsonl(tmp_path / "q.jsonl")
    assert len(rows) == 3
    for i, row in enumerate(rows, start=1):
        assert row["channel"] == "drones.drone1.findings"
        assert row["payload"]["finding_id"] == f"f_drone1_{i}"
        assert "ts_iso" in row and row["ts_iso"]


def test_drain_returns_fifo_order_and_clears(tmp_path):
    buf = FindingBuffer(persist_path=tmp_path / "q.jsonl", maxlen=10)
    for i in (1, 2, 3):
        buf.append("drones.drone1.findings", _make_finding(i))

    out = buf.drain()
    ids = [p["finding_id"] for (_ch, p) in out]
    assert ids == ["f_drone1_1", "f_drone1_2", "f_drone1_3"]

    assert len(buf) == 0
    # File truncated atomically (write_text("")).
    assert (tmp_path / "q.jsonl").read_text() == ""


def test_overflow_drops_oldest(tmp_path):
    """deque(maxlen=N) drops oldest. We document this in the module docstring;
    test makes the contract executable."""
    buf = FindingBuffer(persist_path=tmp_path / "q.jsonl", maxlen=3)
    for i in range(1, 6):
        buf.append("drones.drone1.findings", _make_finding(i))
    assert len(buf) == 3
    out = buf.drain()
    ids = [p["finding_id"] for (_ch, p) in out]
    # In-memory deque holds the most recent 3 entries (3, 4, 5).
    assert ids == ["f_drone1_3", "f_drone1_4", "f_drone1_5"]


def test_restore_from_disk_rehydrates_deque(tmp_path):
    path = tmp_path / "q.jsonl"
    lines = []
    for i in range(1, 4):
        lines.append(
            json.dumps({
                "channel": "drones.drone1.findings",
                "payload": _make_finding(i),
                "ts_iso": "2026-05-10T00:00:00.000Z",
            })
        )
    path.write_text("\n".join(lines) + "\n")

    buf = FindingBuffer(persist_path=path, maxlen=10)
    n = buf.restore_from_disk()
    assert n == 3
    assert len(buf) == 3
    out = buf.drain()
    ids = [p["finding_id"] for (_ch, p) in out]
    assert ids == ["f_drone1_1", "f_drone1_2", "f_drone1_3"]


def test_restore_from_empty_file_is_idempotent(tmp_path):
    path = tmp_path / "q.jsonl"
    path.write_text("")
    buf = FindingBuffer(persist_path=path, maxlen=10)
    assert buf.restore_from_disk() == 0
    assert len(buf) == 0


def test_restore_from_missing_file_is_idempotent(tmp_path):
    path = tmp_path / "missing.jsonl"
    buf = FindingBuffer(persist_path=path, maxlen=10)
    assert buf.restore_from_disk() == 0
    assert len(buf) == 0
    # Restore should not have created a stray file either.
    assert not path.exists()


def test_restore_from_disk_caps_return_at_maxlen(tmp_path):
    """REGRESSION (review finding #2): if the on-disk JSONL has MORE lines
    than maxlen (because a prior incarnation's deque overflowed and dropped
    oldest in-memory while the file kept appending), restore_from_disk()
    must return the deque length, not the line count. Otherwise the caller's
    log message claims to have restored more entries than will actually
    replay.
    """
    path = tmp_path / "q.jsonl"
    lines = [
        json.dumps({
            "channel": "drones.drone1.findings",
            "payload": _make_finding(i),
            "ts_iso": "2026-05-10T00:00:00.000Z",
        })
        for i in range(1, 11)  # 10 lines on disk
    ]
    path.write_text("\n".join(lines) + "\n")

    buf = FindingBuffer(persist_path=path, maxlen=3)
    n = buf.restore_from_disk()
    # Returns the deque length (3), not the line count (10).
    assert n == 3
    assert len(buf) == 3
    # Sanity: deque holds the LAST 3 (8, 9, 10) — drop-oldest.
    out = buf.drain()
    ids = [p["finding_id"] for (_ch, p) in out]
    assert ids == ["f_drone1_8", "f_drone1_9", "f_drone1_10"]


def test_append_uses_single_writer_across_window(tmp_path):
    """REGRESSION (review finding #3): the append path must NOT open and close
    the file per call. With line-buffered text mode the writer is opened
    lazily on first append and stays open until drain() / close(). We assert
    by checking that the writer attribute is set after the first append, the
    same writer object handles subsequent appends, and drain() releases it.
    """
    buf = FindingBuffer(persist_path=tmp_path / "q.jsonl", maxlen=10)
    # Pre-append: writer is None (lazy).
    assert buf._writer is None

    buf.append("drones.drone1.findings", _make_finding(1))
    assert buf._writer is not None
    first_writer = buf._writer
    assert not first_writer.closed

    # Subsequent appends reuse the same writer.
    buf.append("drones.drone1.findings", _make_finding(2))
    buf.append("drones.drone1.findings", _make_finding(3))
    assert buf._writer is first_writer
    assert not first_writer.closed

    # Persistence is durable mid-window (line-buffered flushes on each \n).
    rows = _read_jsonl(tmp_path / "q.jsonl")
    assert len(rows) == 3

    # Drain releases the writer.
    buf.drain()
    assert buf._writer is None
    # The file handle we held is closed.
    assert first_writer.closed


def test_close_releases_writer_without_truncating_file(tmp_path):
    """close() releases the file descriptor but PRESERVES on-disk JSONL so a
    subsequent process can restore_from_disk()."""
    path = tmp_path / "q.jsonl"
    buf = FindingBuffer(persist_path=path, maxlen=10)
    buf.append("drones.drone1.findings", _make_finding(1))
    buf.append("drones.drone1.findings", _make_finding(2))
    held = buf._writer
    assert held is not None and not held.closed

    buf.close()
    assert buf._writer is None
    assert held.closed
    # On-disk JSONL preserved (close ≠ drain).
    rows = _read_jsonl(path)
    assert len(rows) == 2


def test_close_is_idempotent(tmp_path):
    """Calling close() twice (or before any append) is a no-op."""
    buf = FindingBuffer(persist_path=tmp_path / "q.jsonl", maxlen=10)
    # close() before any append: no writer to close, no error.
    buf.close()
    buf.append("drones.drone1.findings", _make_finding(1))
    buf.close()
    buf.close()  # second close is a no-op
    assert buf._writer is None


def test_append_after_drain_reopens_writer(tmp_path):
    """After drain() closes the writer, the next append must re-open it
    cleanly. Otherwise a multi-window standalone session would break."""
    path = tmp_path / "q.jsonl"
    buf = FindingBuffer(persist_path=path, maxlen=10)
    buf.append("drones.drone1.findings", _make_finding(1))
    buf.drain()
    assert buf._writer is None

    # Second window.
    buf.append("drones.drone1.findings", _make_finding(2))
    assert buf._writer is not None and not buf._writer.closed
    rows = _read_jsonl(path)
    assert len(rows) == 1
    assert rows[0]["payload"]["finding_id"] == "f_drone1_2"


def test_restore_from_corrupted_jsonl_skips_bad_lines(tmp_path, caplog):
    import logging

    # Attach caplog's handler directly so records are captured regardless
    # of root-logger handler chain (works around lastResort-only setups).
    target_logger = logging.getLogger("agents.drone_agent.finding_buffer")
    target_logger.addHandler(caplog.handler)
    target_logger.setLevel(logging.DEBUG)

    path = tmp_path / "q.jsonl"
    valid1 = json.dumps({
        "channel": "drones.drone1.findings",
        "payload": _make_finding(1),
        "ts_iso": "2026-05-10T00:00:00.000Z",
    })
    valid2 = json.dumps({
        "channel": "drones.drone1.findings",
        "payload": _make_finding(2),
        "ts_iso": "2026-05-10T00:00:01.000Z",
    })
    # Bad lines: malformed JSON, missing channel, missing payload.
    bad1 = "{not valid json"
    bad2 = json.dumps({"payload": {"x": 1}, "ts_iso": "..."})
    bad3 = json.dumps({"channel": "drones.drone1.findings", "ts_iso": "..."})
    path.write_text("\n".join([valid1, bad1, bad2, valid2, bad3]) + "\n")

    buf = FindingBuffer(persist_path=path, maxlen=10)
    n = buf.restore_from_disk()
    assert n == 2
    assert len(buf) == 2
    # At least one warning per bad line, but we don't lock down the count
    # exactly so the implementation can change wording.
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) >= 1

    # Cleanup: remove the handler to avoid leaking across tests.
    target_logger.removeHandler(caplog.handler)
