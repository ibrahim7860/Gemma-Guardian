"""Gate 3 behavioral test — 3/3 report_finding(victim) on placeholder_victim_01.jpg.

This is the test the team actually needs to make a deployment call on the LoRA
adapter, NOT the aggregate xBD damage-classification metric.

Sends the exact drone-agent system prompt + a filled-in user template + the
actual `sim/fixtures/frames/placeholder_victim_01.jpg` (FEMA Katrina destroyed-
school aerial) through base Gemma 4 E2B-it and through the LoRA-adapted model.
Repeats N times each (default 3, configurable) since base+seed≠greedy in
practice. Records the function call (or text output if parsing fails) and
classifies it as a `report_finding`, `report_finding(type="victim")`, or other.

Scope honesty: the v4_balanced LoRA was trained on xBD damage classification
per docs/12 §Scope line 58-70, NOT victim detection. docs/12 explicitly said
'we do NOT fine-tune for: Victim detection'. If this test shows the LoRA
does not improve `report_finding(type="victim")` rate on this specific frame,
that confirms the scope: the LoRA is doing what it was trained to do (damage
classification), not what the drone3 reliability TODO needs.

Run on the unsloth/unsloth Docker pod where the LoRA already lives:
    /opt/venv/bin/python -m ml.evaluation.behavioral_victim_test \
        --adapter ml/adapters/xbd_e2b_it_lora_v4_balanced \
        --frame sim/fixtures/frames/placeholder_victim_01.jpg \
        --runs 3 \
        --out ml/adapters/xbd_e2b_it_lora_v4_balanced/behavioral_victim_test.json
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Callable

import torch
from PIL import Image


def load_system_prompt(repo_root: Path) -> str:
    return (repo_root / "shared/prompts/drone_agent_system.md").read_text()


def render_user_message(repo_root: Path) -> str:
    """Fill the drone-agent user template with plausible drone3 standalone-window state."""
    template = (repo_root / "shared/prompts/drone_agent_user_template.md").read_text()
    return template.format(
        state_json=json.dumps({
            "drone_id": "drone3",
            "position": {"lat": 30.0167, "lon": -89.6500, "alt": 30.0},
            "battery_pct": 70.0,
            "heading_deg": 90.0,
            "current_task": "survey",
        }, indent=2),
        zone_bounds_json=json.dumps({
            "min_lat": 30.0, "max_lat": 30.05,
            "min_lon": -89.7, "max_lon": -89.6,
        }, indent=2),
        n_remaining=3,
        next_waypoint="(30.018, -89.645)",
        peer_broadcasts_summary="(none)",
        operator_commands_summary="(none)",
    )


def classify_output(text: str) -> dict:
    """Match text against report_finding patterns. Returns shape:
       {kind: "report_finding"|"other", type: str|None, raw_excerpt: str}
    """
    lower = text.lower()
    # Loose: a JSON-style block mentioning "report_finding" or "victim"
    json_blob = re.search(r"\{.*?\}", text, re.DOTALL)
    blob = json_blob.group(0) if json_blob else ""

    # Try to extract function call
    has_report_finding = "report_finding" in lower
    finding_type_match = re.search(r'"type"\s*:\s*"(\w+)"', text)
    finding_type = finding_type_match.group(1) if finding_type_match else None

    if has_report_finding:
        return {"kind": "report_finding", "type": finding_type, "raw_excerpt": text[:300]}

    # If JSON blob but no function call: check what action was taken
    for action in ["continue_mission", "mark_explored", "return_to_base", "request_assist"]:
        if action in lower:
            return {"kind": action, "type": None, "raw_excerpt": text[:300]}

    return {"kind": "unparseable", "type": None, "raw_excerpt": text[:300]}


def make_runner(model, processor, system_prompt: str, user_msg: str) -> Callable:
    messages = [
        {"role": "user", "content": [
            {"type": "image"},
            {"type": "text", "text": system_prompt + "\n\n" + user_msg},
        ]},
    ]
    text = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)

    def run(img: Image.Image) -> str:
        inputs = processor(text=[text], images=[[img]], return_tensors="pt", padding=False).to(model.device)
        with torch.inference_mode():
            out = model.generate(
                **inputs, max_new_tokens=256, do_sample=False,
                pad_token_id=processor.tokenizer.pad_token_id or processor.tokenizer.eos_token_id,
            )
        gen_ids = out[0][inputs["input_ids"].shape[1]:]
        return processor.tokenizer.decode(gen_ids, skip_special_tokens=True)
    return run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", type=Path, required=True)
    ap.add_argument("--frame", type=Path, required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    system_prompt = load_system_prompt(repo_root)
    user_msg = render_user_message(repo_root)
    img = Image.open(args.frame).convert("RGB")
    print(f"frame: {args.frame} ({img.size})")

    from unsloth import FastVisionModel

    results = {"frame": str(args.frame), "runs": args.runs, "base": [], "tuned": []}

    # --- Base ---
    print("=== BASE Gemma 4 E2B-it ===")
    model, tok = FastVisionModel.from_pretrained(model_name="unsloth/gemma-4-e2b-it", load_in_4bit=True)
    FastVisionModel.for_inference(model)
    run = make_runner(model, tok, system_prompt, user_msg)
    for i in range(args.runs):
        t0 = time.time()
        text = run(img)
        cls = classify_output(text)
        cls["wall_s"] = round(time.time() - t0, 1)
        results["base"].append(cls)
        print(f"  run {i+1}: kind={cls['kind']} type={cls['type']} ({cls['wall_s']}s)")
        print(f"    excerpt: {cls['raw_excerpt'][:200]!r}")

    # Free VRAM before loading tuned
    del model, tok, run
    import gc
    gc.collect()
    torch.cuda.empty_cache()

    # --- Tuned ---
    print("\n=== TUNED (LoRA from", args.adapter, ") ===")
    config = json.loads((args.adapter / "lora_config.json").read_text())
    lora_kwargs = config.get("lora_kwargs", {})
    model, tok = FastVisionModel.from_pretrained(model_name="unsloth/gemma-4-e2b-it", load_in_4bit=True)
    model = FastVisionModel.get_peft_model(model, **lora_kwargs)
    state = torch.load(args.adapter / "lora_weights.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(state, strict=False)
    FastVisionModel.for_inference(model)
    run = make_runner(model, tok, system_prompt, user_msg)
    for i in range(args.runs):
        t0 = time.time()
        text = run(img)
        cls = classify_output(text)
        cls["wall_s"] = round(time.time() - t0, 1)
        results["tuned"].append(cls)
        print(f"  run {i+1}: kind={cls['kind']} type={cls['type']} ({cls['wall_s']}s)")
        print(f"    excerpt: {cls['raw_excerpt'][:200]!r}")

    # Tallies
    def tally(rows, predicate):
        return sum(1 for r in rows if predicate(r))

    summary = {
        "base": {
            "report_finding_any_count": tally(results["base"], lambda r: r["kind"] == "report_finding"),
            "report_finding_victim_count": tally(results["base"], lambda r: r["kind"] == "report_finding" and r["type"] == "victim"),
            "report_finding_damaged_structure_count": tally(results["base"], lambda r: r["kind"] == "report_finding" and r["type"] == "damaged_structure"),
            "continue_mission_count": tally(results["base"], lambda r: r["kind"] == "continue_mission"),
            "unparseable_count": tally(results["base"], lambda r: r["kind"] == "unparseable"),
        },
        "tuned": {
            "report_finding_any_count": tally(results["tuned"], lambda r: r["kind"] == "report_finding"),
            "report_finding_victim_count": tally(results["tuned"], lambda r: r["kind"] == "report_finding" and r["type"] == "victim"),
            "report_finding_damaged_structure_count": tally(results["tuned"], lambda r: r["kind"] == "report_finding" and r["type"] == "damaged_structure"),
            "continue_mission_count": tally(results["tuned"], lambda r: r["kind"] == "continue_mission"),
            "unparseable_count": tally(results["tuned"], lambda r: r["kind"] == "unparseable"),
        },
        "gate_3_behavioral_call": "PASS" if tally(results["tuned"], lambda r: r["kind"] == "report_finding" and r["type"] == "victim") >= args.runs else "FAIL",
    }
    results["summary"] = summary

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2))
    print("\n=== Summary ===")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
