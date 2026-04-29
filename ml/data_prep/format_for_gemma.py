"""Convert split manifest → multimodal chat examples ready for Unsloth's Gemma 4 trainer.

Each example is one assistant turn outputting a JSON envelope: damage_class, confidence, visual_evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

PROMPT = "Classify the damage to the building in this image."

CLASS_TO_LABEL = {
    "no-damage": "no_damage",
    "minor-damage": "minor_damage",
    "major-damage": "major_damage",
    "destroyed": "destroyed",
}


def to_example(image_path: str, label: str) -> dict:
    return {
        "messages": [
            {"role": "user", "content": [
                {"type": "image", "image": image_path},
                {"type": "text", "text": PROMPT},
            ]},
            {"role": "assistant", "content": json.dumps({
                "damage_class": CLASS_TO_LABEL[label],
                "confidence": 0.9,
                "visual_evidence": _placeholder_evidence(label),
            })},
        ]
    }


def _placeholder_evidence(label: str) -> str:
    return {
        "no-damage": "Building intact, walls and roof appear undamaged.",
        "minor-damage": "Visible cracks or broken windows, structure largely intact.",
        "major-damage": "Partial collapse, missing roof sections, structural deformation.",
        "destroyed": "Structure reduced to rubble, no recognizable form.",
    }[label]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text())

    for split, items in manifest["splits"].items():
        out_path = args.out_dir / f"{split}.jsonl"
        with out_path.open("w") as f:
            for item in items:
                f.write(json.dumps(to_example(item["path"], item["label"])) + "\n")
        print(f"{split}: {len(items)} → {out_path}")


if __name__ == "__main__":
    main()
