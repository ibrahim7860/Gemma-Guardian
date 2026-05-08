"""Mirror sim/fixtures/base_images/ → frontend/flutter_dashboard/assets/base_images/ byte-for-byte.

Flutter's asset bundler can't load files outside the Flutter project root,
so the static aerials live in two places. This script enforces that the
two copies are byte-identical so neither side silently drifts. CI runs the
matching `scripts/tests/test_flutter_asset_sync.py` lockdown — this script
is the human-side fixer when the lockdown fails.

Usage:
    uv run python -m scripts.sync_flutter_base_images           # copy + verify
    uv run python -m scripts.sync_flutter_base_images --check   # exit 1 if drift
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIR = REPO_ROOT / "sim" / "fixtures" / "base_images"
TARGET_DIR = REPO_ROOT / "frontend" / "flutter_dashboard" / "assets" / "base_images"

# Filenames the Flutter side actually loads via Image.asset (declared in
# pubspec.yaml). If a new aerial is added to sim/fixtures/base_images/ but
# isn't on this list, it's a sim-only asset and the sync skips it.
TRACKED = ("disaster_zone_v1_base.jpg",)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify only; exit 1 on drift instead of copying.",
    )
    args = parser.parse_args()

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    drift: list[str] = []
    for name in TRACKED:
        src = SOURCE_DIR / name
        dst = TARGET_DIR / name
        if not src.exists():
            print(f"ERROR: source missing: {src}", file=sys.stderr)
            return 1
        if dst.exists() and _sha256(src) == _sha256(dst):
            print(f"OK   {name}  ({_sha256(src)[:12]}…)")
            continue
        if args.check:
            drift.append(name)
            print(f"DRIFT {name}  src={_sha256(src)[:12]}… dst={'(missing)' if not dst.exists() else _sha256(dst)[:12] + '…'}", file=sys.stderr)
        else:
            shutil.copyfile(src, dst)
            print(f"COPY {name}  → {dst.relative_to(REPO_ROOT)}")
    if drift:
        print(f"\n{len(drift)} asset(s) out of sync; run without --check to fix.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
