# 13 — Gazebo Setup

## Why This Doc Exists

Getting Gazebo + PX4 + ROS 2 running on Day 1 is the highest-risk single task in the project. This doc gives the exact steps Person 1 follows to get a working baseline by end of Day 2.

If this doesn't work by Day 2, we switch to Gazebo Classic (older, more stable) or AirSim. Don't let perfect be the enemy of working.

## Target Stack

- **OS:** Ubuntu 22.04 LTS (jammy) — native install OR WSL2 on Windows 11 (with WSLg for GUI). VirtualBox/Parallels-class VMs are still NOT acceptable.
- **ROS 2:** Humble Hawksbill
- **PX4 Autopilot:** main branch (latest, v1.15+)
- **Gazebo:** Harmonic (Gz Sim 8.x). Note: this is a *non-default* pairing — Humble officially ships with Gazebo Fortress; Harmonic is the official pairing for Jazzy. We get Harmonic on Humble through `packages.osrfoundation.org` `ros-gz` binaries, which the PX4 `ubuntu.sh` setup script handles for us. **Do not also `apt install ros-humble-ros-gz*`** — those are the Fortress-paired packages and they conflict.
- **Communication:** Micro XRCE-DDS Agent (PX4 uXRCE-DDS ↔ ROS 2 bridge) for `/fmu/in/*` and `/fmu/out/*` flight-controller topics, plus `ros_gz_bridge` for Gazebo sensor topics (camera, IMU, etc.) — **two distinct bridges, both required.**

## Platform Path Selection

The project supports two development paths for the simulation stack. The team picks one based on hardware availability:

| Path | When to use | Trade-offs |
|---|---|---|
| **Native Ubuntu 22.04** | Anyone with a dedicated Linux machine, or willing to dual-boot | First-class everything; preferred path for the demo recording machine |
| **WSL2 on Windows 11** | Anyone on Windows (the team's default) | Mature in 2026, well-documented, supports WSLg for Gazebo GUI. NVIDIA GPU passthrough works for both rendering and CUDA |

**Apple Silicon Macs are NOT a supported sim path.** Persons 1 and 5 must use native Ubuntu or WSL2. macOS is fine for Persons 2, 3, and 4 (agent / EGS / frontend), since those components run cross-platform on Ollama (Metal), Python, and Flutter respectively.

**The demo recording must come from a stable, integrated environment** — either native Ubuntu or a well-tested WSL2 setup. Designate one machine as the "demo box" by Day 1 and treat it as critical infrastructure.

## Hardware Check

Before installing:
- RAM: 32 GB recommended (16 GB minimum, will be tight)
- GPU: NVIDIA RTX 3060 or better (Gazebo rendering + Ollama Gemma 4 share the GPU)
- Disk: 100 GB free
- CPU: 8+ cores recommended for multi-drone simulation

Verify:
```bash
free -h
nvidia-smi
df -h
nproc
```

## Step 1: Install Ubuntu 22.04

### Path A: Native Ubuntu

If you already have Ubuntu 22.04 native, skip. Otherwise:
- Download Ubuntu 22.04 LTS desktop ISO
- Create bootable USB
- Install (dual-boot if needed; do not use VirtualBox/Parallels)
- Update: `sudo apt update && sudo apt upgrade -y`

### Path B: WSL2 on Windows 11 (the team's default)

Run in PowerShell (as Administrator):
```powershell
wsl --install -d Ubuntu-22.04
```

Then inside the WSL2 Ubuntu shell:
```bash
sudo apt update && sudo apt upgrade -y
```

**WSL2 verification checklist:**
- WSLg is enabled (default on Windows 11) — needed for Gazebo GUI: `echo $WAYLAND_DISPLAY` should return `wayland-0`
- WSL version is 2: `wsl -l -v` should show VERSION 2 next to your distro
- If the host has an NVIDIA GPU, install the latest NVIDIA Windows driver — CUDA passthrough works automatically; verify with `nvidia-smi` inside WSL2
- Clock sync: WSL2 occasionally drifts; if you see weird ROS 2 timing issues, run `sudo hwclock -s`

**WSL2 known caveats:**
- USB device passthrough (real PX4 hardware) is finicky; we run SITL only, so this doesn't affect us
- File I/O between Windows and WSL2 is slow; **keep the project repo inside WSL2's home directory (`~/`), NOT under `/mnt/c/`**
- First boot of WSLg can be slow (~30s); subsequent launches are fast

## Step 2: Install ROS 2 Humble

Follow official ROS 2 Humble Ubuntu installation instructions:
https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html

Quick version:
```bash
# Locale (must be UTF-8)
sudo apt update && sudo apt install -y locales
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
export LANG=en_US.UTF-8

sudo apt install -y software-properties-common
sudo add-apt-repository universe
sudo apt update && sudo apt install -y curl
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
sudo apt update && sudo apt upgrade -y
sudo apt install -y ros-humble-desktop
sudo apt install -y ros-dev-tools
```

**Do NOT install `ros-humble-ros-gz` from the ROS apt repo.** That package targets Gazebo Fortress, the default Humble pairing. We're running Harmonic (the non-default pairing), so the `ros_gz` bridge comes from the OSRF repo and is installed by PX4's `ubuntu.sh`. Mixing the two will cause version conflicts at runtime.

Add to `~/.bashrc`:
```bash
source /opt/ros/humble/setup.bash
```

Verify:
```bash
ros2 topic list  # should run without errors
```

## Step 3: Install PX4 Autopilot

```bash
git clone https://github.com/PX4/PX4-Autopilot.git --recursive
bash ./PX4-Autopilot/Tools/setup/ubuntu.sh
```

This installs Gazebo Harmonic and all dependencies. **Will take 20-40 minutes.**

After install, log out and log back in (group memberships).

## Step 4: Install Micro XRCE-DDS Agent

This is the bridge between PX4's uORB messages and ROS 2 topics (it surfaces `/fmu/in/*` and `/fmu/out/*` on the ROS 2 graph). It does **not** bridge Gazebo sensor topics — those go through `ros_gz_bridge`, see Step 7.

```bash
git clone https://github.com/eProsima/Micro-XRCE-DDS-Agent.git
cd Micro-XRCE-DDS-Agent
mkdir build && cd build
cmake ..
make
sudo make install
sudo ldconfig /usr/local/lib/
```

If `cmake ..` fails fetching FastDDS/FastCDR, retry with the standalone-deps flag: `cmake -DUAGENT_USE_INTERNAL_FAST_DDS=ON -DUAGENT_USE_INTERNAL_FAST_CDR=ON ..`.

## Step 5: Install QGroundControl

Used for manual control during testing (verify drone is flyable before adding agent).

```bash
sudo usermod -a -G dialout $USER
sudo apt-get remove modemmanager -y
sudo apt install gstreamer1.0-plugins-bad gstreamer1.0-libav gstreamer1.0-gl -y
```

Download AppImage:
```bash
cd ~/Downloads
wget https://s3-us-west-2.amazonaws.com/qgroundcontrol/latest/QGroundControl.AppImage
chmod +x QGroundControl.AppImage
```

Log out and back in.

## Step 6: Verify Single-Drone Flight

This is the gate before doing anything else.

Terminal 1 — start the XRCE Agent:
```bash
MicroXRCEAgent udp4 -p 8888
```

Terminal 2 — start PX4 SITL with Gazebo:
```bash
cd ~/PX4-Autopilot
make px4_sitl gz_x500_mono_cam
```

This launches:
- Gazebo Harmonic with the X500 quadcopter (with monocular camera)
- PX4 SITL flight controller
- A default world

Terminal 3 — open QGroundControl:
```bash
~/Downloads/QGroundControl.AppImage
```

QGroundControl should auto-detect the simulated drone. Click "Takeoff" and confirm. The drone should rise.

If this works, infrastructure is fine. **End of Day 2 milestone.**

## Step 7: Verify Camera Feed in ROS 2

The PX4-spawned camera publishes on **Gazebo Transport**, not the ROS 2 graph. The Micro XRCE-DDS Agent does NOT bridge it. You must run a `ros_gz_bridge` to surface it as a ROS 2 `sensor_msgs/Image` topic.

Terminal 4 — list the Gazebo-side topic to find the exact name (the `gz` CLI ships with Harmonic):
```bash
gz topic -l | grep -i image
# Expect something like: /world/default/model/x500_mono_cam_0/link/camera_link/sensor/imager/image
```

Terminal 5 — bridge that Gazebo topic into ROS 2:
```bash
# Replace <gz_image_topic> with the path you found above
ros2 run ros_gz_bridge parameter_bridge \
  <gz_image_topic>@sensor_msgs/msg/Image[gz.msgs.Image
```

Terminal 6 — verify in ROS 2:
```bash
ros2 topic list | grep image
ros2 run rqt_image_view rqt_image_view
# Or:
ros2 run image_view image_view --ros-args -r image:=<gz_image_topic>
```

You should see the simulated camera's view from above.

> Note: the PX4 image topic path is auto-generated from the SDF (`world/<world>/model/<model>_<instance>/link/<link>/sensor/<sensor>/image`) and changes if you rename the model or use multi-vehicle. Don't hard-code it; resolve it at startup with `gz topic -l`.

## Step 8: Clone Reference Templates

Two repos worth cloning as starting points:

```bash
# Multi-vehicle simulation template
git clone https://github.com/SathanBERNARD/PX4-ROS2-Gazebo-Drone-Simulation-Template.git

# Reference YOLOv8 integration (we'll replace YOLOv8 with Gemma 4)
git clone https://github.com/monemati/PX4-ROS2-Gazebo-YOLOv8.git
```

Don't fork these into the main project repo yet. Use them as references for code patterns.

## Step 9: Smoke Test Python Camera Subscription

Run this with the `ros_gz_bridge` from Step 7 still active. Substitute the bridged topic name you confirmed via `ros2 topic list` for the placeholder below.

Create `~/test_camera.py`:

```python
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2

class CameraSubscriber(Node):
    def __init__(self):
        super().__init__('camera_subscriber')
        self.bridge = CvBridge()
        # NOTE: this is the ROS 2 topic produced by ros_gz_bridge (see Step 7),
        # not the raw Gazebo Transport topic. Confirm the exact name with
        # `ros2 topic list` after starting the bridge.
        self.subscription = self.create_subscription(
            Image,
            '/world/default/model/x500_mono_cam_0/link/camera_link/sensor/imager/image',
            self.callback,
            10
        )
        
    def callback(self, msg):
        img = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
        cv2.imwrite('/tmp/test_frame.jpg', img)
        self.get_logger().info(f'Saved frame, shape: {img.shape}')

rclpy.init()
node = CameraSubscriber()
rclpy.spin_once(node, timeout_sec=5.0)
node.destroy_node()
rclpy.shutdown()
```

Run with the simulator running:
```bash
python3 ~/test_camera.py
ls -la /tmp/test_frame.jpg
```

If a frame is saved, **the camera pipeline works**.

## Step 10: Install Ollama and Verify Gemma 4

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve  # in one terminal
ollama pull gemma-4:e2b  # in another
ollama run gemma-4:e2b "Hello, can you see this?"
```

For multimodal verification, send the camera frame. Ollama's CLI takes images by appending the path to the prompt (no `--image` flag); confirm syntax for the pinned Gemma 4 tag against `ollama.com/library` at integration time:
```bash
ollama run <pinned-gemma-4-e2b-tag> "Describe this image: /tmp/test_frame.jpg"
```

If this works, **the full pipeline is verified**: Gazebo → ROS 2 → Python → Ollama → Gemma 4.

## Common Failure Modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `make px4_sitl` fails with missing deps | setup.sh didn't run cleanly | Re-run `bash ./PX4-Autopilot/Tools/setup/ubuntu.sh`, reboot |
| Gazebo opens but drone falls / explodes | Wrong simulator version | Use `gz_x500_mono_cam` not `gazebo-classic_iris` |
| Camera topic doesn't appear in ROS 2 | `ros_gz_bridge` not running (XRCE Agent does NOT bridge Gazebo sensors) | Start the bridge from Step 7; confirm gz-side with `gz topic -l \| grep image` first |
| QGC can't connect | UDP port conflict | Restart everything, ensure no other QGC instance |
| Ollama doesn't recognize gemma-4 | Pulled wrong tag | Check `ollama list` and `ollama.com/library`; the canonical Gemma 4 tag must be pinned in `docs/20-integration-contracts.md` once confirmed at integration time. Do not hard-code a tag here. |
| `ros2 topic list` shows nothing from PX4 | Wrong DDS middleware or XRCE Agent not running on UDP 8888 | Confirm `MicroXRCEAgent udp4 -p 8888` is running; check `RMW_IMPLEMENTATION` is unset or set to `rmw_fastrtps_cpp` |
| `ros-humble-ros-gz` install fails / conflicts | You installed the Fortress-paired Humble package over PX4's Harmonic-paired one | `sudo apt remove ros-humble-ros-gz*` and re-run `bash ./PX4-Autopilot/Tools/setup/ubuntu.sh` |
| Gazebo runs slowly | GPU not being used | `nvidia-smi` should show gz-server using GPU |
| Build takes forever / runs out of disk | Insufficient disk | Free up space; PX4 build alone is ~5 GB |

## Fallback Plans

**If Gazebo Harmonic is fundamentally broken on your system:**
- Switch to Gazebo Classic 11 with PX4
- Older but more battle-tested
- Most online tutorials use Classic

**If PX4 SITL is unstable:**
- Switch to AirSim (Microsoft, deprecated but functional)
- Or AVES (lower fidelity, simpler)

**If multi-drone is too hard in your sim:**
- Demo with 2 drones max
- Frame as "core architecture validated; scaling to N drones is future work"

## What to Do at End of Day 2

1. ✅ Single drone flying in Gazebo
2. ✅ Camera frame accessible from Python
3. ✅ Ollama running Gemma 4 E2B
4. ✅ End-to-end test: take a frame, send to Gemma 4, get a structured response

If all 4 are checked, Day 1-2 is done. Move to Week 1 work.

If any are not checked, escalate immediately. Person 5 is paired with Person 1 every day specifically so Person 1 is never solo on infrastructure problems. **Don't sit on infrastructure problems alone.**

## Cross-References

- Multi-drone setup: [`15-multi-drone-spawning.md`](15-multi-drone-spawning.md)
- Disaster scene design: [`14-disaster-scene-design.md`](14-disaster-scene-design.md)
- Day-by-day plan: [`19-day-by-day-plan.md`](19-day-by-day-plan.md)
