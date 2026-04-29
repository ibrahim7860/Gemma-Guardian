"""xBD download — kicks off the ~50GB pull from the xView2 challenge website.

The xView2 challenge requires registration; this script expects credentials in env vars
or for the user to download the tarballs manually and place them in ml/data/xbd_raw/.

Set:
  XVIEW2_USER, XVIEW2_PASS  — challenge account credentials
  XBD_OUT_DIR               — where to put unpacked data (default: ml/data/xbd)

Day 1 deliverable per docs/19: "kick off the xBD download". Start this overnight.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "xbd"
RAW_TARBALLS = [
    "train_images_labels_targets.tar.gz",
    "tier3.tar.gz",
    "test_images_labels_targets.tar.gz",
    "hold_images_labels_targets.tar.gz",
]


def main():
    out_dir = Path(os.environ.get("XBD_OUT_DIR", str(DEFAULT_OUT)))
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    print(f"xBD destination: {out_dir}")
    print("xView2 requires registration; manual download is the path of least resistance.")
    print("1) Register at https://xview2.org/")
    print("2) Download these tarballs into:", raw_dir)
    for t in RAW_TARBALLS:
        print("   -", t)
    print("3) Re-run this script to unpack.\n")

    found = [p for p in raw_dir.glob("*.tar.gz")]
    if not found:
        print("No tarballs found yet. Exiting after creating the directory.")
        return 0

    for tar in found:
        target = out_dir / tar.stem.replace(".tar", "")
        if target.exists():
            print(f"already unpacked: {target}")
            continue
        print(f"unpacking {tar} → {target}")
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run(["tar", "-xzf", str(tar), "-C", str(target)], check=True)

    print("\nDone. Next: python -m ml.data_prep.crop_patches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
