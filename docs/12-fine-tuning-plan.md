# 12 — Fine-Tuning Plan

## Why We Fine-Tune

The hackathon's published analysis stated explicitly: *"You can improve performance for a specific task rather than relying only on generic prompting. You can show the model being used in realistic resource-constrained settings. That is where your project starts to look serious. This is where a lot of people will lose."*

Fine-tuning is the credibility play. It earns:
- Eligibility for the **Unsloth special prize**
- A measurable accuracy improvement over base Gemma 4
- A real evaluation section in the writeup with falsifiable claims

But fine-tuning is also the highest-risk workstream in the project. We isolate it as a clean go/no-go workflow.

## Ownership

**Person 2 owns fine-tuning end-to-end** alongside the drone agent. This is deliberate: the same person writes the vision prompts, defines what "good" output looks like, and integrates the adapter back into the agent runtime. There is no handoff between fine-tuner and agent author — they are the same person, with no shared support resource.

**Person 5 is paired exclusively with Person 1 on the simulation workstream and is not available to support fine-tuning.** This is a strategic choice: Person 1's simulation stack is the higher-risk seat on the project, and we double-up there rather than spread Person 5 thin across roles. Person 2 carries fine-tuning solo.

Because Person 2 has no helper, the Day-2 Unsloth verification gate and the Day-10 GO/NO-GO gate are non-negotiable. If fine-tuning starts pulling Person 2 off the agent loop, **the team invokes NO-GO early rather than reassigning help.** Sunk cost is not a reason to keep the FT workstream alive past the gate.

## Compute Path

Unsloth requires Linux + an NVIDIA CUDA GPU. The team has Mac Silicon and Windows machines (no native Ubuntu). Person 2 picks one of these compute paths:

### Path 1: WSL2 on a Windows + NVIDIA machine (preferred if available)

If anyone on the team has a Windows machine with an NVIDIA RTX 3060 or better, Person 2 (or that team member, if it's not Person 2's own laptop) runs Unsloth inside WSL2 with NVIDIA CUDA passthrough. This works in 2026 with no fuss — install the latest NVIDIA Windows driver, then `nvidia-smi` works inside WSL2 immediately.

Pros: free, fast iteration, no cloud cost.
Cons: requires the right hardware on the team.

### Path 2: Rented cloud GPU (default fallback)

Rent an A10 or A100 instance from Lambda Labs, Paperspace, or Runpod. Person 2 spins it up for training runs only, shuts it down between runs.

- **Lambda Labs A10:** ~$0.75/hr — sufficient for LoRA on Gemma 4 E2B
- **Paperspace A4000 / A5000:** ~$0.51–$0.76/hr
- **Runpod RTX A4000:** ~$0.34/hr (cheapest spot pricing)

Total budget for the 10-day FT window: **~$50–150** if Person 2 is disciplined about shutting down idle instances. Set a billing alert at $100.

Pros: works regardless of team hardware; A100 is faster than any laptop GPU.
Cons: requires credit card setup; data transfer time; risk of forgetting to shut down.

### Workflow regardless of path

1. xBD download and preprocessing happens on Person 2's local machine (Mac or Windows). Output is the cleaned dataset.
2. Cleaned dataset uploads to the GPU machine (rsync to WSL2, or scp to cloud instance).
3. Training runs on the GPU machine.
4. Adapter weights (~MB scale) download back to Person 2's local machine.
5. Adapter integrates into the drone agent's Ollama instance, which can be local or running on the demo box.

The Day-2 Unsloth verification gate happens on whichever path Person 2 chooses. If neither path works by end of Day 2, fine-tuning is abandoned per the existing NO-GO criteria.

## Scope

**Task:** building damage classification from aerial imagery.

**Input:** a cropped patch of an aerial image showing one building or a small group of buildings.

**Output:** damage class — `no_damage | minor_damage | major_damage | destroyed` — plus a confidence and a short visual justification.

This is exactly what the xView2 / xBD challenge was built for. It's the cleanest, best-documented disaster classification task available, and the labels are directly compatible with our `report_finding` function call's `damaged_structure` type with severity levels 1-4.

**We do NOT fine-tune for:**
- Victim detection (visually ambiguous, sim-to-real gap is huge)
- Fire/smoke detection (Gemma 4 base is reasonably good already, and fire visuals in Gazebo are unrealistic)
- Multi-task learning (too much risk in 20 days)

Pick one. Damage classification. That's it.

## Dataset: xBD

**xBD** (xView Building Damage):
- 850,736 annotated buildings
- 45,362 km² of imagery
- Pre/post-disaster pairs from 19 disasters (wildfires, hurricanes, earthquakes, floods, tornadoes, volcanic eruptions, tsunamis)
- Joint Damage Scale labels: no_damage | minor_damage | major_damage | destroyed
- 0.3-0.5m resolution from WorldView-3 satellite
- 22,068 image pairs at 1024×1024 resolution
- Apache-style permissive license (CC) for use in research

**Download:** xView2 challenge website (registration required, free).

**Baseline performance to beat:**
- xView2 challenge baseline localization F1: ~0.27
- xView2 challenge baseline damage F1: ~0.10
- Top entries: ~0.74 F1 damage classification

For our purposes we don't need to match top entries. A modest improvement over base Gemma 4 (e.g., +10 percentage points on damage classification accuracy) is sufficient for the Unsloth prize and a credible writeup.

## Approach: LoRA on Vision Adapter via Unsloth

**Why LoRA:**
- Updates only ~1-5% of parameters
- Trains in hours, not days, on a single consumer GPU
- Adapter file is small (~100-500MB)
- Can be turned on/off at inference time

**Why Unsloth:**
- Designed specifically for this workflow
- Required to qualify for the Unsloth special prize
- Has been validated on Gemma family models

**What we fine-tune:**
- The vision adapter / vision tower portion of Gemma 4 E2B (the smaller variant; we want this on drones)
- Optionally fine-tune the language head with task-specific output formatting
- Do NOT fine-tune the full LLM weights

## Day-1 Verification (Critical)

**Person 2 must verify by end of Day 2:**

1. Unsloth installs cleanly on the dev machine
2. Unsloth supports Gemma 4 vision LoRA fine-tuning (not just text)
3. A hello-world fine-tuning run completes successfully on a tiny dataset

If any of these fails, **fine-tuning is abandoned**. The fallback path is base Gemma 4 + heavy prompt engineering, with an honest writeup section explaining the attempt.

This Day-2 gate is non-negotiable. Fine-tuning is the high-risk workstream; we discover failure early or not at all.

## Data Preparation

xBD comes as 1024×1024 image pairs. We need per-building patches with damage labels.

### Step 1: Download and unpack xBD

~50 GB total. Start the download Day 1.

```
xbd/
├── train/
│   ├── images/
│   ├── labels/  # JSON polygons with damage classes
│   └── targets/
├── tier3/  # additional training data
├── test/
└── hold/
```

### Step 2: Crop per-building patches

For each building polygon:
1. Compute bounding box with padding (e.g., 1.2× the polygon extent)
2. Crop the post-disaster image to that box
3. Resize to 224×224 (or whatever Gemma 4's vision adapter prefers)
4. Save with the damage label

Output: ~500K patches with labels.

### Step 3: Create train/val/test splits

- Train: 80% (use for LoRA training)
- Val: 10% (use for hyperparameter tuning, early stopping)
- Test: 10% (use ONLY for the writeup's final evaluation, do not touch during development)

Split by **disaster** (not by random sample) — this gives us a more honest evaluation of generalization. Use earthquakes for test if you train on hurricanes, etc.

### Step 4: Format for Gemma 4

Gemma 4 vision input is multimodal: image + text. Each training example:

```json
{
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "image", "image": "<patch>"},
        {"type": "text", "text": "Classify the damage to the building in this image."}
      ]
    },
    {
      "role": "assistant",
      "content": "{\"damage_class\": \"major_damage\", \"confidence\": 0.85, \"visual_evidence\": \"Roof partially collapsed, walls tilted, debris around structure.\"}"
    }
  ]
}
```

The output is JSON to encourage structured generation in production.

### Step 5: Synthetic Gazebo augmentation (optional, Week 2)

Render 200-500 patches from our Gazebo disaster scene with known damage labels (since we control the scene). Add to training set as 5-10% augmentation. This addresses the sim-to-real gap.

## Training

**Hardware:** RTX 4090 (24 GB VRAM) sufficient. Lower-end cards may need batch size adjustments.

**Hyperparameters (starting point, iterate from here):**
- LoRA rank: 16
- LoRA alpha: 32
- Learning rate: 2e-4 with cosine schedule
- Batch size: 4 (with gradient accumulation if VRAM tight)
- Epochs: 3-5
- Mixed precision: bf16

**Tracking:**
- Validation accuracy per epoch
- Per-class F1 (no_damage / minor / major / destroyed)
- Confusion matrix
- Sample predictions on held-out images

Use Weights & Biases (free) or just a CSV log + matplotlib.

**Stop criteria:**
- Validation accuracy plateaus for 2 epochs
- Validation accuracy decreases for 2 consecutive epochs (overfitting)
- 7 days of wall-clock time spent (hard cap)

## Evaluation

**Metrics:**
1. **Damage classification accuracy** (4-class, vs 25% random)
2. **Binary damaged-vs-not accuracy** (combine major + destroyed vs no + minor)
3. **Per-class F1 scores**
4. **Mean confidence on correct vs incorrect predictions** (calibration check)

**Baseline comparison:**
- Base Gemma 4 E2B with structured prompt: report this number
- Fine-tuned Gemma 4 E2B with LoRA adapter: report this number
- Reference baseline from xView2 papers: cite

**Realistic expectations:**
- Base Gemma 4 with prompt engineering: 40-55% accuracy on 4-class
- Fine-tuned Gemma 4 LoRA: 60-75% accuracy on 4-class
- Binary damaged-vs-not: 80-90%

These are honest targets. We don't claim state-of-the-art.

## The Day-10 Go/No-Go Gate (May 8)

Person 2 reports to the team:

**If the fine-tuned adapter beats base Gemma 4 by ≥10 percentage points on validation accuracy:**
- GO. Integrate the adapter into the drone agent (Person 2 owns this since fine-tuning and the agent live in the same seat).
- Update the writeup to include the fine-tuning section.
- Compete for the Unsloth special prize.

**If it doesn't beat base by ≥10 points, OR fine-tuning never converged:**
- NO-GO. Drop the adapter from the demo.
- Use base Gemma 4 with structured prompts in the demo.
- Writeup includes an honest "we attempted fine-tuning but did not achieve sufficient improvement in the time available" section.
- We do NOT pretend it worked.

The team's plan is the same in both cases — only the writeup changes and the special-prize claim is adjusted.

## Integration with the Drone Agent

If GO:

1. Adapter file is loaded at startup of the drone agent's Ollama instance
2. The vision component of Gemma 4 E2B uses the adapter for damage classification
3. The drone agent's Reasoning prompt mentions the model's specific training: "Your vision model has been fine-tuned for building damage classification."
4. Damage findings are tagged with the fine-tuned classification source for the writeup's evaluation

If NO-GO:
- Skip the adapter, use base Gemma 4
- Damage classifications come from base model's prompted reasoning
- Demo doesn't break; just less impressive accuracy

## What Could Go Wrong

| Failure | Mitigation |
|---|---|
| Unsloth doesn't support Gemma 4 vision LoRA | Day-2 verification; abandon if confirmed |
| Training never converges | Time-box to 7 days, fall back to base |
| Adapter is worse on Gazebo imagery than xBD | Add synthetic augmentation; prefer base for demo, fine-tuned for writeup numbers |
| Hyperparameters wrong; need many iterations | Start conservative; document what was tried |
| xBD download is slow / corrupted | Mirror to local SSD on Day 1 |

## Honest Disclaimers in the Writeup

If fine-tuning succeeds, the writeup includes:

> "We fine-tuned a LoRA adapter on the vision component of Gemma 4 E2B using Unsloth, training on the xBD building damage dataset. The adapter achieves X% accuracy on a held-out test set of Y disaster events, compared to Z% for base Gemma 4 with structured prompting. We acknowledge this is below state-of-the-art on the xView2 challenge (which uses purpose-built CNNs and substantially more compute), but it represents a meaningful and honest improvement over the base model for an on-device deployment scenario."

If fine-tuning fails, the writeup includes:

> "We attempted to fine-tune Gemma 4's vision component on the xBD dataset using Unsloth. Within the project timeline, we did not achieve a meaningful improvement over base Gemma 4 with structured prompting. The technical writeup includes our experimental setup, hyperparameters, and observed limitations. Future work would address [specific issues encountered]."

Honesty wins judging. Pretending wins nothing.

## Cross-References

- The Unsloth prize qualification: [`02-hackathon-context.md`](02-hackathon-context.md)
- How the adapter integrates with the drone agent: [`05-per-drone-agent.md`](05-per-drone-agent.md)
- Function calling that consumes damage classifications: [`09-function-calling-schema.md`](09-function-calling-schema.md)
