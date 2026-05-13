"""Inference runners: base Gemma 4 vs LoRA-tuned, both via Unsloth FastVisionModel.

Both runners expose:
    run(img: PIL.Image) -> {"damage_class": str, "confidence": float, "visual_evidence": str}

PLATFORM:
  - Both runners require Unsloth + CUDA. Run on WSL2+NVIDIA or a cloud GPU box
    (the unsloth/unsloth Docker image is what we test against). They will not
    work on macOS (see docs/12 §Compute Path).
  - We deliberately do NOT depend on Ollama for the base baseline because
    Ollama may not be present on the Unsloth Docker pod we're evaluating on.
    Both base and tuned use the same model-load path; the only difference is
    whether the LoRA adapter is applied. This keeps the comparison apples-to-apples.

Input formatting bypasses apply_chat_template (the Unsloth-bnb-4bit Gemma 4
processor we get back has chat_template=None in transformers 5.5.0). We hand-format
using Gemma's turn markers + the processor's image token (<|image|>).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

from PIL import Image

CLASSIFY_PROMPT = "Classify the damage to the building in this image."
VALID_CLASSES = {"no_damage", "minor_damage", "major_damage", "destroyed"}

USER_OPEN = "<start_of_turn>user\n"
MODEL_OPEN = "<start_of_turn>model\n"
TURN_CLOSE = "<end_of_turn>\n"


def _parse_json_envelope(text: str) -> dict:
    text = text.strip()
    match = re.search(r"\{.*?\}", text, re.DOTALL)
    if not match:
        return {"damage_class": "no_damage", "confidence": 0.0, "visual_evidence": "", "raw": text[:200]}
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"damage_class": "no_damage", "confidence": 0.0, "visual_evidence": "", "raw": text[:200]}
    if obj.get("damage_class") not in VALID_CLASSES:
        obj["damage_class"] = "no_damage"
        obj["confidence"] = 0.0
    return obj


def _build_prompt(image_token: str) -> str:
    return (
        f"{USER_OPEN}{image_token}\n{CLASSIFY_PROMPT}{TURN_CLOSE}{MODEL_OPEN}"
    )


def _make_runner(model, processor) -> Callable:
    image_token = getattr(processor, "image_token", None) or "<|image|>"
    prompt = _build_prompt(image_token)

    def run(img: Image.Image) -> dict:
        import torch
        inputs = processor(
            text=[prompt],
            images=[[img]],
            return_tensors="pt",
            padding=False,
        ).to(model.device)
        with torch.inference_mode():
            out = model.generate(
                **inputs,
                max_new_tokens=128,
                do_sample=False,
                temperature=1.0,  # ignored when do_sample=False
                pad_token_id=processor.tokenizer.pad_token_id or processor.tokenizer.eos_token_id,
            )
        # Decode only the newly-generated portion
        gen_ids = out[0][inputs["input_ids"].shape[1]:]
        text = processor.tokenizer.decode(gen_ids, skip_special_tokens=True)
        return _parse_json_envelope(text)
    return run


def base_runner(model_name: str = "unsloth/gemma-4-e2b") -> Callable:
    """Load base Gemma 4 E2B in 4-bit via Unsloth, no LoRA."""
    from unsloth import FastVisionModel  # type: ignore
    model, tokenizer = FastVisionModel.from_pretrained(model_name=model_name, load_in_4bit=True)
    FastVisionModel.for_inference(model)
    return _make_runner(model, tokenizer)


def tuned_runner(adapter_dir: str | Path, model_name: str = "unsloth/gemma-4-e2b") -> Callable:
    """Load base + apply LoRA from our custom lora_weights.pt + lora_config.json."""
    import torch
    from unsloth import FastVisionModel  # type: ignore

    adapter_dir = Path(adapter_dir)
    config_path = adapter_dir / "lora_config.json"
    weights_path = adapter_dir / "lora_weights.pt"
    if not weights_path.exists():
        raise FileNotFoundError(f"missing {weights_path}")

    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    lora_kwargs = config.get("lora_kwargs", {})

    model, tokenizer = FastVisionModel.from_pretrained(model_name=model_name, load_in_4bit=True)
    if lora_kwargs:
        model = FastVisionModel.get_peft_model(model, **lora_kwargs)
    else:
        # Fallback: same kwargs as training defaults
        model = FastVisionModel.get_peft_model(
            model,
            finetune_vision_layers=False,
            finetune_language_layers=True,
            finetune_attention_modules=True,
            finetune_mlp_modules=True,
            target_modules="all-linear",
            r=32, lora_alpha=32, lora_dropout=0.0,
            bias="none", random_state=42, use_rslora=False,
            use_gradient_checkpointing="unsloth",
        )

    state = torch.load(weights_path, map_location="cpu", weights_only=True)
    missing, unexpected = model.load_state_dict(state, strict=False)
    if unexpected:
        print(f"[tuned_runner] WARN: {len(unexpected)} unexpected keys (first: {unexpected[:3]})")
    print(f"[tuned_runner] loaded {len(state)} LoRA tensors "
          f"({sum(v.numel() for v in state.values()):,} params)")
    FastVisionModel.for_inference(model)
    return _make_runner(model, tokenizer)
