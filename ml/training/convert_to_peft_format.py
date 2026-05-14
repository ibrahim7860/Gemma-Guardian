"""Convert our custom `lora_weights.pt + lora_config.json` adapter into the
standard PEFT/HuggingFace format that can be `PeftModel.from_pretrained`'d.

Our training pipeline saved via `torch.save(state_dict, lora_weights.pt)`
because transformers 5.5.0's `save_pretrained` raises NotImplementedError on
core_model_loading.revert_weight_conversion for bnb_4bit-loaded models
(documented at length in docs/plans/2026-05-14-gate3-fine-tune-run-and-call.md).
The state dict is the actual PEFT state under standard naming
(`base_model.model.<...>.lora_A.weight`, `lora_B.weight`); we just bypass the
broken serialization path.

To produce a PEFT-format directory the team can load with
`PeftModel.from_pretrained(base_model, adapter_dir)`, we need:
  - `adapter_config.json` — the LoRA config in PEFT's format
  - `adapter_model.safetensors` — the state dict in safetensors

Run on the unsloth/unsloth Docker pod where the LoRA already lives:
    /opt/venv/bin/python -m ml.training.convert_to_peft_format \
        --adapter ml/adapters/xbd_e2b_it_lora_v4_balanced \
        --out    ml/adapters/xbd_e2b_it_lora_v4_balanced/peft_format/
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", type=Path, required=True, help="Dir with lora_weights.pt + lora_config.json")
    ap.add_argument("--out", type=Path, required=True, help="Output dir for PEFT format")
    args = ap.parse_args()

    import torch
    from safetensors.torch import save_file

    config = json.loads((args.adapter / "lora_config.json").read_text())
    lora_kwargs = config["lora_kwargs"]
    base_model = config["base_model"]

    # State dict from our custom torch.save
    state = torch.load(args.adapter / "lora_weights.pt", map_location="cpu", weights_only=True)
    print(f"loaded {len(state)} LoRA tensors ({sum(v.numel() for v in state.values()):,} params)")

    args.out.mkdir(parents=True, exist_ok=True)

    # adapter_config.json in PEFT's expected schema
    # See https://huggingface.co/docs/peft/main/en/package_reference/lora#peft.LoraConfig
    target_modules = lora_kwargs.get("target_modules", "all-linear")
    if isinstance(target_modules, str) and target_modules != "all-linear":
        target_modules = [target_modules]

    peft_config = {
        "peft_type": "LORA",
        "base_model_name_or_path": base_model,
        "task_type": "CAUSAL_LM",
        "r": lora_kwargs.get("r", 16),
        "lora_alpha": lora_kwargs.get("lora_alpha", 16),
        "lora_dropout": lora_kwargs.get("lora_dropout", 0.0),
        "bias": lora_kwargs.get("bias", "none"),
        "target_modules": target_modules,
        "use_rslora": lora_kwargs.get("use_rslora", False),
        "init_lora_weights": True,
        "fan_in_fan_out": False,
        "modules_to_save": None,
        "layers_to_transform": None,
        "layers_pattern": None,
        "rank_pattern": {},
        "alpha_pattern": {},
        "revision": None,
    }
    (args.out / "adapter_config.json").write_text(json.dumps(peft_config, indent=2))

    # safetensors uses contiguous CPU tensors of supported dtypes
    safe_state = {}
    for name, tensor in state.items():
        t = tensor.detach().cpu()
        if not t.is_contiguous():
            t = t.contiguous()
        safe_state[name] = t
    save_file(safe_state, str(args.out / "adapter_model.safetensors"))

    # Also write a README pointing at the training metadata
    readme = f"""# {args.adapter.name} — PEFT-format LoRA adapter

Standard PEFT / HuggingFace format. Load with:

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM  # or your loader
base = AutoModelForCausalLM.from_pretrained("{base_model}")
model = PeftModel.from_pretrained(base, "{args.out}")
```

For Unsloth / FastVisionModel:

```python
from unsloth import FastVisionModel
import torch
model, tok = FastVisionModel.from_pretrained(model_name="{base_model}", load_in_4bit=True)
model = FastVisionModel.get_peft_model(model, **lora_kwargs)  # see lora_config.json
# either use this PEFT dir via PeftModel, or load the raw torch.save
# state from ../lora_weights.pt with model.load_state_dict(strict=False)
```

## Training metadata

Full provenance in `../lora_config.json` and
`docs/plans/2026-05-14-gate3-fine-tune-run-and-call.md`.

- Base: `{base_model}`
- Hyperparameters: {json.dumps({k: v for k, v in lora_kwargs.items() if k != 'loftq_config'}, indent=2)}
- Training: {json.dumps(config.get('training_kwargs', {}), indent=2)}
"""
    (args.out / "README.md").write_text(readme)

    print(f"wrote {args.out}/adapter_config.json")
    print(f"wrote {args.out}/adapter_model.safetensors")
    print(f"wrote {args.out}/README.md")


if __name__ == "__main__":
    main()
