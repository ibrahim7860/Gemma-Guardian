"""Tiny CLI helper: print a scenario's origin as ``lat,lon``.

Used by ``scripts/launch_swarm.sh`` to derive the EGS anchor position passed
into ``agents/mesh_simulator/main.py --egs-lat / --egs-lon`` rather than
parsing YAML in bash. Without this, the mesh simulator has no EGS in its
position cache and ``mesh.adjacency_matrix`` snapshots silently omit the
``egs`` node — so resilience-scenario EGS-link-drop tests can't observe the
drone↔EGS distance crossing ``mesh.egs_link_range_meters``.

Convention: scenarios anchor the EGS at their declared ``origin``. This
matches ``sim/scenarios/disaster_zone_v1.yaml`` and ``resilience_v1.yaml``,
and the runtime can be overridden with explicit ``--egs-lat / --egs-lon``
flags on the mesh simulator if a scenario ever needs a different anchor.

Output (stdout): a single line, e.g. ``34.0000,-118.5000``. No trailing
newline by design — bash captures it verbatim into a variable.

Usage:
    python3 sim/scenario_origin.py resilience_v1
    python3 sim/scenario_origin.py sim/scenarios/disaster_zone_v1.yaml
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sim.scenario import load_scenario


def _resolve_scenario_path(arg: str) -> Path:
    p = Path(arg)
    if p.exists():
        return p
    candidate = _PROJECT_ROOT / "sim" / "scenarios" / f"{arg}.yaml"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"scenario not found: {arg!r} (also looked at {candidate})")


def scenario_origin(scenario_arg: str) -> tuple[float, float]:
    scenario = load_scenario(_resolve_scenario_path(scenario_arg))
    return scenario.origin.lat, scenario.origin.lon


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if len(args) != 1:
        print("usage: python3 sim/scenario_origin.py <scenario>", file=sys.stderr)
        return 2
    try:
        lat, lon = scenario_origin(args[0])
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 1
    sys.stdout.write(f"{lat},{lon}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
