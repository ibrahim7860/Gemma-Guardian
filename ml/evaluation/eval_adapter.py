"""Evaluate base Gemma 4 E2B vs LoRA-tuned adapter on the xBD test split.

Outputs:
  - 4-class accuracy
  - Binary damaged-vs-not accuracy (no/minor vs major/destroyed)
  - Per-class F1
  - Confusion matrix
  - Mean confidence on correct vs incorrect predictions

The Day-10 GO/NO-GO gate (docs/17): adapter must beat base by ≥10pp on 4-class accuracy.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

CLASSES = ["no_damage", "minor_damage", "major_damage", "destroyed"]
CLASS_TO_IDX = {c: i for i, c in enumerate(CLASSES)}
DAMAGED_INDICES = {2, 3}


def predict_one(model_call, image_path: str) -> tuple[str, float]:
    """model_call(image) → (damage_class, confidence). Caller injects either base-Gemma or adapter-Gemma."""
    img = Image.open(image_path).convert("RGB")
    raw = model_call(img)
    return raw["damage_class"], float(raw.get("confidence", 0.0))


def evaluate(model_call, manifest_split: list[dict]) -> dict:
    y_true, y_pred, conf = [], [], []
    for item in manifest_split:
        true_label = item["label"].replace("-", "_")
        pred_label, c = predict_one(model_call, item["path"])
        y_true.append(CLASS_TO_IDX[true_label])
        y_pred.append(CLASS_TO_IDX.get(pred_label, -1))
        conf.append(c)
    return _metrics(y_true, y_pred, conf)


def _metrics(y_true: list[int], y_pred: list[int], conf: list[float]) -> dict:
    n = len(y_true)
    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    binary_correct = sum(1 for t, p in zip(y_true, y_pred) if (t in DAMAGED_INDICES) == (p in DAMAGED_INDICES))

    tp = Counter(); fp = Counter(); fn = Counter()
    for t, p in zip(y_true, y_pred):
        if t == p:
            tp[t] += 1
        else:
            fp[p] += 1
            fn[t] += 1

    f1 = {}
    for c, name in enumerate(CLASSES):
        p = tp[c] / (tp[c] + fp[c]) if (tp[c] + fp[c]) else 0.0
        r = tp[c] / (tp[c] + fn[c]) if (tp[c] + fn[c]) else 0.0
        f1[name] = 2 * p * r / (p + r) if (p + r) else 0.0

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
    ap.add_argument("--split", default="val", choices=["train", "val", "test"])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text())
    items = manifest["splits"][args.split]

    from .runners import base_gemma_runner, adapter_gemma_runner

    base_metrics = evaluate(base_gemma_runner(), items)
    tuned_metrics = evaluate(adapter_gemma_runner(), items)
    decision = gate_decision(base_metrics, tuned_metrics)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({
        "base": base_metrics,
        "tuned": tuned_metrics,
        "gate": decision,
    }, indent=2))
    print(json.dumps(decision, indent=2))


if __name__ == "__main__":
    main()
