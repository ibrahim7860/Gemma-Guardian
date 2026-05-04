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

### Linux (Ubuntu 22.04 / 24.04 / Debian)

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip redis-server
sudo systemctl enable --now redis-server
```

If `systemctl` errors with "System has not been booted with systemd" (common on WSL2 distros that don't have `systemd=true` in `/etc/wsl.conf`), use the `service` fallback instead:

```bash
sudo service redis-server start
```

Both end up with `redis-cli ping` returning `PONG`.

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

### Primary path: `uv` (recommended)

This repo uses [uv](https://docs.astral.sh/uv/) as the canonical Python package manager. A single `pyproject.toml` at the repo root declares every Python dependency the project needs, split into role-scoped extras (`sim`, `mesh`, `drone`, `egs`, `ws_bridge`, `ml`, `dev`). The committed `uv.lock` pins exact versions for fully reproducible installs.

Install uv (one time, anywhere):

```bash
# macOS / Linux / WSL2
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Alternative: pipx install uv
```

Then install the slice your role needs (uv creates `.venv/` automatically):

```bash
# Person 1 (Sim Lead): sim + mesh simulator
uv sync --extra sim --extra mesh --extra dev

# Person 2 (Drone Agent + ML): drone agent + ML fine-tuning
uv sync --extra drone --extra ml --extra dev

# Person 3 (EGS): EGS coordinator
uv sync --extra egs --extra dev

# Person 4 (Frontend / Bridge): FastAPI WebSocket bridge
uv sync --extra ws_bridge --extra dev

# Everyone, full graph (e2e / integration / "install all of them if unsure"):
uv sync --all-extras
```

`uv sync --frozen` is the CI mode — refuses to touch the lock and fails fast if `pyproject.toml` and `uv.lock` are out of sync. Use that whenever you want a deterministic install.

Run any project command through the venv with `uv run`, e.g.:

```bash
PYTHONPATH=. uv run python -m pytest sim/
PYTHONPATH=. uv run python sim/waypoint_runner.py --scenario disaster_zone_v1
```

Or activate the venv directly:

```bash
source .venv/bin/activate     # macOS / Linux / WSL2
# .venv\Scripts\activate      # Windows PowerShell
```

### Fallback path: plain `pip`

If you can't or don't want to install uv, you can provision a venv by hand and `pip install` the same extras out of `pyproject.toml`. Pick the slice you need:

```bash
python3 -m venv .venv
source .venv/bin/activate                  # macOS / Linux / WSL2
# .venv\Scripts\activate                   # Windows PowerShell
pip install --upgrade pip
pip install -e ".[sim,mesh,dev]"           # Person 1
pip install -e ".[drone,ml,dev]"           # Person 2
pip install -e ".[egs,dev]"                # Person 3
pip install -e ".[ws_bridge,dev]"          # Person 4
# Or everything:
pip install -e ".[sim,mesh,drone,egs,ws_bridge,ml,dev]"
```

Plain `pip` does **not** read `uv.lock`, so versions are upper-bound only. That's fine for local development; CI uses uv with `--frozen` for the deterministic build.

**Ubuntu 24.04 / PEP 668 note:** the system Python on 24.04 is marked "externally-managed" and will refuse `pip install` with the error `error: externally-managed-environment`. The uv path above sidesteps this entirely (uv manages its own venv). If you're on the pip fallback, either use the venv above (preferred) or pass `pip install --break-system-packages ...`. The same applies on any distro shipping pip 23.0+.

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
