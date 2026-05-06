"""RedisPublisher publishes JSON payloads on Redis channels via the redis-py sync client."""
from __future__ import annotations

import json

import pytest

from agents.drone_agent.redis_io import RedisPublisher


def _drain(pubsub, expected: int = 1, timeout_total: float = 1.0):
    out = []
    deadline_per_call = 0.05
    iterations = int(timeout_total / deadline_per_call)
    for _ in range(iterations):
        msg = pubsub.get_message(timeout=deadline_per_call)
        if msg and msg["type"] == "message":
            out.append(msg["data"])
            if len(out) >= expected:
                break
    return out


def test_publishes_json_payload_on_channel(fake_redis):
    pubsub = fake_redis.pubsub()
    pubsub.subscribe("drones.drone1.findings")
    pubsub.get_message(timeout=0.1)

    pub = RedisPublisher(fake_redis)
    pub.publish("drones.drone1.findings", {"finding_id": "f_drone1_1", "type": "victim"})

    received = _drain(pubsub, expected=1)
    assert len(received) == 1
    payload = json.loads(received[0])
    assert payload["finding_id"] == "f_drone1_1"
    assert payload["type"] == "victim"


def test_publishes_to_multiple_channels(fake_redis):
    p1 = fake_redis.pubsub()
    p1.subscribe("drones.drone1.findings")
    p2 = fake_redis.pubsub()
    p2.subscribe("swarm.broadcasts.drone1")
    p1.get_message(timeout=0.1)
    p2.get_message(timeout=0.1)

    pub = RedisPublisher(fake_redis)
    pub.publish("drones.drone1.findings", {"a": 1})
    pub.publish("swarm.broadcasts.drone1", {"b": 2})

    assert json.loads(_drain(p1, expected=1)[0]) == {"a": 1}
    assert json.loads(_drain(p2, expected=1)[0]) == {"b": 2}


def test_close_is_idempotent(fake_redis):
    pub = RedisPublisher(fake_redis)
    pub.close()
    pub.close()  # must not raise
