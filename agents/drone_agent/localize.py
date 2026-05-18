"""Gemma 4 native object-detection localizer.

This module asks the base Gemma 4 E2B vision model (via Ollama) to detect
humans in an aerial drone frame using Gemma's NATIVE object-detection
output format documented in Google's PaliGemma 2 / Gemma 3 capability
docs:

  Prompt: "detect person"
  Output: JSON array of {"box_2d": [y0, x0, y1, x1], "label": "person"}
          coordinates normalized to a 0-1024 grid.

We additionally use Ollama's structured-output ``format`` parameter
(documented at ollama.com/docs/structured-outputs) to force deterministic
JSON conformance, avoiding the "model returns empty content for freeform
prompts" trap we hit when we tried tool calling.

This serves two roles in the FieldAgent pipeline:

  1. **Localizer**: convert "victim found" to absolute pixel coords for
     the dashboard overlay.
  2. **Truth gate**: if Gemma returns zero person boxes, the C2A LoRA's
     "victim" classification was a false positive — caller should drop
     the finding. This filters out the C2A hallucinations that flood the
     dashboard with phantom victim findings on forest / flood / debris
     frames.

Coordinate conventions (be careful — easy to mix up):

  Gemma output : [y0, x0, y1, x1] in [0, 1024]  (y-first, top-left & bottom-right corners)
  Internal     : [x_norm, y_norm, w_norm, h_norm] in [0, 1]
  Dashboard    : [x_px, y_px, w_px, h_px] in [0, 1024]×[0, 576]  (1024×576 fixture frame)

Best-effort: any failure returns ``[]`` (empty list) so callers can treat
no-detection and inference-failure identically.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Optional

import httpx

# Strip ```json ... ``` fences Gemma sometimes wraps output in even with
# Ollama's ``format`` parameter set. Tested empirically on gemma4:e2b.
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

logger = logging.getLogger(__name__)

# Schema is what Ollama enforces via /api/chat ``format``. Top-level
# object is required (Ollama wraps top-level arrays inconsistently across
# model backends), so we nest the array under "detections".
_DETECT_SCHEMA = {
    "type": "object",
    "required": ["detections"],
    "properties": {
        "detections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["box_2d", "label"],
                "properties": {
                    "box_2d": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 1024},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                    "label": {"type": "string"},
                },
            },
        }
    },
}

_DETECT_PROMPT = (
    "Detect every human person visible in this aerial drone image. "
    "Return JSON with a 'detections' array. For each person, include "
    "'box_2d' as [y0, x0, y1, x1] normalized to a 0 to 1024 grid where "
    "(y0, x0) is the top-left corner and (y1, x1) is the bottom-right "
    "corner of the bounding box, and 'label' as a brief description. "
    "If no people are visible, return an empty detections array."
)


def _gemma_box_to_normalized(box: list[int]) -> Optional[list[float]]:
    """Convert Gemma's [y0, x0, y1, x1] @ 0-1024 -> [x, y, w, h] @ 0-1.

    Returns None for malformed boxes (wrong order, zero-area, out-of-range).
    """
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        y0, x0, y1, x1 = (int(v) for v in box)
    except (TypeError, ValueError):
        return None
    if not (0 <= x0 < x1 <= 1024 and 0 <= y0 < y1 <= 1024):
        return None
    x_n = x0 / 1024.0
    y_n = y0 / 1024.0
    w_n = (x1 - x0) / 1024.0
    h_n = (y1 - y0) / 1024.0
    if w_n <= 0 or h_n <= 0:
        return None
    return [x_n, y_n, w_n, h_n]


async def detect_persons(
    frame_jpeg: bytes,
    *,
    endpoint: str = "http://localhost:11434",
    model: str = "gemma4:e2b",
    timeout_s: float = 30.0,
) -> list[list[float]]:
    """Detect humans in the frame. Returns list of [x, y, w, h] normalized boxes.

    Empty list means either "no humans visible" or "inference failed" —
    callers treat both the same way (no model bbox → fall back to sidecar
    or drop the finding as a false positive, depending on context).
    """
    body = {
        "model": model,
        "stream": False,
        "messages": [
            {
                "role": "user",
                "content": _DETECT_PROMPT,
                "images": [base64.b64encode(frame_jpeg).decode("ascii")],
            },
        ],
        "format": _DETECT_SCHEMA,
        "options": {"temperature": 0.0, "num_predict": 256},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(f"{endpoint}/api/chat", json=body)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        logger.warning("detect_persons: HTTP error %s", exc)
        return []
    content = (data.get("message", {}) or {}).get("content") or ""
    if not content:
        return []
    # Strip ```json``` fences if present (Gemma does this sometimes).
    fence = _FENCE_RE.search(content)
    raw = fence.group(1) if fence else content.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("detect_persons: JSON parse fail; raw=%r", raw[:200])
        return []
    # Accept both shapes Gemma returns:
    #   (a) {"detections": [{"box_2d": [...], "label": "..."}]}  (our schema)
    #   (b) [{"box_2d": [...], "label": "..."}]                   (native)
    if isinstance(parsed, dict):
        detections = parsed.get("detections")
    elif isinstance(parsed, list):
        detections = parsed
    else:
        detections = None
    if not isinstance(detections, list):
        return []
    out: list[list[float]] = []
    for d in detections:
        if not isinstance(d, dict):
            continue
        norm = _gemma_box_to_normalized(d.get("box_2d"))
        if norm is not None:
            out.append(norm)
    return out


async def localize_victim(
    frame_jpeg: bytes,
    *,
    endpoint: str = "http://localhost:11434",
    model: str = "gemma4:e2b",
    timeout_s: float = 30.0,
) -> Optional[list[float]]:
    """Backward-compat alias: returns first person box or None.

    Prefer ``detect_persons`` directly for the truth-gate use case.
    """
    boxes = await detect_persons(
        frame_jpeg, endpoint=endpoint, model=model, timeout_s=timeout_s
    )
    return boxes[0] if boxes else None
