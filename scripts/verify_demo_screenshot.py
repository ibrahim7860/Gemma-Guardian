"""Programmatic check that a captured dashboard PNG actually has the
FEMA aerial rendered in the map panel (vs falling back to grid-only).

Why this exists: the Flutter map_panel's Image.asset has an errorBuilder
that falls back to a grid-only painter when the aerial 404s. To a human
eyeballing a thumbnail, that fallback is indistinguishable from "aerial
loaded but is dark imagery." Captures that committed silently-broken
PNGs to docs_assets/ would survive eyeball QA. So we crop the map
region and check pixel variance — the aerial is photographic (high
stddev across channels), the grid fallback is near-uniform dark.

Usage:
  uv run python scripts/verify_demo_screenshot.py \\
    --png docs_assets/dashboard-finding-rendered.png \\
    --map-region 760,80,660,480 \\
    --min-stddev 28

Exit 0 = aerial pixels look photographic.
Exit 1 = looks like grid-only fallback (or threshold not met).

Calibration (measured 2026-05-08 on the 1440x673 dashboard layout, with
the map panel on the LEFT side at roughly x=20..710, y=70..370):
- FEMA aerial standalone: stddev ~42-48 per channel.
- Real captures with aerial rendered at 0.80 opacity (region 30,100,650,260):
  Beat 4 severed: stddev 39-46 / Beat 3 counts: stddev 33-38.
- Default --min-stddev 28 sits below the with-aerial floor by ~5pts and
  well above the expected no-aerial baseline (~12-20 at this region);
  if a real capture lands below 28, that is signal the aerial didn't load.
If the layout changes, re-measure on a known-good capture and adjust
both --map-region and --min-stddev.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageStat


def _parse_region(s: str) -> tuple[int, int, int, int]:
    parts = s.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            f"--map-region must be x,y,w,h (got {s!r})"
        )
    try:
        x, y, w, h = (int(p.strip()) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--map-region values must be integers (got {s!r})"
        )
    if w <= 0 or h <= 0:
        raise argparse.ArgumentTypeError(
            f"--map-region width/height must be positive (got w={w}, h={h})"
        )
    return x, y, w, h


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--png", type=Path, required=True, help="Path to captured dashboard PNG")
    parser.add_argument(
        "--map-region",
        type=_parse_region,
        default=(30, 100, 650, 260),
        help="Crop box as x,y,w,h. Default: 30,100,650,260 — covers the "
        "map panel area on the LEFT side of the 1440x673 dashboard. "
        "(The dashboard layout has Map+Findings stacked on the left, "
        "Drone Status+Command on the right — sampling the right side will "
        "miss the aerial entirely.)",
    )
    parser.add_argument(
        "--min-stddev",
        type=float,
        default=28.0,
        help="Minimum per-channel stddev to count as photographic (default: 28.0; "
        "see module docstring for calibration notes)",
    )
    args = parser.parse_args()

    if not args.png.exists():
        print(f"FAIL: {args.png} does not exist", file=sys.stderr)
        return 2

    with Image.open(args.png) as im:
        # Map panel content lives in RGB. Some captures may be RGBA.
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGB")
        x, y, w, h = args.map_region
        if x + w > im.width or y + h > im.height:
            print(
                f"FAIL: --map-region {x},{y},{w},{h} extends past image "
                f"bounds {im.width}x{im.height}",
                file=sys.stderr,
            )
            return 2
        crop = im.crop((x, y, x + w, y + h))
        if crop.mode == "RGBA":
            crop = crop.convert("RGB")
        stats = ImageStat.Stat(crop)
        # stats.stddev is per-channel: [R, G, B]
        stddevs = stats.stddev

    rounded = [round(s, 2) for s in stddevs]
    max_stddev = max(stddevs)

    print(f"png:        {args.png}")
    print(f"region:     x={x} y={y} w={w} h={h}")
    print(f"image dims: {im.width}x{im.height}")
    print(f"stddev RGB: {rounded}  (max={round(max_stddev, 2)})")
    print(f"threshold:  >= {args.min_stddev}")

    if max_stddev < args.min_stddev:
        print(
            f"FAIL: max channel stddev {round(max_stddev, 2)} < {args.min_stddev}. "
            f"Map region looks uniform — likely grid-only fallback (aerial 404'd or "
            f"errorBuilder fired). Check Playwright console for asset errors before "
            f"committing this PNG.",
            file=sys.stderr,
        )
        return 1

    print("OK: map region has photographic variance — aerial is rendered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
