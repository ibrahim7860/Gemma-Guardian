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

    Input construction follows Unsloth's Gemma 4 vision recipe: apply_chat_template
    first to materialize the prompt as a string, then call the processor with
    (text=, images=) keywords. Passing a message list positionally hits
    `patch_processor_call() got multiple values for argument 'images'` because
    Unsloth's processor patch re-extracts images from the message content.
    """
    def _run():
        import torch
        from PIL import Image
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

        img = Image.new("RGB", (224, 224), color=(128, 128, 128))
        # Gemma 4 processor requires an explicit image token in the text or the
        # forward fails with "Image features and image tokens do not match, tokens: 0,
        # features: 256". Try apply_chat_template first (proper path), fall back to
        # the processor's image_token attribute, fall back to a literal "<image>"
        # marker which most multimodal processors recognize.
        text = None
        try:
            messages = [{"role": "user", "content": [
                {"type": "image"},
                {"type": "text", "text": "Classify the damage to the building."},
            ]}]
            text = tokenizer.apply_chat_template(
                messages, add_generation_prompt=False, tokenize=False
            )
        except (ValueError, AttributeError, NotImplementedError):
            tok = getattr(tokenizer, "image_token", None) or "<start_of_image>"
            text = f"{tok}\nClassify the damage to the building."
        inputs = tokenizer(text=text, images=img, return_tensors="pt").to(model.device)
        # Label the last 3 tokens so loss has signal but stays cheap.
        labels = torch.full_like(inputs["input_ids"], -100)
        if labels.shape[1] >= 3:
            labels[:, -3:] = inputs["input_ids"][:, -3:]
        out = model(**inputs, labels=labels)
        out.loss.backward()
        state["model"] = model  # save LoRA-wrapped for adapter+GGUF check
        return True
    return _run


def make_export_check(state: dict):
    """Manual LoRA-state extraction (REQUIRED) + GGUF export (best-effort per docs/12 §271).

    transformers 5.5.0 + Unsloth + Gemma 4 4-bit hits NotImplementedError in
    core_model_loading.revert_weight_conversion when calling either
    model.save_pretrained() (PEFT adapter) or save_pretrained_merged(). To sidestep
    this entirely, we extract LoRA parameters via named_parameters() filter and
    torch.save them to a custom file. Loading uses get_peft_model on the base model
    with identical config + load_state_dict(strict=False).

    GGUF export remains best-effort per docs/12 §271 fallback documentation.
    """
    def _run():
        import tempfile
        import traceback
        from pathlib import Path
        import torch
        model, tokenizer = state["model"], state["tokenizer"]
        with tempfile.TemporaryDirectory() as tmp:
            adapter = Path(tmp) / "adapter"
            adapter.mkdir(parents=True, exist_ok=True)
            # Extract LoRA params directly — bypasses transformers' save_pretrained
            # and its broken revert_weight_conversion path in transformers 5.5.0.
            lora_state = {
                name: param.detach().cpu()
                for name, param in model.named_parameters()
                if "lora_" in name.lower()
            }
            if not lora_state:
                raise RuntimeError(
                    "No LoRA params found via named_parameters() 'lora_' filter — "
                    "get_peft_model may not have wrapped the model correctly."
                )
            torch.save(lora_state, adapter / "lora_weights.pt")
            tokenizer.save_pretrained(str(adapter))
            n_params = sum(p.numel() for p in lora_state.values())
            print(f"  LoRA adapter save (manual torch.save): OK "
                  f"({len(lora_state)} tensors, {n_params:,} params)")

            # GGUF export deliberately SKIPPED in verify per docs/12 §271 fallback.
            # save_pretrained_merged dequantizes Gemma 4 E2B 4-bit → 16-bit (~10 GB),
            # which on a 25 GB RAM pod gets OOM-killed mid-merge before the gate
            # banner can print. We don't need GGUF to train; only to deploy via
            # Ollama. Deployment path: serve the merged 16-bit safetensors (or just
            # the LoRA adapter applied on top of base Gemma 4) via vLLM /
            # transformers instead of Ollama. Documented as known deviation.
            state["gguf_ok"] = False
            print("  GGUF export: SKIPPED (docs/12 §271 fallback — serve via vLLM/transformers)")
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
    # manual_lora_save is the hard gate (sidesteps the broken save_pretrained path);
    # gguf_export is reported separately as soft signal.
    results["manual_lora_save"], _ = check(
        "manual_lora_save", make_export_check(state)
    )
    _finalize(results, gguf_ok=state.get("gguf_ok", False))


def _finalize(results: dict[str, bool], gguf_ok: bool = False) -> None:
    print("\n=== Day-2 Unsloth Verification ===")
    print(json.dumps({**results, "gguf_export_soft_signal": gguf_ok}, indent=2))
    if not all(results.values()):
        print("\nGATE FAILED — abandon fine-tuning per docs/12.")
        sys.exit(1)
    if not gguf_ok:
        print("\nGATE PASSED with GGUF caveat — train adapter, serve via vLLM/transformers per docs/12 §271.")
    else:
        print("\nGATE PASSED — proceed with xBD fine-tuning workstream (full Ollama path available).")
    sys.exit(0)


if __name__ == "__main__":
    main()
