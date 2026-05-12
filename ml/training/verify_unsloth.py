"""Day-2 Unsloth verification gate (per docs/12-fine-tuning-plan.md).

Runs four checks under one shared model load so the gate fits comfortably on a 16 GB GPU:
  1. Unsloth imports
  2. Unsloth can load Gemma 4 E2B in 4-bit
  3. A toy multimodal LoRA forward+backward pass completes (one synthetic batch)
  4. GGUF export of the merged vision tower (docs/12 step 5)

The model is loaded exactly once; checks 2-4 share it. Earlier revisions called
FastVisionModel.from_pretrained three times in the same process and OOM'd via
accelerate's CPU-offload fallback on 16 GB cards.

If any check fails, fine-tuning is abandoned. Print results and exit non-zero so CI can gate.

COMPUTE PATH (docs/12 §Compute Path): Unsloth requires Linux + NVIDIA CUDA.
Run this on WSL2+NVIDIA (Path 1) or a rented cloud GPU instance (Path 2:
Lambda Labs / Paperspace / Runpod). Will not run on macOS or Windows-native.
"""
from __future__ import annotations

import json
import platform
import sys
import time
import traceback


if platform.system() == "Darwin":
    print("This script cannot run on macOS — Unsloth requires Linux + NVIDIA CUDA.")
    print("See docs/12-fine-tuning-plan.md §Compute Path for WSL2 / cloud GPU setup.")
    sys.exit(2)


def check(name: str, fn):
    print(f"[{name}] running...")
    t0 = time.time()
    try:
        result = fn()
        print(f"[{name}] OK ({time.time() - t0:.1f}s)")
        return True, result
    except Exception as e:
        print(f"[{name}] FAIL: {e}")
        traceback.print_exc()
        return False, None


def import_check():
    import unsloth  # noqa: F401
    return True


def make_load_check():
    """Loads Gemma 4 E2B in 4-bit and returns (model, tokenizer)."""
    def _load():
        from unsloth import FastVisionModel  # type: ignore
        model, tokenizer = FastVisionModel.from_pretrained(
            model_name="unsloth/gemma-4-e2b",
            load_in_4bit=True,
        )
        assert model is not None and tokenizer is not None
        return model, tokenizer
    return _load


def make_toy_lora_check(state: dict):
    """One LoRA forward+backward on a synthetic patch — shape compatibility, no convergence claim.

    Uses the same toggles as finetune_lora.py defaults (docs/12 §Training):
    vision_layers=False, language+attention+mlp=True, target_modules='all-linear', r=32.
    Mutates `state["model"]` so the GGUF check can reuse the LoRA-wrapped model.
    """
    def _run():
        import torch
        from unsloth import FastVisionModel  # type: ignore

        model, tokenizer = state["model"], state["tokenizer"]
        model = FastVisionModel.get_peft_model(
            model,
            finetune_vision_layers=False,
            finetune_language_layers=True,
            finetune_attention_modules=True,
            finetune_mlp_modules=True,
            target_modules="all-linear",
            r=32, lora_alpha=32, lora_dropout=0.0,
            bias="none", random_state=0, use_rslora=False, loftq_config=None,
            use_gradient_checkpointing="unsloth",
        )
        FastVisionModel.for_training(model)

        from PIL import Image
        img = Image.new("RGB", (224, 224), color=(128, 128, 128))
        msg = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": "Classify."}]}]
        inputs = tokenizer(msg, images=[img], return_tensors="pt").to(model.device)
        target = torch.zeros_like(inputs["input_ids"])
        out = model(**inputs, labels=target)
        out.loss.backward()
        state["model"] = model  # save LoRA-wrapped for GGUF check
        return True
    return _run


def make_gguf_export_check(state: dict):
    """docs/12 Day-2 step 5: GGUF export of merged vision tower must work end-to-end.

    Saves merged 16-bit safetensors, converts to GGUF q4_k_m, asserts files exist.
    Reuses the LoRA-wrapped model from toy_lora_check.
    """
    def _run():
        import tempfile
        from pathlib import Path
        model, tokenizer = state["model"], state["tokenizer"]
        with tempfile.TemporaryDirectory() as tmp:
            merged = Path(tmp) / "merged"
            gguf = Path(tmp) / "gguf"
            model.save_pretrained_merged(str(merged), tokenizer, save_method="merged_16bit")
            assert merged.exists() and any(merged.iterdir()), f"merged export empty: {merged}"
            model.save_pretrained_gguf(str(gguf), tokenizer, quantization_method="q4_k_m")
            gguf_files = list(gguf.rglob("*.gguf"))
            assert gguf_files, f"no .gguf produced under {gguf}; saw {list(gguf.rglob('*'))}"
        return True
    return _run


def main():
    state: dict = {}
    results: dict[str, bool] = {}

    results["import"], _ = check("import", import_check)
    if not results["import"]:
        _finalize(results)

    ok, loaded = check("load_gemma_4_e2b_4bit", make_load_check())
    results["load_gemma_4_e2b_4bit"] = ok
    if ok:
        state["model"], state["tokenizer"] = loaded
    else:
        _finalize(results)

    results["toy_lora_forward_backward"], _ = check(
        "toy_lora_forward_backward", make_toy_lora_check(state)
    )
    results["gguf_export_merged_vision"], _ = check(
        "gguf_export_merged_vision", make_gguf_export_check(state)
    )
    _finalize(results)


def _finalize(results: dict[str, bool]) -> None:
    print("\n=== Day-2 Unsloth Verification ===")
    print(json.dumps(results, indent=2))
    if not all(results.values()):
        print("\nGATE FAILED — abandon fine-tuning per docs/12.")
        sys.exit(1)
    print("\nGATE PASSED — proceed with xBD fine-tuning workstream.")
    sys.exit(0)


if __name__ == "__main__":
    main()
