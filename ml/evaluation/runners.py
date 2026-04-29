"""Inference runners: base Gemma 4 (via Ollama) vs LoRA-tuned (via Unsloth FastVisionModel).

Both expose: runner(image: PIL.Image) -> {"damage_class": str, "confidence": float, "visual_evidence": str}

PLATFORM:
  - base_gemma_runner: requires only a running Ollama with gemma-4:e2b. Works on
    macOS (Metal), Linux/WSL2 (CUDA), or anywhere Ollama runs.
  - adapter_gemma_runner: requires Unsloth + CUDA. Run on WSL2+NVIDIA or a cloud
    GPU box; will not work on macOS (see docs/12 §Compute Path).
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
from typing import Callable

import httpx
from PIL import Image

CLASSIFY_PROMPT = "Classify the damage to the building in this image."
SYSTEM_PROMPT = (
    "You classify post-disaster building damage. Reply with JSON only, no prose. "
    "Schema: {\"damage_class\": one of [no_damage, minor_damage, major_damage, destroyed], "
    "\"confidence\": float in [0,1], \"visual_evidence\": short string}."
)

VALID_CLASSES = {"no_damage", "minor_damage", "major_damage", "destroyed"}


def _parse_json_envelope(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {"damage_class": "no_damage", "confidence": 0.0, "visual_evidence": ""}
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"damage_class": "no_damage", "confidence": 0.0, "visual_evidence": ""}
    if obj.get("damage_class") not in VALID_CLASSES:
        obj["damage_class"] = "no_damage"
        obj["confidence"] = 0.0
    return obj


def _img_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def base_gemma_runner(endpoint: str = "http://localhost:11434", model: str = "gemma-4:e2b") -> Callable:
    def run(img: Image.Image) -> dict:
        b64 = _img_to_b64(img)
        r = httpx.post(
            f"{endpoint}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": CLASSIFY_PROMPT, "images": [b64]},
                ],
                "stream": False,
                "options": {"temperature": 0.0},
            },
            timeout=60.0,
        )
        r.raise_for_status()
        return _parse_json_envelope(r.json().get("message", {}).get("content", ""))
    return run


def adapter_gemma_runner(adapter_dir: str | None = None) -> Callable:
    """Loads the LoRA adapter via Unsloth FastVisionModel; returns a callable."""
    adapter_dir = adapter_dir or os.environ.get("ADAPTER_DIR")
    if not adapter_dir:
        raise RuntimeError("set ADAPTER_DIR or pass adapter_dir=…")

    from unsloth import FastVisionModel  # type: ignore

    model, tokenizer = FastVisionModel.from_pretrained(
        model_name=adapter_dir,
        load_in_4bit=True,
    )
    FastVisionModel.for_inference(model)

    def run(img: Image.Image) -> dict:
        msgs = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image"},
                {"type": "text", "text": CLASSIFY_PROMPT},
            ]},
        ]
        inputs = tokenizer(msgs, images=[img], return_tensors="pt").to(model.device)
        out = model.generate(**inputs, max_new_tokens=128, temperature=0.0, do_sample=False)
        text = tokenizer.batch_decode(out, skip_special_tokens=True)[0]
        return _parse_json_envelope(text)
    return run
