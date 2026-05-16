"""GATE 3 — 4-bit native base + DoRA key fix (8GB safe)."""
import sys, json, tempfile, shutil
from pathlib import Path
import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
from safetensors.torch import load_file, save_file
from peft import PeftModel

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prompts import PROMPT, parse_model_output

MODEL_DIR = Path(__file__).parent
BASE = (MODEL_DIR / "BASE_MODEL.txt").read_text().strip()

print("1. Loading base model (4-bit native)...")
processor = AutoProcessor.from_pretrained(BASE)
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16
)
base_model = AutoModelForImageTextToText.from_pretrained(
    BASE, quantization_config=bnb_config, device_map="cuda"
)

print("2. Unwrapping ClippableLinear...")
n = 0
for name, mod in list(base_model.named_modules()):
    if type(mod).__name__ == "Gemma4ClippableLinear":
        parts = name.split(".")
        parent = base_model
        for p in parts[:-1]:
            parent = getattr(parent, p)
        setattr(parent, parts[-1], mod.linear)
        n += 1
print(f"   -> {n} layers unwrapped")

print("3. Fixing DoRA keys + loading adapter...")
tmpdir = Path(tempfile.mkdtemp())
for f in MODEL_DIR.iterdir():
    if f.is_file() and f.name != "adapter_model.safetensors":
        shutil.copy2(str(f), str(tmpdir))

sd = load_file(str(MODEL_DIR / "adapter_model.safetensors"))
fixed = {}
for k, v in sd.items():
    # Fix missing .weight suffixes on magnitude vectors
    if "lora_magnitude_vector" in k and not k.endswith(".weight"):
        k = k + ".weight"
    # Strip .linear from Unsloth's keys to match our unwrapped base model
    if ".linear.lora" in k:
        k = k.replace(".linear.lora", ".lora")
    fixed[k] = v

save_file(fixed, str(tmpdir / "adapter_model.safetensors"))

model = PeftModel.from_pretrained(base_model, str(tmpdir))
model.eval()
shutil.rmtree(str(tmpdir))

print("4. Running inference...")
img = Image.open(sys.argv[1]).convert("RGB")
msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": PROMPT}]}]
txt = processor.apply_chat_template(msgs, add_generation_prompt=True)
inputs = processor(text=txt, images=img, add_special_tokens=False, return_tensors="pt").to("cuda")

with torch.no_grad():
    out = model.generate(**inputs, max_new_tokens=128, do_sample=False)
raw = processor.batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0]
print(json.dumps(parse_model_output(raw), indent=2))