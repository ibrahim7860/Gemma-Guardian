"""xBD per-building patch cropper.

For each post-disaster image:
  - Read its label JSON (polygon list with damage classes)
  - For each polygon, crop a padded bounding box from the post-disaster image
  - Resize to 224×224
  - Write to {out_dir}/{damage_class}/{disaster}_{img_id}_{building_id}.jpg

Output layout matches what format_for_gemma.py expects.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import shape
from tqdm import tqdm

DAMAGE_CLASSES = {"no-damage", "minor-damage", "major-damage", "destroyed"}
PADDING = 1.2
TARGET_SIZE = 224


def crop_split(split_dir: Path, out_dir: Path, target_size: int = TARGET_SIZE) -> int:
    images_dir = split_dir / "images"
    labels_dir = split_dir / "labels"
    if not images_dir.exists():
        print(f"missing images: {images_dir}")
        return 0

    n = 0
    label_files = sorted(labels_dir.glob("*_post_disaster.json"))
    for label_path in tqdm(label_files, desc=f"cropping {split_dir.name}"):
        img_path = images_dir / (label_path.stem + ".png")
        if not img_path.exists():
            continue
        img = cv2.imread(str(img_path))
        if img is None:
            continue
        try:
            meta = json.loads(label_path.read_text())
        except json.JSONDecodeError:
            continue

        disaster = meta.get("metadata", {}).get("disaster") or label_path.stem.split("_")[0]
        for feat in meta.get("features", {}).get("xy", []):
            props = feat.get("properties", {})
            damage = props.get("subtype")
            if damage not in DAMAGE_CLASSES:
                continue
            try:
                geom = shape(feat["wkt_geometry"]) if "wkt_geometry" in feat else None
            except Exception:
                geom = None
            poly_xy = feat.get("wkt") or feat.get("xy")
            try:
                bbox = _polygon_bbox(feat)
            except Exception:
                continue
            if bbox is None:
                continue
            x1, y1, x2, y2 = _pad_bbox(bbox, img.shape[:2], PADDING)
            patch = img[y1:y2, x1:x2]
            if patch.size == 0:
                continue
            patch = cv2.resize(patch, (target_size, target_size))
            class_dir = out_dir / damage
            class_dir.mkdir(parents=True, exist_ok=True)
            uid = props.get("uid", f"{n}")
            out_path = class_dir / f"{disaster}_{label_path.stem}_{uid}.jpg"
            cv2.imwrite(str(out_path), patch, [cv2.IMWRITE_JPEG_QUALITY, 90])
            n += 1
    return n


def _polygon_bbox(feature: dict) -> tuple[float, float, float, float] | None:
    wkt = feature.get("wkt")
    if wkt:
        try:
            geom = _wkt_to_polygon_coords(wkt)
            xs = [p[0] for p in geom]
            ys = [p[1] for p in geom]
            return min(xs), min(ys), max(xs), max(ys)
        except Exception:
            return None
    return None


def _wkt_to_polygon_coords(wkt: str) -> list[tuple[float, float]]:
    inside = wkt[wkt.index("((") + 2 : wkt.rindex("))")]
    pts = []
    for chunk in inside.split(","):
        x, y = chunk.strip().split(" ")
        pts.append((float(x), float(y)))
    return pts


def _pad_bbox(bbox, img_shape, pad_factor):
    h, w = img_shape
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    bw, bh = (x2 - x1) * pad_factor, (y2 - y1) * pad_factor
    x1 = max(0, int(cx - bw / 2))
    x2 = min(w, int(cx + bw / 2))
    y1 = max(0, int(cy - bh / 2))
    y2 = min(h, int(cy + bh / 2))
    return x1, y1, x2, y2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xbd-root", type=Path, required=True, help="Root where train/, tier3/, test/, hold/ live unpacked.")
    ap.add_argument("--out", type=Path, required=True, help="Output dir for class-organized patches.")
    ap.add_argument("--splits", nargs="+", default=["train", "tier3", "test", "hold"])
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    total = 0
    for split in args.splits:
        sdir = args.xbd_root / split
        if not sdir.exists():
            print(f"skipping missing split: {sdir}")
            continue
        total += crop_split(sdir, args.out)
    print(f"\ncropped {total} patches → {args.out}")


if __name__ == "__main__":
    main()
