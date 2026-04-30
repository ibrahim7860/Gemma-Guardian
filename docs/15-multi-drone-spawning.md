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

- PX4 multi-vehicle Gazebo guide: https://docs.px4.io/main/en/sim_gazebo_gz/multi_vehicle_simulation.html
- PX4 uXRCE-DDS namespace customization: https://docs.px4.io/main/en/middleware/uxrce_dds.html#customizing-the-namespace
- Working community example: https://github.com/SathanBERNARD/PX4-ROS2-Gazebo-Drone-Simulation-Template

## How PX4 Multi-Vehicle Works

PX4 SITL runs as multiple separate processes, each:
- A unique `-i <instance>` argument (1, 2, 3, ...). The instance number drives the MAVLink system ID and offsets the simulator/MAVLink UDP ports (remote ports start at 14541 and increment per instance).
- Distinct Gazebo model name (PX4 appends an index suffix to `PX4_SIM_MODEL`'s spawned model — e.g. `x500_mono_cam_0`, `x500_mono_cam_1`, …).
- A unique uXRCE-DDS topic namespace (set per process via `PX4_UXRCE_DDS_NS`).

The first instance starts the Gazebo server (gz-server). Subsequent instances must set `PX4_GZ_STANDALONE=1` so they connect to the already-running server instead of trying to launch their own.

## Launch Pattern

Terminal 1 — XRCE Agent (a single agent on port 8888 serves the entire swarm; per-drone isolation is handled via `PX4_UXRCE_DDS_NS` on the PX4 side, not by running multiple agents):
```bash
MicroXRCEAgent udp4 -p 8888
```

Terminal 2 — Drone 1 (also starts Gazebo with the disaster world):
```bash
cd ~/PX4-Autopilot
PX4_UXRCE_DDS_NS=drone1 \
PX4_GZ_WORLD=disaster_zone_v1 \
PX4_GZ_MODEL_POSE="0,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4001 \
./build/px4_sitl_default/bin/px4 -i 1
```

Terminal 3 — Drone 2 (standalone, connects to running gz-server):
```bash
cd ~/PX4-Autopilot
PX4_UXRCE_DDS_NS=drone2 \
PX4_GZ_STANDALONE=1 \
PX4_GZ_MODEL_POSE="5,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4001 \
./build/px4_sitl_default/bin/px4 -i 2
```

Terminal 4 — Drone 3 (same pattern):
```bash
cd ~/PX4-Autopilot
PX4_UXRCE_DDS_NS=drone3 \
PX4_GZ_STANDALONE=1 \
PX4_GZ_MODEL_POSE="10,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4001 \
./build/px4_sitl_default/bin/px4 -i 3
```

Each drone gets:
- A unique MAVLink system ID derived from `-i N` (PX4 uses the instance number; ID 1 is reserved on the network so for real-world deployments we'd offset, but for SITL the instance number is fine).
- A unique Gazebo model name: `x500_mono_cam_0`, `x500_mono_cam_1`, `x500_mono_cam_2` (PX4 zero-indexes the suffix even though `-i` is 1-indexed).
- A unique ROS 2 topic prefix: `/drone1/fmu/...`, `/drone2/fmu/...`, `/drone3/fmu/...` via `PX4_UXRCE_DDS_NS`.
- A different starting pose.

> Note on autostart: `4001` is the canonical "Quadrotor X" airframe used by every `gz_x500*` SITL build (see `ROMFS/px4fmu_common/init.d/airframes/`). Do not invent autostart numbers — only IDs that exist in that directory will boot.

## ROS 2 Topic Namespacing

By default, PX4's uXRCE-DDS client publishes uORB messages under `/fmu/in/...` and `/fmu/out/...` with no per-vehicle prefix, which collides immediately under multi-vehicle. We solve this with the official PX4 mechanism: the `PX4_UXRCE_DDS_NS` environment variable (or `uxrce_dds_client start -n <ns>`).

With `PX4_UXRCE_DDS_NS=drone1` set on the PX4 process, that vehicle's topics appear as:

```
/drone1/fmu/out/vehicle_status
/drone1/fmu/out/vehicle_local_position
/drone1/fmu/in/trajectory_setpoint
/drone1/fmu/in/vehicle_command
...
```

Verify with:

```bash
ros2 topic list | grep fmu
```

A single `MicroXRCEAgent udp4 -p 8888` handles all three PX4 clients; the namespace is applied client-side, so the agent does not need any per-drone flags. The drone name used in `PX4_UXRCE_DDS_NS` matches the `<id>` segment of the topic structure documented in [`08-mesh-communication.md`](08-mesh-communication.md) (`/drones/<id>/...`); we re-publish from `/<id>/fmu/...` to `/drones/<id>/...` inside the per-drone agent.

## Launch Script

We bundle this into a single script for the demo:

`scripts/launch_swarm.sh`:

```bash
#!/bin/bash
# Launch the FieldAgent simulation: 3 drones in disaster_zone_v1

set -e

# Single XRCE agent for the whole swarm; per-drone isolation comes from PX4_UXRCE_DDS_NS
MicroXRCEAgent udp4 -p 8888 > /tmp/xrce.log 2>&1 &
XRCE=$!

sleep 2

# Start drone 1 (also launches Gazebo)
cd ~/PX4-Autopilot
PX4_HOME_LAT=34.0000 PX4_HOME_LON=-118.5000 PX4_HOME_ALT=0 \
PX4_UXRCE_DDS_NS=drone1 \
PX4_GZ_WORLD=disaster_zone_v1 \
PX4_GZ_MODEL_POSE="0,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4001 \
./build/px4_sitl_default/bin/px4 -i 1 > /tmp/drone1.log 2>&1 &
DRONE1=$!

sleep 8  # wait for Gazebo to be ready

# Start drone 2
PX4_HOME_LAT=34.0000 PX4_HOME_LON=-118.5000 PX4_HOME_ALT=0 \
PX4_UXRCE_DDS_NS=drone2 \
PX4_GZ_STANDALONE=1 \
PX4_GZ_MODEL_POSE="10,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4001 \
./build/px4_sitl_default/bin/px4 -i 2 > /tmp/drone2.log 2>&1 &
DRONE2=$!

sleep 4

# Start drone 3
PX4_HOME_LAT=34.0000 PX4_HOME_LON=-118.5000 PX4_HOME_ALT=0 \
PX4_UXRCE_DDS_NS=drone3 \
PX4_GZ_STANDALONE=1 \
PX4_GZ_MODEL_POSE="20,0,0.1,0,0,0" \
PX4_SIM_MODEL=gz_x500_mono_cam \
PX4_SYS_AUTOSTART=4001 \
./build/px4_sitl_default/bin/px4 -i 3 > /tmp/drone3.log 2>&1 &
DRONE3=$!

echo "Swarm launched. PIDs: $XRCE $DRONE1 $DRONE2 $DRONE3"
echo "Run 'kill $XRCE $DRONE1 $DRONE2 $DRONE3' to stop."
echo $XRCE $DRONE1 $DRONE2 $DRONE3 > /tmp/fieldagent_swarm.pids
```

## Launching the Agents

After the swarm is up, launch the agent processes:

`scripts/launch_agents.sh`:

```bash
#!/bin/bash
# Launch the per-drone agents and the EGS

cd ~/fieldagent

# Drone agents (all share the single XRCE agent on 8888; per-drone topics are
# distinguished by the uXRCE-DDS namespace, which matches --drone_id)
python3 -m agents.drone_agent --drone_id=drone1 > /tmp/agent_drone1.log 2>&1 &
python3 -m agents.drone_agent --drone_id=drone2 > /tmp/agent_drone2.log 2>&1 &
python3 -m agents.drone_agent --drone_id=drone3 > /tmp/agent_drone3.log 2>&1 &

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

Each drone gets its own Gazebo Harmonic camera topic. The pattern is (note: PX4 zero-indexes the spawned model name even though `-i` is 1-indexed):

```
/world/disaster_zone_v1/model/x500_mono_cam_0/link/camera_link/sensor/imager/image  # drone 1 (-i 1)
/world/disaster_zone_v1/model/x500_mono_cam_1/link/camera_link/sensor/imager/image  # drone 2 (-i 2)
/world/disaster_zone_v1/model/x500_mono_cam_2/link/camera_link/sensor/imager/image  # drone 3 (-i 3)
```

These are Gazebo Transport topics. We need a `ros_gz_bridge` to access them as ROS 2 `sensor_msgs/Image`. The Harmonic-era spec is `<gz-topic>@<ros-msg>[<gz-msg>` (with `[` meaning gz→ros only):

```bash
ros2 run ros_gz_bridge parameter_bridge \
  /world/disaster_zone_v1/model/x500_mono_cam_0/link/camera_link/sensor/imager/image@sensor_msgs/msg/Image[gz.msgs.Image \
  /world/disaster_zone_v1/model/x500_mono_cam_1/link/camera_link/sensor/imager/image@sensor_msgs/msg/Image[gz.msgs.Image \
  /world/disaster_zone_v1/model/x500_mono_cam_2/link/camera_link/sensor/imager/image@sensor_msgs/msg/Image[gz.msgs.Image \
  --ros-args -r /world/disaster_zone_v1/model/x500_mono_cam_0/link/camera_link/sensor/imager/image:=/drones/drone1/camera/image_raw \
             -r /world/disaster_zone_v1/model/x500_mono_cam_1/link/camera_link/sensor/imager/image:=/drones/drone2/camera/image_raw \
             -r /world/disaster_zone_v1/model/x500_mono_cam_2/link/camera_link/sensor/imager/image:=/drones/drone3/camera/image_raw
```

This remaps the verbose Gazebo topic names onto the `/drones/<id>/camera/image_raw` topic structure locked in [`08-mesh-communication.md`](08-mesh-communication.md). Verify the bridge is alive with `ros2 topic hz /drones/drone1/camera/image_raw`.

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
| Second drone doesn't spawn | Check `PX4_GZ_STANDALONE=1` is set on instances 2/3; check Gazebo server is up (`gz topic -l`) |
| Cameras have name collisions | Verify each drone's model name has a unique suffix (`_0`, `_1`, `_2`) |
| ROS 2 `/fmu/...` topics from all drones collide | Confirm `PX4_UXRCE_DDS_NS=droneN` is set on every PX4 process; `ros2 topic list \| grep fmu` should show `/drone1/fmu/...`, `/drone2/fmu/...`, `/drone3/fmu/...` |
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
