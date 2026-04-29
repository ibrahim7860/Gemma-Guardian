"""Day-2 Unsloth verification gate (per docs/12-fine-tuning-plan.md).

Runs three checks:
  1. Unsloth imports
  2. Unsloth can load Gemma 4 E2B in 4-bit
  3. A toy multimodal LoRA forward+backward pass completes (one synthetic batch)

If any check fails, fine-tuning is abandoned. Print results and exit non-zero so CI can gate.
"""
from __future__ import annotations

import json
import sys
import time
import traceback


def check(name: str, fn):
    print(f"[{name}] running...")
    t0 = time.time()
    try:
        fn()
        print(f"[{name}] OK ({time.time() - t0:.1f}s)")
        return True
    except Exception as e:
        print(f"[{name}] FAIL: {e}")
        traceback.print_exc()
        return False


def import_check():
    import unsloth  # noqa: F401


def load_check():
    from unsloth import FastVisionModel  # type: ignore

    model, tokenizer = FastVisionModel.from_pretrained(
        model_name="unsloth/gemma-4-e2b",
        load_in_4bit=True,
    )
    assert model is not None and tokenizer is not None


def toy_lora_check():
    """One LoRA forward+backward on a synthetic patch — shape compatibility, no convergence claim."""
    import torch
    from unsloth import FastVisionModel  # type: ignore

    model, tokenizer = FastVisionModel.from_pretrained(
        model_name="unsloth/gemma-4-e2b",
        load_in_4bit=True,
    )
    model = FastVisionModel.get_peft_model(
        model,
        finetune_vision_layers=True,
        finetune_language_layers=False,
        finetune_attention_modules=True,
        finetune_mlp_modules=False,
        r=8, lora_alpha=16, lora_dropout=0.0,
        bias="none", random_state=0, use_rslora=False, loftq_config=None,
    )
    FastVisionModel.for_training(model)

    from PIL import Image
    img = Image.new("RGB", (224, 224), color=(128, 128, 128))
    msg = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": "Classify."}]}]
    inputs = tokenizer(msg, images=[img], return_tensors="pt").to(model.device)
    target = torch.zeros_like(inputs["input_ids"])
    out = model(**inputs, labels=target)
    out.loss.backward()


def main():
    results = {
        "import": check("import", import_check),
        "load_gemma_4_e2b_4bit": check("load_gemma_4_e2b_4bit", load_check),
        "toy_lora_forward_backward": check("toy_lora_forward_backward", toy_lora_check),
    }
    print("\n=== Day-2 Unsloth Verification ===")
    print(json.dumps(results, indent=2))
    if not all(results.values()):
        print("\nGATE FAILED — abandon fine-tuning per docs/12.")
        sys.exit(1)
    print("\nGATE PASSED — proceed with xBD fine-tuning workstream.")


if __name__ == "__main__":
    main()
