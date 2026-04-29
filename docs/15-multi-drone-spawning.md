# 15 — Multi-Drone Spawning

## Goal

Spawn 2-3 drones in the disaster scene, each with its own:
- MAVLink system ID
- ROS 2 namespace
- PX4 SITL instance
- Gazebo model instance
- Camera topic

This is the foundation for the swarm demo. PX4 has built-in multi-vehicle support; we use it.

## Reference Documentation

- PX4 multi-vehicle Gazebo guide: https://docs.px4.io/main/en/sim_gazebo_gz/multi_vehicle_simulation
- Working community example: https://github.com/SathanBERNARD/PX4-ROS2-Gazebo-Drone-Simulation-Template

## How PX4 Multi-Vehicle Works

PX4 SITL runs as multiple separate processes, each:
- A unique `-i <instance>` argument (1, 2, 3, ...)
- Distinct UDP ports for MAVLink communication
- Distinct Gazebo model name (suffixed with the instance)

The first instance starts the Gazebo server (gz-server). Subsequent instances run in "standalone" mode and connect to the running server.

## Launch Pattern

Terminal 1 — XRCE Agent (one for the entire swarm):
```bash
MicroXRCEAgent udp4 -p 8888
```

Terminal 2 — Drone 1 (also starts Gazebo with the disaster world):
```bash
cd ~/PX4-Autopilot
PX4_GZ_WORLD=disaster_zone \
PX4_GZ_MODEL_POSE="0,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4010 \
./build/px4_sitl_default/bin/px4 -i 1
```

Terminal 3 — Drone 2 (standalone, connects to running gz-server):
```bash
cd ~/PX4-Autopilot
PX4_GZ_STANDALONE=1 \
PX4_GZ_MODEL_POSE="5,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4010 \
./build/px4_sitl_default/bin/px4 -i 2
```

Terminal 4 — Drone 3 (same pattern):
```bash
cd ~/PX4-Autopilot
PX4_GZ_STANDALONE=1 \
PX4_GZ_MODEL_POSE="10,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4010 \
./build/px4_sitl_default/bin/px4 -i 3
```

Each drone gets:
- A unique MAVLink system ID (1, 2, 3)
- A unique Gazebo model name (`x500_mono_cam_0`, `x500_mono_cam_1`, etc.)
- A different starting pose

## ROS 2 Topic Namespacing

By default, PX4 publishes uORB messages on global topics. With multi-vehicle, we want each drone's topics namespaced.

The XRCE Agent supports per-vehicle namespaces:

```bash
MicroXRCEAgent udp4 -p 8888 -n /drone1
```

But with a single agent serving all drones, we have to use ROS 2 remapping in our agent code to split them.

The cleaner approach is **one XRCE Agent per drone** on different ports:

```bash
# Drone 1
MicroXRCEAgent udp4 -p 8888 &
# Drone 2
MicroXRCEAgent udp4 -p 8889 &
# Drone 3
MicroXRCEAgent udp4 -p 8890 &
```

And configure each PX4 instance to talk to its own agent port. This gives clean per-drone topic namespaces.

## Launch Script

We bundle this into a single script for the demo:

`scripts/launch_swarm.sh`:

```bash
#!/bin/bash
# Launch the FieldAgent simulation: 3 drones in disaster_zone_v1

set -e

# Start XRCE agents
MicroXRCEAgent udp4 -p 8888 > /tmp/xrce1.log 2>&1 &
XRCE1=$!
MicroXRCEAgent udp4 -p 8889 > /tmp/xrce2.log 2>&1 &
XRCE2=$!
MicroXRCEAgent udp4 -p 8890 > /tmp/xrce3.log 2>&1 &
XRCE3=$!

sleep 2

# Start drone 1 (also launches Gazebo)
cd ~/PX4-Autopilot
PX4_HOME_LAT=34.0000 PX4_HOME_LON=-118.5000 PX4_HOME_ALT=0 \
PX4_GZ_WORLD=disaster_zone_v1 \
PX4_GZ_MODEL_POSE="0,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4010 \
./build/px4_sitl_default/bin/px4 -i 1 > /tmp/drone1.log 2>&1 &
DRONE1=$!

sleep 8  # wait for Gazebo to be ready

# Start drone 2
PX4_HOME_LAT=34.0000 PX4_HOME_LON=-118.5000 PX4_HOME_ALT=0 \
PX4_GZ_STANDALONE=1 \
PX4_GZ_MODEL_POSE="10,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4010 \
./build/px4_sitl_default/bin/px4 -i 2 > /tmp/drone2.log 2>&1 &
DRONE2=$!

sleep 4

# Start drone 3
PX4_HOME_LAT=34.0000 PX4_HOME_LON=-118.5000 PX4_HOME_ALT=0 \
PX4_GZ_STANDALONE=1 \
PX4_GZ_MODEL_POSE="20,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4010 \
./build/px4_sitl_default/bin/px4 -i 3 > /tmp/drone3.log 2>&1 &
DRONE3=$!

echo "Swarm launched. PIDs: $XRCE1 $XRCE2 $XRCE3 $DRONE1 $DRONE2 $DRONE3"
echo "Run 'kill $XRCE1 $XRCE2 $XRCE3 $DRONE1 $DRONE2 $DRONE3' to stop."
echo $XRCE1 $XRCE2 $XRCE3 $DRONE1 $DRONE2 $DRONE3 > /tmp/fieldagent_swarm.pids
```

## Launching the Agents

After the swarm is up, launch the agent processes:

`scripts/launch_agents.sh`:

```bash
#!/bin/bash
# Launch the per-drone agents and the EGS

cd ~/fieldagent

# Drone agents
python3 -m agents.drone_agent --drone_id=drone1 --xrce_port=8888 > /tmp/agent_drone1.log 2>&1 &
python3 -m agents.drone_agent --drone_id=drone2 --xrce_port=8889 > /tmp/agent_drone2.log 2>&1 &
python3 -m agents.drone_agent --drone_id=drone3 --xrce_port=8890 > /tmp/agent_drone3.log 2>&1 &

# EGS
python3 -m agents.egs_agent > /tmp/egs.log 2>&1 &

# Mesh simulator
python3 -m agents.mesh_simulator > /tmp/mesh.log 2>&1 &

# rosbridge for the Flutter dashboard
ros2 launch rosbridge_server rosbridge_websocket_launch.xml > /tmp/rosbridge.log 2>&1 &
```

## Single-Command Demo Launcher

For the demo recording session:

`scripts/run_full_demo.sh`:

```bash
#!/bin/bash
# Full demo launcher: simulation + agents + dashboard

bash scripts/launch_swarm.sh
sleep 15  # wait for Gazebo and PX4 to fully initialize
bash scripts/launch_agents.sh
sleep 5
echo "FieldAgent demo running. Open the Flutter dashboard at http://localhost:8080"
```

And a stop script:

`scripts/stop_demo.sh`:

```bash
#!/bin/bash
pkill -f MicroXRCEAgent
pkill -f px4
pkill -f drone_agent
pkill -f egs_agent
pkill -f mesh_simulator
pkill -f rosbridge
killall gz
```

## Camera Topics with Multi-Vehicle

Each drone gets its own camera topic. The pattern is:

```
/world/disaster_zone_v1/model/x500_mono_cam_0/link/camera_link/sensor/imager/image  # drone 1
/world/disaster_zone_v1/model/x500_mono_cam_1/link/camera_link/sensor/imager/image  # drone 2
/world/disaster_zone_v1/model/x500_mono_cam_2/link/camera_link/sensor/imager/image  # drone 3
```

These are Gazebo topics. We need a ROS-Gz bridge to access them in ROS 2:

```bash
ros2 run ros_gz_bridge parameter_bridge \
  /world/disaster_zone_v1/model/x500_mono_cam_0/link/camera_link/sensor/imager/image@sensor_msgs/msg/Image[gz.msgs.Image \
  /world/disaster_zone_v1/model/x500_mono_cam_1/link/camera_link/sensor/imager/image@sensor_msgs/msg/Image[gz.msgs.Image \
  /world/disaster_zone_v1/model/x500_mono_cam_2/link/camera_link/sensor/imager/image@sensor_msgs/msg/Image[gz.msgs.Image \
  --ros-args -r /world/disaster_zone_v1/model/x500_mono_cam_0/link/camera_link/sensor/imager/image:=/drone1/camera \
             -r /world/disaster_zone_v1/model/x500_mono_cam_1/link/camera_link/sensor/imager/image:=/drone2/camera \
             -r /world/disaster_zone_v1/model/x500_mono_cam_2/link/camera_link/sensor/imager/image:=/drone3/camera
```

This remaps the verbose Gazebo topic names to clean `/drone<id>/camera` names that the agent code uses.

## Performance Notes

Multi-drone simulation is GPU- and CPU-intensive. With 3 drones each rendering a camera at 30 Hz:

- GPU usage: 60-80% on RTX 4090 (Gazebo + Ollama compete)
- CPU usage: 4-6 cores active
- RAM: 8-12 GB

If your dev machine struggles:
- Reduce camera FPS in the SDF model (drop to 10 Hz from 30 Hz)
- Reduce camera resolution (640×480 from 1280×720)
- Drop to 2 drones for the demo

The agent loop only samples 1 frame per second per drone, so high camera FPS is wasted.

## What Could Go Wrong

| Failure | Mitigation |
|---|---|
| Second drone doesn't spawn | Check `PX4_GZ_STANDALONE=1` is set; check Gazebo server is up |
| Cameras have name collisions | Verify each drone's model name has a unique suffix |
| ROS 2 topics conflict | Use the bridge remapping pattern above |
| Drones flicker / disappear | GPU memory exhaustion; reduce camera resolution |
| One drone's PX4 crashes | Use the `--restart` pattern in launch script; isolate the issue |
| MAVLink IDs collide in QGroundControl | Each drone needs a unique `-i N`; verify with `ros2 topic list` |

## Fallback: 2 Drones Instead of 3

If 3 drones is unstable, drop to 2. The demo still works:
- Drone 1: surveys western half
- Drone 2: surveys eastern half
- One drone fails mid-mission; the other takes over

This is a perfectly fine demo scenario, and the architecture argument is unchanged.

## Cross-References

- Gazebo install and single-drone setup: [`13-gazebo-setup.md`](13-gazebo-setup.md)
- The disaster scene used: [`14-disaster-scene-design.md`](14-disaster-scene-design.md)
- Mesh simulation: [`08-mesh-communication.md`](08-mesh-communication.md)
- Demo capture: [`21-demo-storyboard.md`](21-demo-storyboard.md)
