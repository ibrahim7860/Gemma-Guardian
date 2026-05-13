"""Evaluate base Gemma 4 E2B vs LoRA-tuned adapter on the xBD val/test split.

Outputs:
  - 4-class accuracy (no_damage / minor_damage / major_damage / destroyed)
  - Binary damaged-vs-not accuracy (no/minor vs major/destroyed)
  - Per-class F1
  - Confusion matrix
  - Mean confidence on correct vs incorrect predictions
  - GO/NO-GO decision per docs/12 Gate 3 (LoRA must beat base by ≥10 pp on 4-class)

Reads manifest.json (output of split_dataset.py) so the same val rows go
through both runners. Loads ONE model at a time (base then tuned) to keep VRAM
in budget on a 24 GB A5000.

Usage on Runpod (inside the Unsloth Docker pod):
    /opt/venv/bin/python ml/evaluation/eval_adapter.py \
        --manifest ml/data/manifest.json \
        --adapter ml/adapters/xbd_e2b_lora_v1_10k \
        --split val --limit 300 \
        --out ml/adapters/xbd_e2b_lora_v1_10k/eval_val.json
"""
from __future__ import annotations

import argparse
import gc
import json
import random
import time
from collections import Counter
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from ml.evaluation.runners import base_runner, tuned_runner

CLASSES = ["no_damage", "minor_damage", "major_damage", "destroyed"]
CLASS_TO_IDX = {c: i for i, c in enumerate(CLASSES)}
DAMAGED_INDICES = {2, 3}


def evaluate(make_runner: Callable, label: str, items: list[dict], repo_root: Path) -> dict:
    print(f"[{label}] loading model...")
    t0 = time.time()
    run = make_runner()
    print(f"[{label}] model loaded in {time.time() - t0:.1f}s")
    y_true, y_pred, conf = [], [], []
    last = time.time()
    for i, item in enumerate(items):
        true_label = item["label"].replace("-", "_")
        img_path = item["path"]
        full = (repo_root / img_path) if not Path(img_path).is_absolute() else Path(img_path)
        img = Image.open(full).convert("RGB")
        result = run(img)
        pred_label = result.get("damage_class", "no_damage")
        c = float(result.get("confidence", 0.0))
        y_true.append(CLASS_TO_IDX[true_label])
        y_pred.append(CLASS_TO_IDX.get(pred_label, -1))
        conf.append(c)
        if (i + 1) % 25 == 0 or i == len(items) - 1:
            now = time.time()
            print(f"  [{label}] {i + 1}/{len(items)} ({(now - last):.1f}s since last)")
            last = now
    return _metrics(y_true, y_pred, conf)


def _metrics(y_true: list[int], y_pred: list[int], conf: list[float]) -> dict:
    n = len(y_true)
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    binary_correct = sum(1 for t, p in zip(y_true, y_pred)
                         if (t in DAMAGED_INDICES) == (p in DAMAGED_INDICES))
    tp, fp, fn = Counter(), Counter(), Counter()
    for t, p in zip(y_true, y_pred):
        if t == p:
            tp[t] += 1
        else:
            fp[p] += 1
            fn[t] += 1
    f1 = {}
    for c, name in enumerate(CLASSES):
        prec = tp[c] / (tp[c] + fp[c]) if (tp[c] + fp[c]) else 0.0
        rec = tp[c] / (tp[c] + fn[c]) if (tp[c] + fn[c]) else 0.0
        f1[name] = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    cm = [[0] * len(CLASSES) for _ in CLASSES]
    for t, p in zip(y_true, y_pred):
        if 0 <= p < len(CLASSES):
            cm[t][p] += 1
    correct_conf = [c for t, p, c in zip(y_true, y_pred, conf) if t == p]
    wrong_conf = [c for t, p, c in zip(y_true, y_pred, conf) if t != p]
    return {
        "n": n,
        "accuracy_4class": correct / n if n else 0.0,
        "accuracy_binary": binary_correct / n if n else 0.0,
        "f1_per_class": f1,
        "confusion_matrix": cm,
        "mean_conf_correct": float(np.mean(correct_conf)) if correct_conf else 0.0,
        "mean_conf_wrong": float(np.mean(wrong_conf)) if wrong_conf else 0.0,
    }


def gate_decision(base: dict, tuned: dict, threshold_pp: float = 10.0) -> dict:
    delta_pp = (tuned["accuracy_4class"] - base["accuracy_4class"]) * 100.0
    return {
        "base_accuracy_4class": base["accuracy_4class"],
        "tuned_accuracy_4class": tuned["accuracy_4class"],
        "delta_pp": delta_pp,
        "threshold_pp": threshold_pp,
        "decision": "GO" if delta_pp >= threshold_pp else "NO_GO",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--adapter", type=Path, required=True, help="Dir containing lora_weights.pt + lora_config.json")
    ap.add_argument("--split", default="val", choices=["train", "val", "test"])
    ap.add_argument("--limit", type=int, default=300, help="Cap eval examples per runner.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text())
    items = manifest["splits"][args.split]
    random.seed(args.seed)
    random.shuffle(items)
    items = items[: args.limit]
    print(f"evaluating {len(items)} examples from split={args.split} (limit={args.limit})")

    # Class balance check on the eval slice
    class_counts = Counter(it["label"].replace("-", "_") for it in items)
    print(f"class balance: {dict(class_counts)}")

    repo_root = Path(__file__).resolve().parents[2]

    # Run base first, free VRAM, then tuned
    base_metrics = evaluate(lambda: base_runner(), "base", items, repo_root)
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:
        pass

    tuned_metrics = evaluate(lambda: tuned_runner(args.adapter), "tuned", items, repo_root)

    decision = gate_decision(base_metrics, tuned_metrics)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "split": args.split,
        "limit": args.limit,
        "seed": args.seed,
        "class_balance": dict(class_counts),
        "base": base_metrics,
        "tuned": tuned_metrics,
        "gate": decision,
    }, indent=2))
    print("\n=== Gate 3 Result ===")
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
