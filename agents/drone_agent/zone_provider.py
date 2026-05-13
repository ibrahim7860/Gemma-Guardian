"""ZoneProvider — mutable holder for the active mission zone bbox.

Bootstrapped from the scenario YAML at construction (matches EGS's
`build_initial_egs_state` semantics: bbox of ALL drones' waypoints + 50m).
Overwritten on every `egs.state` message that carries a valid `zone_polygon`,
via `update_from_polygon`.

Lives next to the rest of the drone-agent module so its mutation timing is
tied to the runtime's asyncio loop. The math itself (polygon -> bbox,
scenario -> mission polygon) lives in `shared.contracts.zones` so EGS and
drone agent share one source of truth.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from shared.contracts.zones import (
    ZONE_BUFFER_M,
    mission_zone_bbox,
    polygon_to_bbox,
)
from sim.scenario import Scenario

logger = logging.getLogger(__name__)


class ZoneProvider:
    def __init__(self, scenario: Scenario, *, buffer_m: float = ZONE_BUFFER_M):
        self._bbox: Dict[str, float] = mission_zone_bbox(scenario, buffer_m=buffer_m)

    def current(self) -> Dict[str, float]:
        """Return the live bbox as `{lat_min, lat_max, lon_min, lon_max}`."""
        return dict(self._bbox)  # defensive copy; consumers must not mutate

    def update_from_polygon(self, polygon: List[List[float]]) -> bool:
        """Overwrite the bbox from a new `zone_polygon`. Returns True on success.

        Malformed polygons (fewer than 3 points, wrong shape) are rejected
        with a warning and the existing bbox is preserved.
        """
        try:
            new_bbox = polygon_to_bbox(polygon)
        except (ValueError, TypeError) as exc:
            logger.warning("ZoneProvider: rejecting malformed polygon: %s", exc)
            return False
        self._bbox = new_bbox
        return True
