"""C2A victim-detection LoRA adapter inference for the drone agent.

Loads the Gemma 4 E2B base model with the C2A-trained PEFT adapter and
exposes a single ``analyze_frame(jpeg_bytes, drone_state)`` method that
returns either a ``report_finding`` function-call dict (victim detected)
or ``None`` (no victim → fall through to the Ollama reasoning path).

Design decisions
----------------
- **Singleton model load**: heavy imports + model init happen once in
  ``__init__``.  Each frame runs ``model.generate()`` on the already-
  loaded weights.
- **Env-var config**: ``C2A_ADAPTER_PATH`` overrides the default adapter
  directory.  Fallback is ``kaggle_work_c2a/adapter/`` relative to the
  repo root.
- **Graceful fallback**: callers should wrap construction in try/except
  and set the reference to ``None`` on failure.  The drone agent step
  loop treats ``None`` as "no adapter, use Ollama".
- **Prompt template**: uses the prompt the adapter was *trained against*
  (``PROMPT`` from the bundled ``prompts.py``), NOT the project's default
  drone-agent system prompt.  Swapping prompts would degrade adapter
  accuracy.

GATE 3 fixes baked in
---------------------
1. **ClippableLinear unwrap** — vanilla PEFT doesn't know about
   ``Gemma4ClippableLinear`` custom wrappers; we unwrap 232 layers to
   their inner ``nn.Linear`` before PEFT injection.
2. **DoRA magnitude-vector key rename** — Unsloth saves DoRA keys as
   ``…lora_magnitude_vector.default`` but vanilla PEFT expects
   ``…lora_magnitude_vector.default.weight``; we rename in a temp copy
   before ``PeftModel.from_pretrained``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]

# ---------- I/O contract (vendored from the adapter's prompts.py) ----------

FINDING_TYPES = ["victim", "none"]

C2A_PROMPT = (
    "You are analyzing an aerial image from a disaster-response drone. "
    "Determine if a human victim is visible. "
    "Respond with ONLY a JSON object in this exact format: "
    '{"finding_type": <one of: victim, none>, '
    '"confidence": <float between 0 and 1>, '
    '"visual_evidence": <brief description of what you see>}. '
    "Do not include any other text. Do not refuse. Do not hedge."
)

_JSON_BLOCK = re.compile(r"\{.*?\}", re.DOTALL)


def _extract_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def parse_c2a_output(raw: str) -> dict:
    """Parse the raw model output into a structured dict.

    Returns a dict with ``parse_status`` ("ok", "empty", "off_schema",
    "bad_class"), ``finding_type`` (str | None), ``confidence`` (float |
    None), ``visual_evidence`` (str | None), and ``raw`` (the original
    string).
    """
    if raw is None or not raw.strip():
        return {"parse_status": "empty", "finding_type": None, "raw": raw}
    obj = _extract_json(raw.strip())
    if obj is None:
        return {"parse_status": "off_schema", "finding_type": None, "raw": raw}
    ft = obj.get("finding_type")
    if ft not in FINDING_TYPES:
        return {"parse_status": "bad_class", "finding_type": None, "raw": raw}
    return {
        "parse_status": "ok",
        "finding_type": ft,
        "confidence": obj.get("confidence"),
        "visual_evidence": obj.get("visual_evidence"),
        "raw": raw,
    }


def translate_to_report_finding(
    c2a_result: dict,
    lat: float,
    lon: float,
    alt: float,
) -> Optional[dict]:
    """Convert a successful C2A output into a ``report_finding`` call dict.

    Returns ``None`` if the C2A result is not a parseable victim detection
    (parse_status != "ok" or finding_type != "victim").
    """
    if c2a_result.get("parse_status") != "ok":
        return None
    if c2a_result.get("finding_type") != "victim":
        return None
    confidence = c2a_result.get("confidence")
    if confidence is None or not isinstance(confidence, (int, float)):
        confidence = 0.7  # safe default
    confidence = max(0.0, min(1.0, float(confidence)))
    visual_evidence = c2a_result.get("visual_evidence") or "Human victim detected by C2A adapter."
    # Ensure visual_description meets the minLength=10 schema constraint.
    if len(visual_evidence) < 10:
        visual_evidence = visual_evidence + " " * (10 - len(visual_evidence))
    return {
        "function": "report_finding",
        "arguments": {
            "type": "victim",
            "severity": 4,
            "gps_lat": lat,
            "gps_lon": lon,
            "confidence": confidence,
            "visual_description": visual_evidence,
        },
    }


def resolve_adapter_path() -> Path:
    """Resolve the adapter directory from env var or fallback default."""
    env = os.environ.get("C2A_ADAPTER_PATH")
    if env:
        return Path(env)
    return _REPO_ROOT / "kaggle_work_c2a" / "adapter"


class C2AInferenceNode:
    """Loads the C2A LoRA adapter and runs victim-detection inference.

    Heavy dependencies (torch, transformers, peft, PIL) are imported lazily
    inside ``__init__`` so the module stays importable in unit-test lanes
    that don't have CUDA.
    """

    def __init__(self, adapter_path: Optional[Path] = None):
        import torch
        from PIL import Image as _PIL_Image  # noqa: F401 — validates import
        from transformers import (
            AutoModelForImageTextToText,
            AutoProcessor,
            BitsAndBytesConfig,
        )
        from peft import PeftModel
        from safetensors.torch import load_file, save_file

        self._adapter_path = Path(adapter_path) if adapter_path else resolve_adapter_path()
        if not self._adapter_path.exists():
            raise FileNotFoundError(
                f"C2A adapter not found at {self._adapter_path}. "
                f"Set C2A_ADAPTER_PATH env var or place the adapter at "
                f"kaggle_work_c2a/adapter/ relative to repo root."
            )

        base_model_file = self._adapter_path / "BASE_MODEL.txt"
        if base_model_file.exists():
            base_name = base_model_file.read_text().strip()
        else:
            base_name = "unsloth/gemma-4-E2B-it"

        logger.info("C2A: loading base model %s (4-bit)", base_name)
        self._processor = AutoProcessor.from_pretrained(base_name)
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
        )
        base_model = AutoModelForImageTextToText.from_pretrained(
            base_name,
            quantization_config=bnb_config,
            device_map="cuda",
        )

        # GATE 3 fix 1: unwrap ClippableLinear
        n_unwrapped = 0
        for name, mod in list(base_model.named_modules()):
            if type(mod).__name__ == "Gemma4ClippableLinear":
                parts = name.split(".")
                parent = base_model
                for p in parts[:-1]:
                    parent = getattr(parent, p)
                setattr(parent, parts[-1], mod.linear)
                n_unwrapped += 1
        logger.info("C2A: unwrapped %d ClippableLinear layers", n_unwrapped)

        # GATE 3 fix 2: DoRA key rename in a temp copy
        tmpdir = Path(tempfile.mkdtemp())
        try:
            for f in self._adapter_path.iterdir():
                if f.is_file() and f.name != "adapter_model.safetensors":
                    shutil.copy2(str(f), str(tmpdir))
            safetensors_path = self._adapter_path / "adapter_model.safetensors"
            if safetensors_path.exists():
                sd = load_file(str(safetensors_path))
                fixed: dict[str, Any] = {}
                for k, v in sd.items():
                    if "lora_magnitude_vector" in k and not k.endswith(".weight"):
                        k = k + ".weight"
                    if ".linear.lora" in k:
                        k = k.replace(".linear.lora", ".lora")
                    fixed[k] = v
                save_file(fixed, str(tmpdir / "adapter_model.safetensors"))
            else:
                logger.warning("C2A: adapter_model.safetensors not found, trying direct load")
                tmpdir = self._adapter_path  # fall back

            logger.info("C2A: loading PEFT adapter from %s", tmpdir)
            self._model = PeftModel.from_pretrained(base_model, str(tmpdir))
            self._model.eval()
        finally:
            # Clean up temp dir (but not if we fell back to the real adapter path)
            if tmpdir != self._adapter_path and tmpdir.exists():
                shutil.rmtree(str(tmpdir), ignore_errors=True)

        self._torch = torch
        logger.info("C2A: adapter loaded successfully from %s", self._adapter_path)

    def analyze_frame(
        self,
        frame_jpeg: bytes,
        lat: float,
        lon: float,
        alt: float,
    ) -> Optional[dict]:
        """Run victim detection on a JPEG frame.

        Returns a ``report_finding`` function-call dict if a victim is
        detected, or ``None`` if no victim (caller should fall through to
        the Ollama reasoning path for other finding types).
        """
        from PIL import Image

        img = Image.open(BytesIO(frame_jpeg)).convert("RGB")
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": C2A_PROMPT},
                ],
            }
        ]
        input_text = self._processor.apply_chat_template(
            messages, add_generation_prompt=True
        )
        inputs = self._processor(
            text=input_text,
            images=img,
            add_special_tokens=False,
            return_tensors="pt",
        ).to("cuda")

        with self._torch.no_grad():
            out = self._model.generate(
                **inputs, max_new_tokens=128, do_sample=False
            )
        raw = self._processor.batch_decode(
            out[:, inputs["input_ids"].shape[1]:],
            skip_special_tokens=True,
        )[0]

        logger.debug("C2A raw output: %s", raw)
        parsed = parse_c2a_output(raw)
        logger.info(
            "C2A: finding_type=%s confidence=%s parse_status=%s",
            parsed.get("finding_type"),
            parsed.get("confidence"),
            parsed.get("parse_status"),
        )

        return translate_to_report_finding(parsed, lat, lon, alt)
