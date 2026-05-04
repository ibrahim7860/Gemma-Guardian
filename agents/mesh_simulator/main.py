"""Mesh simulator main loop.

Subscribes to ``drones.*.state`` (psubscribe) to maintain a position cache,
and to ``swarm.broadcasts.*`` to forward peer broadcasts to in-range
recipients via ``swarm.<receiver_id>.visible_to.<receiver_id>``.

Also publishes a JSON adjacency snapshot on ``mesh.adjacency_matrix`` once per
second (configurable). The snapshot is debug-only — agents do not consume it,
but Person 4's dashboard can render the live mesh topology.

Public surface for tests:
    MeshSimulator(redis, range_m, egs_link_range_m)
    sim.ingest_state(state_dict)
    sim.set_egs_position(lat, lon)
    sim.forward_broadcast(sender_id, raw_bytes)
    sim.publish_adjacency()

The CLI entry point ``main()`` wires these methods to redis-py pubsub and
spins a blocking loop.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

# Add project root to sys.path for direct-script invocation.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import redis

from agents.mesh_simulator.range_filter import (
    EGS_NODE_ID,
    filter_recipients,
    in_range_pairs,
)
from shared.contracts.config import CONFIG
from shared.contracts.topics import (
    MESH_ADJACENCY,
    PER_DRONE_STATE,
    SWARM_BROADCAST,
    swarm_visible_to_channel,
)

# psubscribe patterns derived from the channel templates (single source of truth).
_STATE_PATTERN = PER_DRONE_STATE.replace("{drone_id}", "*")
_BROADCAST_PATTERN = SWARM_BROADCAST.replace("{drone_id}", "*")

LatLon = Tuple[float, float]


_STATE_CHANNEL_RE = re.compile(r"^drones\.(drone\d+)\.state$")
_BROADCAST_CHANNEL_RE = re.compile(r"^swarm\.broadcasts\.(drone\d+)$")


def drone_id_from_state_channel(channel: str) -> Optional[str]:
    m = _STATE_CHANNEL_RE.match(channel)
    return m.group(1) if m else None


def drone_id_from_broadcast_channel(channel: str) -> Optional[str]:
    m = _BROADCAST_CHANNEL_RE.match(channel)
    return m.group(1) if m else None


class MeshSimulator:
    """Distance-gated republisher for swarm broadcasts."""

    def __init__(
        self,
        redis_client: redis.Redis,
        *,
        range_m: float,
        egs_link_range_m: float,
    ) -> None:
        self.redis = redis_client
        self.range_m = range_m
        self.egs_link_range_m = egs_link_range_m
        self._positions: Dict[str, LatLon] = {}

    # --- Position cache management -------------------------------------------------

    def ingest_state(self, payload: dict) -> None:
        try:
            drone_id = payload["drone_id"]
            lat = payload["position"]["lat"]
            lon = payload["position"]["lon"]
        except (KeyError, TypeError):
            return  # malformed; drop silently — drones publish at 2 Hz, we'll catch up
        self._positions[drone_id] = (lat, lon)

    def set_egs_position(self, lat: float, lon: float) -> None:
        self._positions[EGS_NODE_ID] = (lat, lon)

    def known_positions(self) -> Dict[str, LatLon]:
        return dict(self._positions)

    # --- Broadcast forwarding ------------------------------------------------------

    def forward_broadcast(self, sender_id: str, raw_message: bytes) -> int:
        """Forward a raw broadcast payload to every in-range recipient.

        Returns the number of recipients the message was actually published to.
        Drops silently if the sender's position is unknown — we cannot range-gate
        without it.
        """
        sender_pos = self._positions.get(sender_id)
        if sender_pos is None:
            return 0
        recipients = filter_recipients(
            sender_id=sender_id,
            sender_pos=sender_pos,
            drone_positions=self._positions,
            range_m=self.range_m,
        )
        published = 0
        for rid in recipients:
            # EGS node receives via the regular per-drone forwarding too; range
            # gating here uses the wider radius if this is a drone↔EGS pair.
            self.redis.publish(swarm_visible_to_channel(rid), raw_message)
            published += 1
        return published

    # --- Adjacency snapshot --------------------------------------------------------

    def adjacency_snapshot(self) -> Dict[str, list]:
        return in_range_pairs(
            self._positions,
            range_m=self.range_m,
            egs_link_range_m=self.egs_link_range_m,
        )

    def publish_adjacency(self) -> None:
        snap = self.adjacency_snapshot()
        self.redis.publish(MESH_ADJACENCY, json.dumps(snap))

    # --- CLI loop ------------------------------------------------------------------

    def run_forever(self, *, adjacency_hz: float = 1.0) -> None:
        """Blocking loop: psubscribe, dispatch, periodically publish adjacency."""
        pubsub = self.redis.pubsub()
        pubsub.psubscribe(_STATE_PATTERN, _BROADCAST_PATTERN)
        # drain initial subscribe acks
        for _ in range(2):
            pubsub.get_message(timeout=0.5)

        stop = threading.Event()
        period = 1.0 / adjacency_hz

        def _adjacency_thread():
            while not stop.is_set():
                try:
                    self.publish_adjacency()
                except Exception as e:  # pragma: no cover — defensive
                    print(f"[mesh] adjacency publish failed: {e}", flush=True)
                stop.wait(period)

        t = threading.Thread(target=_adjacency_thread, daemon=True)
        t.start()

        try:
            for msg in pubsub.listen():
                if msg.get("type") != "pmessage":
                    continue
                channel = msg["channel"].decode() if isinstance(msg["channel"], bytes) else msg["channel"]
                data = msg["data"]
                drone_id = drone_id_from_state_channel(channel)
                if drone_id is not None:
                    try:
                        payload = json.loads(data)
                    except Exception:
                        continue
                    self.ingest_state(payload)
                    continue
                drone_id = drone_id_from_broadcast_channel(channel)
                if drone_id is not None:
                    raw = data if isinstance(data, (bytes, bytearray)) else str(data).encode()
                    self.forward_broadcast(drone_id, bytes(raw))
                    continue
        except KeyboardInterrupt:
            print("[mesh_simulator] stopped via SIGINT", flush=True)
        finally:
            stop.set()
            t.join(timeout=2.0)
            pubsub.close()


def _parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mesh simulator — Euclidean range dropout for swarm broadcasts.")
    parser.add_argument("--redis-url", default=CONFIG.transport.redis_url)
    parser.add_argument("--range-meters", type=float, default=200.0)
    parser.add_argument("--egs-link-range-meters", type=float, default=500.0)
    parser.add_argument("--egs-lat", type=float, default=None, help="EGS latitude (defaults to omitted = no EGS)")
    parser.add_argument("--egs-lon", type=float, default=None)
    parser.add_argument("--adjacency-hz", type=float, default=1.0)
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = _parse_args(argv)
    redis_client = redis.Redis.from_url(args.redis_url)
    sim = MeshSimulator(
        redis_client,
        range_m=args.range_meters,
        egs_link_range_m=args.egs_link_range_meters,
    )
    if args.egs_lat is not None and args.egs_lon is not None:
        sim.set_egs_position(args.egs_lat, args.egs_lon)
    print(
        f"[mesh_simulator] range_m={args.range_meters} egs_link_range_m={args.egs_link_range_meters} "
        f"redis={args.redis_url}",
        flush=True,
    )
    sim.run_forever(adjacency_hz=args.adjacency_hz)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
