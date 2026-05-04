"""Pure-functional Euclidean (haversine) range filter for mesh forwarding.

This module is the load-bearing logic of the mesh simulator: given a swarm of
drone positions, compute who can hear whom. The Redis I/O wrapper (main.py)
depends on this module for every forwarding decision. Keep it side-effect-free
so it remains trivially testable.

EGS link is gated by a *separate* range threshold (CONFIG.mesh.egs_link_range_meters)
because the EGS antenna is assumed to be more powerful than a drone-to-drone
WiFi mesh radio per docs/08-mesh-communication.md (lines 105–113).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from sim.geo import haversine_meters

# Sentinel ID used in adjacency / position dicts for the ground station node.
# Matches docs/20-integration-contracts.md Contract 9 (in_mesh_range_of items
# may be a drone_id or the literal "egs").
EGS_NODE_ID = "egs"

LatLon = Tuple[float, float]


def filter_recipients(
    *,
    sender_id: str,
    sender_pos: LatLon,
    drone_positions: Dict[str, LatLon],
    range_m: float,
) -> List[str]:
    """Return the sorted list of node IDs that should receive a broadcast from sender.

    Excludes the sender. Distance is haversine, in meters.
    """
    out: List[str] = []
    for node_id, pos in drone_positions.items():
        if node_id == sender_id:
            continue
        if haversine_meters(sender_pos, pos) <= range_m:
            out.append(node_id)
    return sorted(out)


def in_range_pairs(
    drone_positions: Dict[str, LatLon],
    *,
    range_m: float,
    egs_link_range_m: float | None = None,
) -> Dict[str, List[str]]:
    """Build a {node_id: [in_range_neighbours]} adjacency map.

    Drone-drone links use ``range_m``. If ``egs_link_range_m`` is provided AND
    the special node ``EGS_NODE_ID`` is present in ``drone_positions``, the
    drone↔EGS edges use ``egs_link_range_m`` instead. All neighbour lists are
    sorted for deterministic output.
    """
    adj: Dict[str, List[str]] = {nid: [] for nid in drone_positions}
    nodes = list(drone_positions.items())
    for i, (a_id, a_pos) in enumerate(nodes):
        for b_id, b_pos in nodes[i + 1:]:
            d = haversine_meters(a_pos, b_pos)
            if a_id == EGS_NODE_ID or b_id == EGS_NODE_ID:
                limit = egs_link_range_m if egs_link_range_m is not None else range_m
            else:
                limit = range_m
            if d <= limit:
                adj[a_id].append(b_id)
                adj[b_id].append(a_id)
    for nid in adj:
        adj[nid].sort()
    return adj
