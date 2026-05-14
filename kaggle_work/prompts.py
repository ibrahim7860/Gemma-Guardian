"""Single source of truth for the Gemma 4 vision damage-classifier I/O contract.

Imported by:
  - gemma4-xbd-vision-lora.py (the Kaggle kernel that trains + evals)
  - qasim_inference.py (bundled with the published Kaggle Model)
  - tests/test_preprocess.py (verifies parity with ml/data_prep/format_for_gemma.py)

The output schema MUST match ml/data_prep/format_for_gemma.py:21 (Kaleel's existing
training pipeline). Drone agent perception parses this exact envelope, so the
output cannot drift.
"""
from __future__ import annotations

import json
import re
from typing import Optional

CLASS_LABELS = ["no-damage", "minor-damage", "major-damage", "destroyed"]
CLASS_TO_LABEL = {
    "no-damage": "no_damage",
    "minor-damage": "minor_damage",
    "major-damage": "major_damage",
    "destroyed": "destroyed",
}
LABEL_TO_CLASS = {v: k for k, v in CLASS_TO_LABEL.items()}

PROMPT = "Classify the damage to the building in this image."

EVIDENCE_BY_CLASS = {
    "no-damage": "Building intact, walls and roof appear undamaged.",
    "minor-damage": "Visible cracks or broken windows, structure largely intact.",
    "major-damage": "Partial collapse, missing roof sections, structural deformation.",
    "destroyed": "Structure reduced to rubble, no recognizable form.",
}


def to_chat_example(image_path: str, label: str) -> dict:
    """Convert (image, damage class) into Unsloth/Gemma 4 vision chat-format row.

    Output schema matches ml/data_prep/format_for_gemma.to_example exactly.
    """
    if label not in CLASS_TO_LABEL:
        raise ValueError(f"Unknown damage class: {label!r}. Expected one of {list(CLASS_TO_LABEL)}")
    return {
        "messages": [
            {"role": "user", "content": [
                {"type": "image", "image": image_path},
                {"type": "text", "text": PROMPT},
            ]},
            {"role": "assistant", "content": json.dumps({
                "damage_class": CLASS_TO_LABEL[label],
                "confidence": 0.9,
                "visual_evidence": EVIDENCE_BY_CLASS[label],
            })},
        ]
    }


def parse_model_output(raw: str) -> dict:
    """Parse the model's emitted JSON envelope.

    Returns {"parse_status": ..., "damage_class": ..., "raw": ...}. parse_status
    is one of "ok", "off_schema", "empty", "bad_class". NEVER coerces silently.
    """
    if raw is None or not raw.strip():
        return {"parse_status": "empty", "damage_class": None, "raw": raw}

    text = raw.strip()
    obj = _extract_json(text)
    if obj is None:
        return {"parse_status": "off_schema", "damage_class": None, "raw": raw}

    dc = obj.get("damage_class")
    if dc not in LABEL_TO_CLASS:
        return {"parse_status": "bad_class", "damage_class": None, "raw": raw}

    return {
        "parse_status": "ok",
        "damage_class": LABEL_TO_CLASS[dc],
        "confidence": obj.get("confidence"),
        "visual_evidence": obj.get("visual_evidence"),
        "raw": raw,
    }


_JSON_BLOCK = re.compile(r"\{.*?\}", re.DOTALL)


def _extract_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
