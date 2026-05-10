"""Beat 5 Component 5 — durable per-drone finding_id counter.

These tests guarantee that the counter survives a drone-agent process
restart. Without persistence, a restart would reset to 0 and collide
finding_ids with previously-emitted ones; the EGS dedup set (Component 4)
keys on finding_id, so a collision silently drops a real new finding as
"already seen" — invisible-but-fatal data loss.
"""
from __future__ import annotations

import logging

import pytest

from agents.drone_agent.memory import MemoryStore


def test_counter_persists_across_restart(tmp_path):
    """Restart-equivalent: throw away the store, instantiate fresh in same dir,
    and the next id must NOT collide with any previously-emitted id."""
    m1 = MemoryStore(drone_id="drone1", persist_dir=tmp_path)
    assert m1.next_finding_id() == "f_drone1_1"
    assert m1.next_finding_id() == "f_drone1_2"
    assert m1.next_finding_id() == "f_drone1_3"

    # Drop the in-memory store; a fresh process re-loads from disk.
    del m1
    m2 = MemoryStore(drone_id="drone1", persist_dir=tmp_path)
    assert m2.next_finding_id() == "f_drone1_4"


def test_counter_starts_at_zero_when_no_file(tmp_path):
    """First boot in a clean dir → first id is _1, not _0 (1-indexed)."""
    m = MemoryStore(drone_id="drone1", persist_dir=tmp_path)
    assert m.next_finding_id() == "f_drone1_1"


def test_counter_recovers_from_empty_file(tmp_path):
    """Empty file (zero-byte; can happen during a write-truncate crash window)
    must be tolerated as 0, not raise. Ensures a single bad write doesn't
    brick the drone."""
    counter_path = tmp_path / "drone1_finding_counter.txt"
    counter_path.write_text("")

    m = MemoryStore(drone_id="drone1", persist_dir=tmp_path)
    assert m.next_finding_id() == "f_drone1_1"


def test_counter_recovers_from_whitespace_file(tmp_path):
    """Whitespace-only file (e.g. lone newline) → treat as 0, no warning,
    no crash."""
    counter_path = tmp_path / "drone1_finding_counter.txt"
    counter_path.write_text("   \n")

    m = MemoryStore(drone_id="drone1", persist_dir=tmp_path)
    assert m.next_finding_id() == "f_drone1_1"


def test_counter_recovers_from_non_integer_file(tmp_path, caplog):
    """Garbage in the file (e.g. someone hand-edited it, or the disk
    corrupted a sector) → log a warning, treat as 0, keep running."""
    counter_path = tmp_path / "drone1_finding_counter.txt"
    counter_path.write_text("abc")

    with caplog.at_level(logging.WARNING, logger="agents.drone_agent.memory"):
        m = MemoryStore(drone_id="drone1", persist_dir=tmp_path)

    assert m.next_finding_id() == "f_drone1_1"
    # Verify a warning was emitted naming the file and the bad content.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "non-integer" in r.message and "abc" in r.message
        for r in warnings
    ), f"Expected non-integer warning, got: {[r.message for r in warnings]}"


def test_counter_writes_to_disk_each_call(tmp_path):
    """The whole point of Component 5: every call updates disk, not just
    in-memory state. Otherwise a crash mid-batch loses ids."""
    counter_path = tmp_path / "drone1_finding_counter.txt"
    m = MemoryStore(drone_id="drone1", persist_dir=tmp_path)

    m.next_finding_id()
    assert counter_path.read_text() == "1"
    m.next_finding_id()
    assert counter_path.read_text() == "2"
    m.next_finding_id()
    assert counter_path.read_text() == "3"


def test_counter_isolated_per_drone(tmp_path):
    """drone1 and drone2 get separate files in the same dir; their counters
    must not interfere."""
    m1 = MemoryStore(drone_id="drone1", persist_dir=tmp_path)
    m2 = MemoryStore(drone_id="drone2", persist_dir=tmp_path)

    assert m1.next_finding_id() == "f_drone1_1"
    assert m1.next_finding_id() == "f_drone1_2"
    assert m2.next_finding_id() == "f_drone2_1"
    assert m1.next_finding_id() == "f_drone1_3"
    assert m2.next_finding_id() == "f_drone2_2"

    # And restarts of one drone don't disturb the other.
    del m1, m2
    m1b = MemoryStore(drone_id="drone1", persist_dir=tmp_path)
    m2b = MemoryStore(drone_id="drone2", persist_dir=tmp_path)
    assert m1b.next_finding_id() == "f_drone1_4"
    assert m2b.next_finding_id() == "f_drone2_3"
