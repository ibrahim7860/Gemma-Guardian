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


def test_restore_from_corrupted_jsonl_skips_bad_lines(tmp_path, caplog):
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
    with caplog.at_level("WARNING", logger="agents.drone_agent.finding_buffer"):
        n = buf.restore_from_disk()
    assert n == 2
    assert len(buf) == 2
    # At least one warning per bad line, but we don't lock down the count
    # exactly so the implementation can change wording.
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) >= 1
