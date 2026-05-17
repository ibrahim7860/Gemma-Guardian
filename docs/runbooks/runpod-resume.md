# RunPod Resume Runbook — capture-day cloud GPU

**Purpose:** restart the cloud GPU box for capture day. Validated 2026-05-17. Pod paused at end of session to save billing.

## Current capture-day pod (use this)

| Field | Value |
|---|---|
| Pod ID | `gecy7frp1l1nwn` |
| Name | `petite_pink_panther` |
| GPU | 1× NVIDIA **RTX 6000 Ada Generation** (48 GB, Ada Lovelace) |
| Driver / CUDA | 550.78 / 12.4 |
| Cost | $0.74/hr |
| Region | US |
| RAM / vCPU | 78 GB / 14 |
| Container disk | 30 GB |
| Volume disk | 60 GB at `/workspace` |
| Exposed HTTP | 11434, 9090, 8888 |
| SSH | `ssh -i ~/.runpod/ssh/runpodctl-ssh-key root@107.150.186.62 -p 12542` (port can change on restart) |
| HTTPS proxy | `https://gecy7frp1l1nwn-9090.proxy.runpod.net` |

**Historical pods (do not use — kept for reference only):**
- `x06ssfqf5wnmep` (RTX 3090 24 GB) — terminated 2026-05-17; insufficient VRAM for 3×C2A+Ollama Config A on Stockholm host.
- `a9pstxiwgiicb1` (A40 48 GB Stockholm) — terminated 2026-05-17; Stockholm host had no free GPUs to resume after stop.
- `3vzmdd59766dvr` (L40S 48 GB Taiwan) — terminated 2026-05-17; host had broken CUDA runtime (error 803, even on official RunPod PyTorch image; restart did not help).

## What persists across stop/start

| Path | Persists? | Contents |
|---|---|---|
| `/workspace/Gemma-Guardian/` | ✅ Yes (volume disk) | Full repo + `.venv` (~ 7.8 GB) + `kaggle_work_c2a/adapter/` (149 MB) |
| `/workspace/hf_cache/` | ✅ Yes | `unsloth/gemma-4-E2B-it` base model (~6 GB after first load) |
| `/root/.ollama/models/` | ❌ No (container disk, wiped on stop) | `gemma4:e2b` + `gemma4:e4b` need re-pull (~5 min) |
| Ollama binary at `/usr/local/bin/ollama` | ❌ No | Re-install (30 s) |
| SSH key, ports, pod ID | ✅ Yes (pod metadata) | Same SSH command, same HTTPS proxy URL |

## Resume sequence (~6–8 min total)

### 1. Start the pod
```bash
runpodctl start pod x06ssfqf5wnmep
# wait ~30s for STATUS RUNNING
runpodctl pod list
```

### 2. SSH in, re-install Ollama + zstd
```bash
ssh -i ~/.ssh/id_ed25519 -p 11031 root@99.69.17.69

# inside the pod
apt-get install -y -qq zstd rsync
curl -fsSL https://ollama.com/install.sh | sh
```

### 3. Start Ollama

**⚠️ EMPIRICALLY VERIFIED 2026-05-17 (Ibrahim run):** On a 24 GB RTX 3090, C2A coexisting with both Gemma 4 models is **not feasible**. The per-process C2A footprint is **7.4 GB** (not the 3 GB I optimistically projected from 4-bit theory — bitsandbytes activations + buffers add substantial overhead). Math:

| Setup | VRAM | Fits 24 GB? |
|---|---|---|
| Ollama e2b + e4b @ ctx=8192 (Config A baseline) | 17 GB | ✅ 7 GB headroom |
| + 1 × C2A | 24.4 GB | ❌ overflow by 0.4 GB |
| + 1 × C2A, Ollama ctx=4096 | ≈ 23 GB | ⚠️ but Ollama force-unloads one model on every swap → ~30 s reload between drone↔EGS calls; not viable for live capture |
| + 2 × C2A | 32 GB | ❌ impossible |
| + 3 × C2A | 39 GB | ❌ impossible |

**Hard truth:** Config A / B / C all fail on this hardware *when C2A is loaded*. Three real filming-day options:

| Option | Lift | Cost | Verdict |
|---|---|---|---|
| **(i) Upgrade pod to A6000 48 GB** | Re-create pod, expose ports, re-pull models (~15 min) | ~$0.79/hr × 4 hr = **~$3.20** | **Recommended — clean topology, 3× C2A + full Ollama fits comfortably** |
| **(ii) C2A microservice** | Write FastAPI wrapper around `C2AInferenceNode`, modify drone agent's C2A path to HTTP-call instead of in-process | ~30-45 min dev | One shared C2A in VRAM regardless of drone count → ≈ 24 GB total → fits |
| **(iii) Drop C2A from the captured video** | Zero | $0 | Beat 3b uses base E2B with the strengthened system prompt (`shared/prompts/drone_agent_system.md` updated 2026-05-17) + multiple takes. C2A's GATE 3 win + Kaggle Model + writeup §6 numbers remain the published evidence. |

For Sunday-pragmatic capture, **option (iii) is the lowest-risk path.** Option (i) is the gold standard if budget allows. Option (ii) is the elegant fix for post-submission.

### 3a. If continuing on this 24 GB pod *without* C2A
```bash
# No C2A → Ollama can use full 8K context with both models resident comfortably.
nohup env OLLAMA_HOST=0.0.0.0:11434 OLLAMA_NUM_PARALLEL=1 OLLAMA_KEEP_ALIVE=60m \
  OLLAMA_CONTEXT_LENGTH=8192 /usr/local/bin/ollama serve > /workspace/ollama.log 2>&1 &
disown
sleep 4
curl -s http://localhost:11434/api/tags
```

### 3b. If you upgraded to A40 or A6000 48 GB

**Configure the pod with these settings (lesson from 2026-05-17 attempt):**
- GPU: A40 48 GB Secure Cloud at $0.44/hr (A6000 same VRAM and slightly cheaper if available)
- Pod template: `Runpod Pytorch 2.4.0`
- SSH terminal access: ✅
- Container disk: **30 GB** (not 20 — bnb 4-bit quantization needs temp space during HF base download)
- Volume disk: **60 GB** (not 30 — the 30 GB ceiling fills up with: 13 GB repo+.venv + 16 GB Ollama models + 6 GB HF base = 35 GB needed, hits quota)
- Expose HTTP ports: `11434, 9090, 8888`
- Expose TCP ports: `22`

**Why the disk numbers matter:** RunPod enforces the volume-size you pick at creation as a hard quota, even though the underlying network filesystem has TB free. A 30 GB volume can hold either the Ollama models OR the repo+.venv comfortably, but **not both + the HF base model** the C2A inference path needs. Hitting the quota silently fails downloads and triggers segfaults from partially-written model files.

**Setup sequence (~25 min total, mostly download time):**

```bash
# 1. SSH in
ssh -i ~/.ssh/id_ed25519 -p <pod-port> root@<pod-ip>

# 2. Inside pod — bootstrap deps + tools
apt-get update -qq && apt-get install -y -qq zstd rsync
curl -fsSL https://astral.sh/uv/install.sh | sh
curl -fsSL https://ollama.com/install.sh | sh

# 3. Start Ollama — NUM_PARALLEL=4 (we have VRAM to spare on 48 GB)
nohup env OLLAMA_HOST=0.0.0.0:11434 OLLAMA_NUM_PARALLEL=4 OLLAMA_KEEP_ALIVE=60m \
  OLLAMA_MODELS=/workspace/ollama_models \
  /usr/local/bin/ollama serve > /workspace/ollama.log 2>&1 &
disown
sleep 4 && ollama pull gemma4:e2b && ollama pull gemma4:e4b

# 4. From your M1, rsync repo + adapter to pod
# (skip if you already have a volume from a previous session)
rsync -rltvz --no-owner --no-group -e "ssh -i ~/.ssh/id_ed25519 -p <port>" \
  --exclude='.venv/' --exclude='__pycache__/' --exclude='.git/objects/' --exclude='node_modules/' \
  --exclude='frontend/flutter_dashboard/build/' --exclude='kaggle_work/' --exclude='kaggle_out_c2a/' --exclude='kaggle_work_c2a/' \
  ./ root@<pod-ip>:/workspace/Gemma-Guardian/
rsync -rltvz --no-owner --no-group -e "ssh -i ~/.ssh/id_ed25519 -p <port>" \
  kaggle_out_c2a/adapter/ root@<pod-ip>:/workspace/Gemma-Guardian/kaggle_work_c2a/adapter/

# 5. Inside pod — install Python deps
export PATH=$HOME/.local/bin:$PATH
cd /workspace/Gemma-Guardian
uv sync --extra drone --extra ml --extra dev --extra egs --extra sim --extra ws_bridge

# 6. Verify C2A loads standalone — first run downloads ~6 GB base model
.venv/bin/python -c "
import sys; sys.path.insert(0, '/workspace/Gemma-Guardian')
from agents.drone_agent.c2a_inference import C2AInferenceNode
with open('sim/fixtures/frames/placeholder_victim_01.jpg', 'rb') as f: jpg = f.read()
node = C2AInferenceNode()
import json
print(json.dumps(node.analyze_frame(jpg, lat=34.0001, lon=-118.5001, alt=25.0), indent=2))
"
# Expected output: report_finding(type='victim', ...)

# 7. From M1, expose dashboard via SSH tunnel
ssh -L 8080:localhost:8080 -i ~/.ssh/id_ed25519 -p <port> root@<pod-ip>
# Then in pod, start Flutter dashboard or use the pod's HTTPS proxy URL for port 9090
```

**VRAM math on A40 48 GB (confirmed 2026-05-17 — 45 GB usable after CUDA overhead):**
- 3 × C2A in 4-bit: 22 GB
- Ollama (NUM_PARALLEL=4, both models): 22 GB
- **Total: 44 GB / 45 GB → 1 GB headroom** ✅

Drop `NUM_PARALLEL` to 1 or 2 if you want more headroom for safety.

### 4. Re-pull models
```bash
ollama pull gemma4:e2b   # ~2 min
ollama pull gemma4:e4b   # ~3 min
ollama list              # verify both cached
```

### 5. Verify VRAM layout will fit
```bash
nvidia-smi --query-gpu=memory.free --format=csv
# Expect 24125 MB free. Loading e2b+e4b takes ~19 GB; C2A another ~3 GB.
# Total ~22 GB on 24 GB card with NUM_PARALLEL=1. Tight but feasible.
```

### 6a. STANDALONE C2A test (fastest sanity)
```bash
# Inside pod, in /workspace/Gemma-Guardian
cd /workspace/Gemma-Guardian
export HF_HOME=/workspace/hf_cache
export PATH=$HOME/.local/bin:$PATH  # uv lives here

# Re-install uv if needed (it lives on container disk by default)
which uv || curl -fsSL https://astral.sh/uv/install.sh | sh

uv run python -c "
import json
from agents.drone_agent.c2a_inference import C2AInferenceNode
with open('sim/fixtures/frames/placeholder_victim_01.jpg', 'rb') as f:
    jpg = f.read()
node = C2AInferenceNode()
print(json.dumps(node.analyze_frame(jpg, lat=34.0001, lon=-118.5001, alt=25.0), indent=2))
"
# Expected: report_finding with type='victim'
```

### 6b. FULL STACK on pod (integration test for Beat 3b capture)
Requires exposing port 9090 first (RunPod web UI → pod → Edit → expose HTTP `9090`).

```bash
# Inside pod
cd /workspace/Gemma-Guardian
export HF_HOME=/workspace/hf_cache
export PATH=$HOME/.local/bin:$PATH

# Start the full demo stack — tmux session 'fieldagent'
bash scripts/run_full_demo.sh resilience_v1 --duration=240
# OR for a quick smoke:
bash scripts/run_drone3_reliability.sh --dry-run  # validate config first
```

### 7. From your M1: point dashboard at the pod
The Flutter dashboard is a static web app. Open in browser:
```
http://localhost:8080/?ws=wss://x06ssfqf5wnmep-9090.proxy.runpod.net
```
(Adjust `8080` to wherever you serve the Flutter build locally. The `ws=` query param routes WS bridge to the pod.)

## VRAM math reference

| Model | NUM_PARALLEL=1 | NUM_PARALLEL=4 |
|---|---|---|
| `gemma4:e2b` (Ollama) | ~8 GB | ~9 GB |
| `gemma4:e4b` (Ollama) | ~11 GB | ~13 GB |
| C2A base + adapter (PEFT 4-bit) | ~3 GB | — |
| **Total with C2A** | **~22 GB** ✅ fits | ~25 GB ❌ OOM |
| **Total without C2A** | ~19 GB ✅ | ~22 GB ✅ |

Keep `NUM_PARALLEL=1` when running C2A. Drop C2A and bump `NUM_PARALLEL=4` if you want maximum drone throughput without the adapter.

## When done — pause billing

```bash
runpodctl pod stop gecy7frp1l1nwn     # billing pauses, volume disk preserved
# OR if no plan to resume:
runpodctl pod delete gecy7frp1l1nwn   # destroys volume too — only if certain
```

## Local-side cleanup after capture

```bash
# Revert config.yaml back to localhost so future local runs don't try cloud
cd "$REPO_ROOT"
git checkout -- shared/config.yaml
```

## Pre-filming verification — 2026-05-17 on RTX 6000 Ada (pod `gecy7frp1l1nwn`)

Eight-phase verification plan to confirm capture-day readiness. All critical phases PASS.

### Verification matrix

| Phase | Goal | Result |
|---|---|---|
| 0 — Pod bootstrap | apt deps + uv + Ollama + rsync repo + C2A weights + HF base + C2A standalone smoke | ✅ PASS — C2A returns `victim sev=4 conf=0.85` on `placeholder_victim_01.jpg` in 10s (load 98s first time, then HF cached) |
| 1 — Ollama dual-model | gemma4:e2b + gemma4:e4b warm @ NUM_PARALLEL=2 | ✅ PASS — both models respond, **18.3 GB / 48 GB** VRAM, 30.3 GB free for C2A |
| 2 — Stagger patch | `scripts/launch_swarm.sh` GG_DRONE_STAGGER_S env var | ✅ PASS — 43/43 launch_scripts tests green; default 0 (CI), capture day uses 20 |
| 3 — Full demo stack 3×C2A | Config A on `disaster_zone_v1`, 3 drones with C2A | ✅ PASS — all 3 drones C2A-loaded, 26 victim findings aggregated, **44.3 GB / 48 GB** VRAM (3.7 GB headroom) |
| 4 — Victim detection 3/3 | Wow frame `report_finding(type='victim')` reliability | ✅ PASS — drone1 fired 6 consecutive `c2a_adapter_victim` calls under load |
| 5 — Dashboard end-to-end | M1 Flutter ↔ pod WS proxy via Playwright MCP | ✅ PASS — `v1.1.0 · connected`, 3 drones rendered, finding tiles live (`docs_assets/phase5-dashboard-live.png`) |
| 6 — Beat 5 buffered-publisher | drone3 standalone + buffer + replay | ✅ PASS via fix — see "Phase 6 root cause + fix" below. drone3 fires `c2a_adapter_victim` × 3, buffer populates while standalone (515 bytes), drain replays `f_drone3_1..4` into EGS on link restore. Run with `resilience_v1_zonefix`. |
| 7 — Wow-moment trigger eval | `eval_wow_moment_trigger.py --runs 10` baseline + flag end-to-end | ✅ Two-part. (A) Natural rate **0/10** ASSIGNMENT_TOTAL_MISMATCH triggers; cumulative 0/17 across M1+A2000+RTX-6000-Ada — confirms §6.5. (B) `--inject-overcount-once` against `wow_moment_v1` on pod: attempt 1 fires ASSIGNMENT_TOTAL_MISMATCH with injected phantoms, attempt 2 real-E4B retry, attempt 3 valid `corrected_after_retry`. Algorithm 1 retry loop verified live. |

### Phase 6 root cause + fix

**Symptom:** Running `bash scripts/launch_swarm.sh resilience_v1` with all 3 drones loaded, drone3 stays in `agent_status: "standalone"` during the link-drop window but its `drone3_findings_queue.jsonl` stays empty. EGS receives 0 drone3 findings.

**Root cause:** `agents/egs_agent/main.py` was reading the active scenario from `CONFIG.mission.scenario_id` (the hardcoded value in `shared/config.yaml`, "disaster_zone_v1"), not from a CLI arg like every other component. When `launch_swarm.sh resilience_v1` ran:
1. sim, drone agents → used `resilience_v1` waypoints + frame mappings + scripted_events (correct)
2. EGS → used `disaster_zone_v1` to compute `zone_polygon` (wrong)
3. EGS published `egs.state.zone_polygon` derived from disaster_zone_v1 (small ~150×200m box around (34.0, -118.5))
4. Drones subscribe to `egs.state`; `ZoneProvider.update_from_polygon` overwrote each drone's bootstrap zone with the (mismatched) disaster_zone_v1 polygon
5. drone3 at lat=33.9975 was OUTSIDE the disaster_zone_v1 zone → every valid C2A `report_finding(type=victim)` got rejected with `GPS_OUTSIDE_ZONE` → fell through to Ollama → `continue_mission` / `return_to_base`
6. No findings ever published → BufferedPublisher had nothing to buffer

Confirmed by instrumenting `agents/drone_agent/main.py` to log every C2A return + validator outcome + zone_bounds — drone3 received the disaster_zone_v1 polygon, not the resilience_v1 one.

**Fix (3 changes, 147+157 tests pass):**
1. `agents/egs_agent/main.py` — added `--scenario` CLI arg that overrides `CONFIG.mission.scenario_id`. EGS now publishes a zone_polygon matching the active scenario.
2. `scripts/launch_swarm.sh` — passes `--scenario $SCENARIO` to EGS alongside `--inject-overcount-once`.
3. `scripts/run_beat5_capture.sh` — same.

**Second scenario-level quirk (not a code bug):** original `resilience_v1.yaml` walks drone3 south to lat=33.9892, which is more than 500m from the EGS (34.0, -118.5). Even after the scripted `egs_link_restore` event at t=180, the mesh simulator's geometric range check keeps publishing `link=down` for drone3, so drone3 stays standalone and the buffer never drains. For Beat 5 capture, use `sim/scenarios/resilience_v1_zonefix.yaml` (added 2026-05-17) which holds drone3 at lat=33.9975 (~280m south of EGS, well inside both 500m range and 1500m zone). Verified end-to-end: drone3 fires 3 `c2a_adapter_victim` events during t=120–180, buffer accumulates 4 findings, link restore drains them into EGS as `f_drone3_1..4`.

### Critical fixes applied to make this work

1. **torch CUDA mismatch (`error 803: unsupported display driver / cuda driver combination`).** Fresh `uv sync` resolves torch to `2.10.0+cu128`, which needs a newer driver than the host's 550.78. Force `cu124`:
   ```bash
   UV_HTTP_TIMEOUT=180 uv pip install --reinstall \
     torch==2.5.1 torchvision==0.20.1 \
     --index-url https://download.pytorch.org/whl/cu124
   ```
   Verify: `.venv/bin/python -c "import torch; print(torch.cuda.is_available())"` → True.

2. **torchao breaks torch 2.5 downgrade.** `torchao>=0.17` references `torch.int1` which exists only in torch ≥2.10. After the cu124 reinstall, remove torchao (C2A uses bitsandbytes, not torchao):
   ```bash
   uv pip uninstall torchao
   ```

3. **C2A adapter weights live at `kaggle_out_c2a/adapter/` locally but code expects `kaggle_work_c2a/adapter/`.** When rsyncing to pod, target the expected path:
   ```bash
   rsync -rltz --no-owner --no-group -e "ssh -i ~/.runpod/ssh/runpodctl-ssh-key -p $POD_PORT" \
     kaggle_out_c2a/adapter/ root@$POD_IP:/workspace/Gemma-Guardian/kaggle_work_c2a/adapter/
   ```
   Local rsync of the whole repo must NOT exclude `kaggle_out_c2a/` if you skip the explicit adapter copy (current default excludes it for size).

4. **WebSocket bridge binds 127.0.0.1 by default; RunPod proxy needs 0.0.0.0.** `scripts/launch_swarm.sh:215` launches uvicorn without `--host 0.0.0.0`; the pod's HTTPS proxy returns 502 until you fix it. For capture day either patch that line or replace the ws_bridge command in-flight:
   ```bash
   tmux send-keys -t fieldagent:ws_bridge C-c
   tmux send-keys -t fieldagent:ws_bridge \
     "cd /workspace/Gemma-Guardian && source .venv/bin/activate && \
      python3 -m uvicorn frontend.ws_bridge.main:app --host 0.0.0.0 --port 9090 \
      --log-level info 2>&1 | tee /workspace/gg_logs/ws_bridge.log" Enter
   ```

5. **Never run wow eval in parallel with the drone stack.** Two heavy LLM workloads thrash Ollama: per-`/api/chat` latency goes from ~7–25 s to 17–49 s, drones never get through their frame windows, and the run produces zero findings. Sequence: stack → finish, eval → start. Or run eval BEFORE launching the stack.

6. **Drone agent stagger required for safe simultaneous C2A loads.** Each C2A init transiently spikes VRAM during bnb 4-bit quantization. With three drones launching back-to-back the spikes overlap. Use `GG_DRONE_STAGGER_S=20` for capture day:
   ```bash
   GG_DRONE_STAGGER_S=20 GG_LOG_DIR=/workspace/gg_logs \
     bash scripts/launch_swarm.sh disaster_zone_v1 --duration=300
   ```

7. **`resilience_v1` scenario has a Beat 5 design quirk.** Drone3's victim frame window (sim t=121–240) overlaps with drone3 walking outside the EGS zone (lat < 33.9933). Validator correctly rejects out-of-zone findings, so no victims are buffered during the link-drop window. The BufferedPublisher + LinkStateMonitor wiring is verified working (drone3's `agent_status: "standalone"` flips on cue), but `check_beat5.py` A2 will fail until the scenario is tweaked. Post-submission fix: keep drone3's victim frame mapped to a tick range where its GPS is still inside zone.

### Disk / cost discipline

- Volume disk preserved across `pod stop` / `pod start` — full repo + .venv + Ollama models + HF cache + adapter all stay (~30 GB used of 60 GB on this pod).
- Container disk wiped on stop — must re-install zstd, rsync, uv, Ollama, redis-server every resume (~3 min total).
- Per-resume cost: roughly $0.74 × (bootstrap 25 min + verification work) ≈ $0.30–$1.00 per session. Idle stopped pod costs only the 60 GB volume storage.
