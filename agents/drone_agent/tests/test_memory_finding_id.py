"""Test the per-drone monotonic finding_id counter."""
from __future__ import annotations

import re

from agents.drone_agent.memory import DroneMemory


def test_next_finding_id_format():
    mem = DroneMemory(drone_id="drone1")
    fid = mem.next_finding_id()
    assert re.match(r"^f_drone1_\d+$", fid), f"Bad format: {fid!r}"


def test_next_finding_id_monotonic():
    mem = DroneMemory(drone_id="drone2")
    a = mem.next_finding_id()
    b = mem.next_finding_id()
    c = mem.next_finding_id()
    assert a != b != c
    a_n = int(a.rsplit("_", 1)[1])
    b_n = int(b.rsplit("_", 1)[1])
    c_n = int(c.rsplit("_", 1)[1])
    assert b_n == a_n + 1 == c_n - 1


def test_next_finding_id_different_drones():
    """Two DroneMemory instances must produce IDs that match their respective drone_id."""
    m1 = DroneMemory(drone_id="drone1")
    m2 = DroneMemory(drone_id="drone7")
    f1 = m1.next_finding_id()
    f2 = m2.next_finding_id()
    assert f1.startswith("f_drone1_")
    assert f2.startswith("f_drone7_")
