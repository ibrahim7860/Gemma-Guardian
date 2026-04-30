# 13 — Runtime Setup

## Why This Doc Exists

Every team member needs a working dev environment before contributing code. This guide gets you there in under 30 minutes on macOS, Linux, or Windows 11. There is no platform-specific simulation software: the stack is Python + Redis + Ollama, all of which run natively on every OS.

## Target Stack

| Component | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Agents, sim scripts, ML pipeline |
| Redis | 7+ | Inter-process pub/sub bus (all channels — see Contract 9 in `docs/20-integration-contracts.md`) |
| Ollama | latest | Runs Gemma 4 E2B (drone agent) and Gemma 4 E4B (EGS) locally |
| NVIDIA CUDA | optional | Person 5's fine-tuning workstream only; not needed for any other role |

No Gazebo. No PX4. No ROS 2. No WSL2 requirement.

## Per-Platform Install

### macOS (Apple Silicon or Intel)

```bash
# Install Homebrew if not already present: https://brew.sh
brew install python@3.11 redis
brew services start redis
```

Install Ollama from https://ollama.com/download (native macOS app, Metal-accelerated on Apple Silicon).

Verify:
```bash
redis-cli ping          # → PONG
python3.11 --version    # → Python 3.11.x
ollama --version        # → ollama version ...
```

### Linux (Ubuntu 22.04 / Debian)

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip redis-server
sudo systemctl enable --now redis-server
```

Install Ollama:
```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Verify:
```bash
redis-cli ping          # → PONG
python3.11 --version    # → Python 3.11.x
ollama --version        # → ollama version ...
```

### Linux (Fedora / RHEL)

```bash
sudo dnf install -y python3.11 redis
sudo systemctl enable --now redis
curl -fsSL https://ollama.com/install.sh | sh
```

Verify with the same three commands above.

### Windows 11

Option A — Windows-native Redis (recommended):
```powershell
# Run PowerShell as Administrator
winget install Python.Python.3.11
winget install Redis.Redis
# Start Redis service
Start-Service Redis
```

Option B — Redis under WSL2 (if winget Redis is unavailable on your build):
```powershell
wsl --install -d Ubuntu-22.04
# Then inside WSL2:
sudo apt update && sudo apt install -y redis-server
sudo service redis-server start
```

Install Ollama for Windows from https://ollama.com/download.

Verify (in PowerShell or WSL2 shell):
```bash
redis-cli ping          # → PONG
python --version        # → Python 3.11.x
ollama --version        # → ollama version ...
```

## Pull Gemma 4 Models

```bash
ollama pull gemma4:e2b
ollama pull gemma4:e4b
```

**Important:** the exact Ollama tag for each Gemma 4 variant is pinned in `docs/20-integration-contracts.md` (Contract 2). Confirm against https://ollama.com/library at integration time. Do not hard-code a tag anywhere in the codebase other than that contract.

`gemma4:e2b` runs on the drone agent process. `gemma4:e4b` runs on the EGS agent process. Both can run on the same machine during development; the demo box should have enough VRAM to hold both (8 GB VRAM minimum; 12 GB+ recommended if running both simultaneously).

## Clone Repo and Install Python Dependencies

```bash
git clone <repo-url> fieldagent
cd fieldagent
```

Install deps for your role (install all three if unsure):

```bash
# Core shared deps (everyone)
pip install -r shared/requirements.txt

# Drone and EGS agents
pip install -r agents/drone_agent/requirements.txt

# ML fine-tuning workstream (Person 5 only, requires CUDA)
pip install -r ml/requirements.txt
```

Using a virtual environment is strongly recommended:
```bash
python3.11 -m venv .venv
source .venv/bin/activate   # macOS/Linux
# .venv\Scripts\activate    # Windows PowerShell
pip install -r shared/requirements.txt
```

## Smoke Test

With `redis-server` running:

```bash
python3.11 -c "
import redis
r = redis.Redis()
assert r.ping(), 'Redis not responding'
r.publish('test.channel', 'hello')
print('ok — Redis pub/sub is working')
"
```

Expected output: `ok — Redis pub/sub is working`

Then verify Ollama responds:
```bash
ollama run gemma4:e2b "Reply with one word: ready"
# Expected: ready  (or similar single-word confirmation)
```

If both pass, your environment is ready.

## NVIDIA CUDA (Person 5 / Fine-Tuning Only)

Person 5's Unsloth fine-tuning workstream requires an NVIDIA GPU with CUDA 12+. This is not needed for any other role. Options:

- **Native Linux with NVIDIA GPU:** install CUDA Toolkit from https://developer.nvidia.com/cuda-downloads, then `pip install -r ml/requirements.txt`.
- **WSL2 on Windows 11 with NVIDIA GPU:** install the latest NVIDIA Windows driver; CUDA passthrough works automatically inside WSL2.
- **Rented GPU (Lambda Labs / Paperspace / Runpod):** the ml/requirements.txt installs cleanly on any Ubuntu 22.04 cloud GPU instance. See `docs/12-fine-tuning-plan.md` for the go/no-go gate.

## Cross-References

- Running 2-3 drone agents simultaneously: [`docs/15-multi-drone-spawning.md`](15-multi-drone-spawning.md)
- Redis channel naming and JSON schemas: [`docs/20-integration-contracts.md`](20-integration-contracts.md) Contract 9
- Scenario YAML format and disaster scene layout: [`docs/14-disaster-scene-design.md`](14-disaster-scene-design.md)
