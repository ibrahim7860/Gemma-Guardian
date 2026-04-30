"""Codegen freshness gate + concrete channel-helper outputs."""
import subprocess
import sys

from shared.contracts import topics


def test_codegen_is_fresh():
    result = subprocess.run(
        [sys.executable, "-m", "scripts.gen_topic_constants", "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"stale generated files:\n{result.stderr}"


def test_per_drone_helpers_substitute_drone_id():
    assert topics.per_drone_state_channel("drone1") == "drones.drone1.state"
    assert topics.per_drone_findings_channel("drone7") == "drones.drone7.findings"
    assert topics.swarm_broadcast_channel("drone2") == "swarm.broadcasts.drone2"
    assert topics.swarm_visible_to_channel("drone3") == "swarm.drone3.visible_to.drone3"


def test_egs_constants_are_correct():
    assert topics.EGS_STATE == "egs.state"
    assert topics.WS_ENDPOINT == "ws://localhost:9090"
    assert topics.WS_SCHEMA == "websocket_messages"
