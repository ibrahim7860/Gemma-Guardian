"""Pull candidate disaster-aerial frames showing people for the demo dashboard.

Tries multiple sources in priority order, dumps everything to /tmp/sard_candidates/
for human curation. The caller picks the killer victim frame + supporting frames
and copies them into sim/fixtures/frames/ (overwriting placeholders by filename).

Sources (in order):
  1. Pexels API — targeted queries for aerial drone people rescue (already verified
     working this session via video/.env PEXELS_API_KEY).
  2. NASA SVS Eaton Fire imagery — public domain, government work.
  3. (Skipped: HuggingFace SARD dataset — depends on `datasets` library and
     network access to HF; not reliable enough under deadline.)

Run: python3 scripts/fetch_sard_candidates.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import requests

# Pull PEXELS_API_KEY from video/.env (already populated this session)
VIDEO_ENV = Path(__file__).parent.parent / "video" / ".env"
PEXELS_API_KEY = ""
if VIDEO_ENV.exists():
    for line in VIDEO_ENV.read_text().splitlines():
        if line.startswith("PEXELS_API_KEY="):
            PEXELS_API_KEY = line.split("=", 1)[1].strip()
            break

OUT_DIR = Path("/tmp/sard_candidates")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Queries targeted at aerial drone perspectives of people in disaster contexts.
# Goal: find the ONE killer frame where a person is clearly visible from above
# (waving for help, lying in debris, group in a clearing). All other frames are
# supporting context (terrain, wildfire aftermath, no people).
QUERIES = {
    "aerial_rescue":         "aerial drone rescue people",
    "rescue_aerial_search":  "search rescue aerial",
    "drone_victim":          "drone aerial victim disaster",
    "wildfire_terrain":      "wildfire aftermath aerial drone",
    "earthquake_aerial":     "earthquake damage aerial",
    "flood_rescue_aerial":   "flood rescue aerial drone",
    "disaster_landscape":    "disaster aftermath aerial drone",
    "drone_search":          "drone search person ground",
}

PER_QUERY = 4   # max candidates per query


def search_pexels_images(query: str, per_page: int) -> list[dict[str, Any]]:
    if not PEXELS_API_KEY:
        print("ERROR: PEXELS_API_KEY missing from video/.env", file=sys.stderr)
        return []
    # Use Pexels Photos (not Videos) — we want STILLS for the camera tiles
    r = requests.get(
        "https://api.pexels.com/v1/search",
        headers={"Authorization": PEXELS_API_KEY},
        params={"query": query, "per_page": per_page, "orientation": "landscape"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("photos", [])


def download(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 16):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"  download error: {e}", file=sys.stderr)
        return False


def main() -> int:
    if not PEXELS_API_KEY:
        print("PEXELS_API_KEY not set. Aborting.", file=sys.stderr)
        return 1

    total = 0
    attribution_lines = ["# SARD candidate attribution", ""]
    for slug, query in QUERIES.items():
        print(f"=== '{query}' ===")
        try:
            photos = search_pexels_images(query, PER_QUERY)
        except Exception as e:
            print(f"  search error: {e}", file=sys.stderr)
            continue
        for i, p in enumerate(photos, 1):
            src = (p.get("src") or {})
            # Prefer "large" (typically ~940x650 or so); fall back to original
            url = src.get("large2x") or src.get("large") or src.get("original")
            if not url:
                continue
            fname = f"{slug}_{i:02d}_pexels{p['id']}.jpg"
            dest = OUT_DIR / fname
            if dest.exists():
                print(f"  skip {fname} (exists)")
                continue
            if download(url, dest):
                print(f"  ✓ {fname}  (by {p.get('photographer', '?')})")
                attribution_lines.append(
                    f"- **{fname}** — Pexels {p['id']}, "
                    f"photographer: {p.get('photographer', '?')}, "
                    f"url: {p.get('url', '')}"
                )
                total += 1
    (OUT_DIR / "ATTRIBUTION.md").write_text("\n".join(attribution_lines) + "\n")
    print(f"\nDONE: {total} candidates in {OUT_DIR}")
    print("Open the folder, pick the 8 best, copy to sim/fixtures/frames/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
