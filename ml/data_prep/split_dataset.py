"""Train/val/test split — by disaster, not by random sample.

Per docs/12-fine-tuning-plan.md: split by disaster gives an honest measure of generalization.
The disaster name is the prefix of each patch filename (set in crop_patches.py).
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path


DEFAULT_TRAIN_DISASTERS = [
    "hurricane-florence", "hurricane-harvey", "hurricane-matthew",
    "midwest-flooding", "palu-tsunami", "santa-rosa-wildfire",
    "socal-fire", "guatemala-volcano",
]
DEFAULT_VAL_DISASTERS = ["mexico-earthquake", "moore-tornado"]
DEFAULT_TEST_DISASTERS = ["joplin-tornado", "lower-puna-volcano", "nepal-flooding"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patches", type=Path, required=True, help="Output dir from crop_patches.py.")
    ap.add_argument("--out-manifest", type=Path, required=True)
    ap.add_argument("--train-disasters", nargs="+", default=DEFAULT_TRAIN_DISASTERS)
    ap.add_argument("--val-disasters", nargs="+", default=DEFAULT_VAL_DISASTERS)
    ap.add_argument("--test-disasters", nargs="+", default=DEFAULT_TEST_DISASTERS)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)

    by_split = {"train": [], "val": [], "test": []}
    by_disaster = defaultdict(list)

    for class_dir in sorted(args.patches.iterdir()):
        if not class_dir.is_dir():
            continue
        cls = class_dir.name
        for jpg in class_dir.glob("*.jpg"):
            disaster = jpg.stem.split("_", 1)[0]
            by_disaster[disaster].append((str(jpg), cls))

    for disaster, items in by_disaster.items():
        if disaster in args.test_disasters:
            split = "test"
        elif disaster in args.val_disasters:
            split = "val"
        elif disaster in args.train_disasters:
            split = "train"
        else:
            split = "train"
        by_split[split].extend(items)

    for split in by_split:
        random.shuffle(by_split[split])

    args.out_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.out_manifest.write_text(json.dumps({
        "splits": {k: [{"path": p, "label": c} for p, c in v] for k, v in by_split.items()},
        "counts": {k: len(v) for k, v in by_split.items()},
        "disasters": {
            "train": args.train_disasters,
            "val": args.val_disasters,
            "test": args.test_disasters,
        },
    }, indent=2))
    print({k: len(v) for k, v in by_split.items()})


if __name__ == "__main__":
    main()
