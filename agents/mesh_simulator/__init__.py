"""Mesh simulator: Euclidean-distance dropout filter on swarm.broadcasts.*.

Owned by Person 1 (Sim Lead). Subscribes to drones.*.state to maintain a position
cache, then re-publishes peer broadcasts only to receivers within
CONFIG.mesh.range_meters. Also publishes mesh.adjacency_matrix at 1 Hz.
"""
