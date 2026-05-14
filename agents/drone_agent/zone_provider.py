"""ZoneProvider — mutable holder for the active mission zone polygon.

Bootstrapped from the scenario YAML at construction (matches EGS's
`build_initial_egs_state` semantics: bbox-polygon of ALL drones' waypoints
outset by 50m). Overwritten on every `egs.state` message that carries a
valid `zone_polygon`, via `update_from_polygon`.

Lives next to the rest of the drone-agent module so its mutation timing is
tied to the runtime's asyncio loop. The math itself (scenario -> mission
polygon, polygon shape validation) lives in `shared.contracts.zones` so EGS
and drone agent share one source of truth.

The provider's `current()` returns `{"polygon": [[lat, lon], ...]}`, which
is the shape ValidationNode._within_zone expects on the polygon path
(see agents/drone_agent/validation.py).
"""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Dict, List

from shared.contracts.zones import (
    ZONE_BUFFER_M,
    mission_zone_polygon,
    polygon_to_bbox,
)
from sim.scenario import Scenario

logger = logging.getLogger(__name__)


class ZoneProvider:
    def __init__(self, scenario: Scenario, *, buffer_m: float = ZONE_BUFFER_M):
        self._polygon: List[List[float]] = mission_zone_polygon(scenario, buffer_m=buffer_m)

    def current(self) -> Dict[str, List[List[float]]]:
        """Return the live zone as `{"polygon": [[lat, lon], ...]}`.

        Polygon is deep-copied so consumers cannot mutate provider state.
        """
        return {"polygon": deepcopy(self._polygon)}

    def update_from_polygon(self, polygon: List[List[float]]) -> bool:
        """Overwrite the polygon from a new `zone_polygon`. Returns True on success.

        Malformed polygons (fewer than 3 points, wrong shape) are rejected
        with a warning and the existing polygon is preserved. Shape
        validation reuses `polygon_to_bbox`, which raises on the same
        rejection cases we want here.
        """
        try:
            polygon_to_bbox(polygon)
        except (ValueError, TypeError) as exc:
            logger.warning("ZoneProvider: rejecting malformed polygon: %s", exc)
            return False
        # Coerce to float on store so downstream `_point_in_polygon` numeric
        # comparisons never trip on str/int sneaking past schema validation.
        # polygon_to_bbox already validated each point parses as a float; this
        # reuses that guarantee at storage time.
        self._polygon = [[float(point[0]), float(point[1])] for point in polygon]
        return True
