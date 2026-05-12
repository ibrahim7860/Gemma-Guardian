"""Synthetic xBD-shaped fixture + end-to-end prep pipeline smoke test.

Run with: uv run --extra ml python ml/data_prep/_synthetic_pipeline_smoke.py

Builds a minimal but xBD-format-correct fake dataset (3 disasters × 2 images × 4 buildings),
then runs crop_patches → split_dataset → format_for_gemma against it.

Catches: code path bugs (WKT parser, bbox math, JPEG write, manifest shape, JSONL schema)
before the real ~50GB xBD download. Pure Mac-CPU; no GPU needed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

DAMAGE_CLASSES = ["no-damage", "minor-damage", "major-damage", "destroyed"]


def make_synthetic_xbd(root: Path) -> None:
    """Build train/{images,labels} with 3 disasters × 2 images × 4 buildings each."""
    disasters = ["hurricane-florence", "mexico-earthquake", "joplin-tornado"]
    for split in ("train",):
        (root / split / "images").mkdir(parents=True, exist_ok=True)
        (root / split / "labels").mkdir(parents=True, exist_ok=True)
        for d in disasters:
            for img_idx in range(2):
                img_id = f"{d}_{img_idx:08d}_post_disaster"
                img = _make_image()
                cv2.imwrite(str(root / split / "images" / f"{img_id}.png"), img)
                label = _make_label(d)
                (root / split / "labels" / f"{img_id}.json").write_text(json.dumps(label))


def _make_image() -> np.ndarray:
    """1024x1024 RGB with some texture so resized patches aren't single-color."""
    img = np.random.randint(40, 220, (1024, 1024, 3), dtype=np.uint8)
    cv2.rectangle(img, (100, 100), (300, 300), (200, 50, 50), -1)
    cv2.rectangle(img, (500, 500), (700, 700), (50, 200, 50), -1)
    return img


def _make_label(disaster: str) -> dict:
    features = []
    boxes = [(100, 100, 300, 300), (500, 500, 700, 700), (400, 100, 480, 180), (820, 820, 980, 980)]
    for i, (x1, y1, x2, y2) in enumerate(boxes):
        wkt = f"POLYGON (({x1} {y1}, {x2} {y1}, {x2} {y2}, {x1} {y2}, {x1} {y1}))"
        features.append({
            "properties": {"subtype": DAMAGE_CLASSES[i % 4], "uid": f"b{i}"},
            "wkt": wkt,
        })
    return {"metadata": {"disaster": disaster}, "features": {"xy": features}}


def run(cmd: list[str], cwd: Path) -> None:
    print(f"\n$ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    print(r.stdout)
    if r.returncode != 0:
        print("STDERR:", r.stderr, file=sys.stderr)
        raise SystemExit(f"FAILED: {' '.join(cmd)}")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        xbd_root = tmp / "xbd_synth"
        patches_dir = tmp / "patches"
        manifest = tmp / "manifest.json"
        gemma_dir = tmp / "gemma_jsonl"

        print(f"[1/4] building synthetic xBD at {xbd_root}")
        make_synthetic_xbd(xbd_root)

        print("[2/4] crop_patches")
        run(["uv", "run", "--extra", "ml", "python", "-m", "ml.data_prep.crop_patches",
             "--xbd-root", str(xbd_root), "--out", str(patches_dir), "--splits", "train"], repo_root)
        n_patches = sum(1 for _ in patches_dir.rglob("*.jpg"))
        assert n_patches == 24, f"expected 24 patches (3 disasters × 2 imgs × 4 buildings), got {n_patches}"
        per_class = {c.name: len(list(c.glob("*.jpg"))) for c in patches_dir.iterdir() if c.is_dir()}
        print(f"  per-class counts: {per_class}")
        assert set(per_class) == set(DAMAGE_CLASSES), per_class

        print("[3/4] split_dataset")
        run(["uv", "run", "--extra", "ml", "python", "-m", "ml.data_prep.split_dataset",
             "--patches", str(patches_dir), "--out-manifest", str(manifest)], repo_root)
        m = json.loads(manifest.read_text())
        print(f"  splits: {m['counts']}")
        assert m["counts"]["train"] > 0 and m["counts"]["val"] > 0 and m["counts"]["test"] > 0, m["counts"]
        assert sum(m["counts"].values()) == 24, m["counts"]

        print("[4/4] format_for_gemma")
        run(["uv", "run", "--extra", "ml", "python", "-m", "ml.data_prep.format_for_gemma",
             "--manifest", str(manifest), "--out-dir", str(gemma_dir)], repo_root)
        for split in ("train", "val", "test"):
            jl = gemma_dir / f"{split}.jsonl"
            assert jl.exists(), jl
            lines = jl.read_text().splitlines()
            for line in lines:
                ex = json.loads(line)
                assert ex["messages"][0]["role"] == "user"
                assert ex["messages"][1]["role"] == "assistant"
                payload = json.loads(ex["messages"][1]["content"])
                assert payload["damage_class"] in {"no_damage", "minor_damage", "major_damage", "destroyed"}
            print(f"  {split}.jsonl: {len(lines)} examples OK")

    print("\nALL GREEN — prep pipeline runs end-to-end on synthetic data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
