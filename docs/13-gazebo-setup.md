# 13 — Gazebo Setup

## Why This Doc Exists

Getting Gazebo + PX4 + ROS 2 running on Day 1 is the highest-risk single task in the project. This doc gives the exact steps Person 1 follows to get a working baseline by end of Day 2.

If this doesn't work by Day 2, we switch to Gazebo Classic (older, more stable) or AirSim. Don't let perfect be the enemy of working.

## Target Stack

- **OS:** Ubuntu 22.04 LTS (native install, NOT a VM)
- **ROS 2:** Humble Hawksbill
- **PX4 Autopilot:** main branch (latest)
- **Gazebo:** Harmonic (Gz Sim 8.x)
- **Communication:** Micro XRCE-DDS Agent (PX4 ↔ ROS 2 bridge)

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

If you already have Ubuntu 22.04 native, skip. Otherwise:
- Download Ubuntu 22.04 LTS desktop ISO
- Create bootable USB
- Install (dual-boot if needed; do not use a VM)
- Update: `sudo apt update && sudo apt upgrade -y`

## Step 2: Install ROS 2 Humble

Follow official ROS 2 Humble Ubuntu installation instructions:
https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html

Quick version:
```bash
locale  # check for UTF-8
sudo apt install software-properties-common
sudo add-apt-repository universe
sudo apt update && sudo apt install curl -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null
sudo apt update
sudo apt upgrade -y
sudo apt install ros-humble-desktop -y
sudo apt install ros-dev-tools -y
```

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

This is the bridge between PX4's uORB messages and ROS 2 topics.

```bash
git clone https://github.com/eProsima/Micro-XRCE-DDS-Agent.git
cd Micro-XRCE-DDS-Agent
mkdir build && cd build
cmake ..
make
sudo make install
sudo ldconfig /usr/local/lib/
```

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

Terminal 4:
```bash
ros2 topic list | grep camera
ros2 run image_view image_view image:=/world/default/model/x500_mono_cam_0/link/camera_link/sensor/imager/image
```

Or with `rqt_image_view`:
```bash
rqt
# Plugins → Visualization → Image View
```

You should see the simulated camera's view from above.

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

For multimodal verification, send the camera frame:
```bash
ollama run gemma-4:e2b "Describe this image" --image /tmp/test_frame.jpg
```

If this works, **the full pipeline is verified**: Gazebo → ROS 2 → Python → Ollama → Gemma 4.

## Common Failure Modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `make px4_sitl` fails with missing deps | setup.sh didn't run cleanly | Re-run `bash ./PX4-Autopilot/Tools/setup/ubuntu.sh`, reboot |
| Gazebo opens but drone falls / explodes | Wrong simulator version | Use `gz_x500_mono_cam` not `gazebo-classic_iris` |
| Camera topic doesn't appear | XRCE Agent not running, or wrong topic name | Check `ros2 topic list`, run XRCE Agent |
| QGC can't connect | UDP port conflict | Restart everything, ensure no other QGC instance |
| Ollama doesn't recognize gemma-4 | Pulled wrong tag | Check `ollama list`; tag may be different at hackathon time |
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
