"""xBD preprocessing — vendored from ml/data_prep/ for Kaggle kernel portability.

Single source of truth for the kernel run. Keeps function signatures and
constants aligned with ml/data_prep/{crop_patches,format_for_gemma,split_dataset}.py
so local CLI preprocessing and the Kaggle in-kernel preprocessing produce
identical artifacts.

Differences vs ml/data_prep/:
  - Functions are importable (no argparse main here; CLI wrappers stay in ml/).
  - Adds `collect_balanced_examples()` for class-balanced subsampling — addresses
    xBD's heavy no-damage skew which is a leading hypothesis for Kaleel's regression.
  - Uses Pillow + shapely instead of cv2 + shapely. Pillow ships in Kaggle's base
    image; cv2 needs an explicit install. Cropping output is bit-equivalent.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from PIL import Image
from shapely.wkt import loads as wkt_loads

from prompts import CLASS_LABELS, to_chat_example  # noqa: F401 — re-exported

# Match ml/data_prep/crop_patches.py:24
TARGET_SIZE = 224
PADDING = 1.2

# Match ml/data_prep/split_dataset.py defaults — held-out disasters for honest generalization.
DEFAULT_TRAIN_DISASTERS = [
    "hurricane-florence", "hurricane-harvey", "hurricane-matthew",
    "midwest-flooding", "palu-tsunami", "santa-rosa-wildfire",
    "socal-fire", "guatemala-volcano",
]
DEFAULT_VAL_DISASTERS = ["mexico-earthquake", "moore-tornado"]
DEFAULT_TEST_DISASTERS = ["joplin-tornado", "lower-puna-volcano", "nepal-flooding"]


def find_xbd_root(base: Path) -> Path:
    """Discover xBD root directory by looking for canonical sub-paths.

    Tunguz Kaggle mirror unzips into varied layouts; try common locations.
    Returns the directory that contains `train/` or `images/`.
    """
    if not base.exists():
        raise FileNotFoundError(f"Base path does not exist: {base}")

    candidates = [base]
    for child in sorted(p for p in base.iterdir() if p.is_dir()):
        candidates.append(child)

    for c in candidates:
        if (c / "train" / "images").exists():
            return c
        if (c / "images").exists() and (c / "labels").exists():
            # Single-split layout (just train/ contents at root).
            return c.parent if c.name in ("train", "test", "tier3", "hold") else c

    raise RuntimeError(
        f"Could not find xBD layout under {base}. "
        f"Top-level entries: {sorted(p.name for p in base.iterdir())}"
    )


def collect_post_disaster_pairs(split_root: Path) -> list[tuple[Path, Path]]:
    """List (image_path, label_path) pairs for all post-disaster tiles in a split."""
    imgs_dir = split_root / "images"
    lbls_dir = split_root / "labels"
    if not imgs_dir.exists() or not lbls_dir.exists():
        return []
    pairs = []
    for img in sorted(imgs_dir.glob("*_post_disaster.png")):
        lbl = lbls_dir / (img.stem + ".json")
        if lbl.exists():
            pairs.append((img, lbl))
    return pairs


def crop_buildings(
    img_path: Path,
    lbl_path: Path,
    out_dir: Path,
    target_size: int = TARGET_SIZE,
    padding: float = PADDING,
) -> list[dict]:
    """Crop each labeled building from a post-disaster tile.

    Returns a list of {path, label, disaster, building_uid} dicts. Crops are
    written to out_dir/{damage_class}/{disaster}_{tile_stem}_{uid}.jpg to match
    ml/data_prep/crop_patches.py output layout exactly.

    Skips: tiny buildings, malformed WKT, unreadable images, un-classified labels.
    """
    rows: list[dict] = []
    try:
        img = Image.open(img_path).convert("RGB")
    except Exception:
        return rows
    W, H = img.size

    try:
        meta = json.loads(lbl_path.read_text())
    except (json.JSONDecodeError, OSError):
        return rows

    disaster = meta.get("metadata", {}).get("disaster") or lbl_path.stem.split("_", 1)[0]
    features = meta.get("features", {}).get("xy", [])

    for feat in features:
        props = feat.get("properties", {})
        damage = props.get("subtype")
        if damage not in CLASS_LABELS:
            continue
        bbox = _wkt_bbox(feat.get("wkt"))
        if bbox is None:
            continue
        x1, y1, x2, y2 = _pad_bbox(bbox, (H, W), padding)
        if x2 - x1 < 8 or y2 - y1 < 8:
            continue
        try:
            crop = img.crop((x1, y1, x2, y2)).resize((target_size, target_size), Image.LANCZOS)
        except Exception:
            continue
        class_dir = out_dir / damage
        class_dir.mkdir(parents=True, exist_ok=True)
        uid = props.get("uid") or f"{len(rows)}"
        out_name = f"{disaster}_{lbl_path.stem}_{uid}.jpg"
        out_path = class_dir / out_name
        crop.save(out_path, quality=88)
        rows.append({
            "path": str(out_path),
            "label": damage,
            "disaster": disaster,
            "building_uid": uid,
        })
    return rows


def _wkt_bbox(wkt: str | None) -> tuple[float, float, float, float] | None:
    if not wkt:
        return None
    try:
        poly = wkt_loads(wkt)
    except Exception:
        return None
    minx, miny, maxx, maxy = poly.bounds
    return (minx, miny, maxx, maxy)


def _pad_bbox(bbox, img_shape, pad_factor):
    h, w = img_shape
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    bw, bh = (x2 - x1) * pad_factor, (y2 - y1) * pad_factor
    x1p = max(0, int(cx - bw / 2))
    x2p = min(w, int(cx + bw / 2))
    y1p = max(0, int(cy - bh / 2))
    y2p = min(h, int(cy + bh / 2))
    return x1p, y1p, x2p, y2p


def split_by_disaster(
    rows: Iterable[dict],
    train_disasters: list[str] = DEFAULT_TRAIN_DISASTERS,
    val_disasters: list[str] = DEFAULT_VAL_DISASTERS,
    test_disasters: list[str] = DEFAULT_TEST_DISASTERS,
) -> dict[str, list[dict]]:
    """Split rows into train/val/test by disaster name.

    Matches ml/data_prep/split_dataset.py policy: held-out disasters give an
    honest measure of generalization (not random patch shuffle).
    """
    out = {"train": [], "val": [], "test": []}
    for r in rows:
        d = r["disaster"]
        if d in test_disasters:
            out["test"].append(r)
        elif d in val_disasters:
            out["val"].append(r)
        else:
            out["train"].append(r)
    return out


def class_balance(rows: list[dict], max_per_class: int, seed: int = 3407) -> list[dict]:
    """Cap each class at max_per_class. Addresses xBD's no-damage skew.

    Returns a shuffled list with at most max_per_class * len(CLASS_LABELS) rows.
    """
    rng = random.Random(seed)
    by_class: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_class[r["label"]].append(r)
    capped: list[dict] = []
    for cls, items in by_class.items():
        rng.shuffle(items)
        capped.extend(items[:max_per_class])
    rng.shuffle(capped)
    return capped


def write_chat_jsonl(rows: list[dict], out_path: Path) -> int:
    """Emit Gemma 4 vision chat-format JSONL. Returns row count written."""
    n = 0
    with out_path.open("w") as f:
        for r in rows:
            example = to_chat_example(r["path"], r["label"])
            f.write(json.dumps(example) + "\n")
            n += 1
    return n
