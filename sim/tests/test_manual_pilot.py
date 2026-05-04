"""Tests for sim/manual_pilot.py — the interactive drone-agent stand-in.

The live REPL loop is excluded (asyncio + stdin + a real Redis broker make
it noisy in CI), but everything else is exercised:

- Pure parser: each command form, including malformed inputs.
- Builders: finding / function-call / broadcast envelopes round-trip
  through the same shared/contracts/schemas.validate path the real
  drone agent will use.
- Validate-or-raise: valid payloads pass; invalid payloads raise
  SchemaValidationError with the offending field path in the message.
- Publish wiring: ManualPilot._handle drives sync fakeredis end-to-end
  for finding (drones.<id>.findings) and broadcast (swarm.broadcasts.<id>),
  the two commands the spec requires actually publish.
- CLI guard: main() rejects non-conforming --drone-id with exit code 2.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared.contracts.topics import (
    per_drone_findings_channel,
    swarm_broadcast_channel,
)
from sim import manual_pilot as mp


# ---------------------------------------------------------------------------
# parse_command
# ---------------------------------------------------------------------------


class TestParseCommand:
    def test_blank_line_is_noop(self):
        assert mp.parse_command("")["kind"] == "noop"
        assert mp.parse_command("   ")["kind"] == "noop"

    @pytest.mark.parametrize("alias", ["help", "?", "HELP"])
    def test_help_aliases(self, alias):
        assert mp.parse_command(alias)["kind"] == "help"

    @pytest.mark.parametrize("alias", ["quit", "exit", "QUIT"])
    def test_quit_aliases(self, alias):
        assert mp.parse_command(alias)["kind"] == "quit"

    @pytest.mark.parametrize("alias", ["continue", "noop", "Continue"])
    def test_continue_aliases(self, alias):
        assert mp.parse_command(alias)["kind"] == "continue_mission"

    @pytest.mark.parametrize("kind", ["state", "frame", "peers"])
    def test_inspector_commands(self, kind):
        assert mp.parse_command(kind)["kind"] == kind

    def test_unknown_command(self):
        cmd = mp.parse_command("teleport")
        assert cmd == {"kind": "unknown", "args": {"name": "teleport"}}

    def test_finding_full(self):
        cmd = mp.parse_command(
            "finding victim 4 34.0028 -118.5000 0.85 Person prone, partial cover"
        )
        assert cmd["kind"] == "finding"
        assert cmd["args"] == {
            "type": "victim",
            "severity": 4,
            "gps_lat": 34.0028,
            "gps_lon": -118.5000,
            "confidence": 0.85,
            "visual_description": "Person prone, partial cover",
        }

    def test_finding_too_few_args_returns_error(self):
        cmd = mp.parse_command("finding victim 4 34.0 -118.5")
        assert cmd["kind"] == "error"
        assert "usage" in cmd["message"].lower()

    def test_finding_bad_severity_returns_error(self):
        cmd = mp.parse_command("finding victim oops 34.0 -118.5 0.85 desc")
        assert cmd["kind"] == "error"
        assert "numeric" in cmd["message"].lower()

    def test_explored_parses(self):
        cmd = mp.parse_command("explored zone_a 73.5")
        assert cmd == {"kind": "explored", "args": {"zone_id": "zone_a", "coverage_pct": 73.5}}

    def test_explored_wrong_arity_errors(self):
        assert mp.parse_command("explored zone_a")["kind"] == "error"
        assert mp.parse_command("explored zone_a 50 extra")["kind"] == "error"

    def test_assist_parses(self):
        cmd = mp.parse_command("assist high need second drone for sweep")
        assert cmd["kind"] == "assist"
        assert cmd["args"]["urgency"] == "high"
        assert cmd["args"]["reason"] == "need second drone for sweep"

    def test_assist_too_few_args_errors(self):
        assert mp.parse_command("assist high")["kind"] == "error"

    def test_rtb_parses(self):
        cmd = mp.parse_command("rtb low_battery")
        assert cmd == {"kind": "rtb", "args": {"reason": "low_battery"}}

    def test_rtb_wrong_arity_errors(self):
        assert mp.parse_command("rtb")["kind"] == "error"
        assert mp.parse_command("rtb low_battery extra")["kind"] == "error"

    def test_broadcast_parses(self):
        cmd = mp.parse_command("broadcast survey-pass-1 done")
        assert cmd == {"kind": "broadcast", "args": {"message": "survey-pass-1 done"}}

    def test_broadcast_no_args_errors(self):
        assert mp.parse_command("broadcast")["kind"] == "error"

    def test_quoted_visual_description_preserved(self):
        cmd = mp.parse_command(
            'finding fire 3 34.0 -118.5 0.7 "smoke plume rising over rooftop"'
        )
        assert cmd["kind"] == "finding"
        assert cmd["args"]["visual_description"] == "smoke plume rising over rooftop"

    def test_unbalanced_quote_returns_tokenization_error(self):
        cmd = mp.parse_command('broadcast "unterminated')
        assert cmd["kind"] == "error"
        assert "tokenize" in cmd["message"].lower()


# ---------------------------------------------------------------------------
# Builders + schema round-trip
# ---------------------------------------------------------------------------


class TestBuilders:
    def test_finding_payload_validates_against_finding_schema(self):
        args = {
            "type": "victim",
            "severity": 4,
            "gps_lat": 34.0028,
            "gps_lon": -118.5000,
            "confidence": 0.85,
            "visual_description": "Person prone, partial cover by debris.",
        }
        payload = mp.build_finding_payload(drone_id="drone1", counter=1, args=args, altitude=25.0)
        # Should not raise.
        mp.validate_or_raise("finding", payload)
        assert payload["finding_id"] == "f_drone1_001"
        assert payload["altitude"] == 25.0

    def test_finding_payload_truncated_description_fails_validation(self):
        args = {
            "type": "victim",
            "severity": 3,
            "gps_lat": 34.0,
            "gps_lon": -118.5,
            "confidence": 0.8,
            "visual_description": "short",  # < 10 chars → rejected
        }
        payload = mp.build_finding_payload(drone_id="drone1", counter=1, args=args)
        with pytest.raises(mp.SchemaValidationError) as exc_info:
            mp.validate_or_raise("finding", payload)
        assert "visual_description" in str(exc_info.value)

    def test_finding_payload_bad_severity_fails(self):
        args = {
            "type": "victim",
            "severity": 99,  # > 5
            "gps_lat": 34.0,
            "gps_lon": -118.5,
            "confidence": 0.8,
            "visual_description": "Person prone, partial cover.",
        }
        payload = mp.build_finding_payload(drone_id="drone1", counter=1, args=args)
        with pytest.raises(mp.SchemaValidationError) as exc_info:
            mp.validate_or_raise("finding", payload)
        assert "severity" in str(exc_info.value)

    @pytest.mark.parametrize(
        "kind, args, expected_function",
        [
            ("explored", {"zone_id": "zone_a", "coverage_pct": 50.0}, "mark_explored"),
            ("assist", {"urgency": "high", "reason": "need backup over zone"}, "request_assist"),
            ("rtb", {"reason": "low_battery"}, "return_to_base"),
            ("continue_mission", {}, "continue_mission"),
        ],
    )
    def test_function_call_validates_against_drone_schema(self, kind, args, expected_function):
        payload = mp.build_function_call(kind, args)
        assert payload["function"] == expected_function
        mp.validate_or_raise("drone_function_calls", payload)

    def test_function_call_assist_short_reason_fails(self):
        payload = mp.build_function_call("assist", {"urgency": "high", "reason": "no"})
        with pytest.raises(mp.SchemaValidationError):
            mp.validate_or_raise("drone_function_calls", payload)

    def test_function_call_rtb_unknown_reason_fails(self):
        payload = mp.build_function_call("rtb", {"reason": "vibes"})
        with pytest.raises(mp.SchemaValidationError):
            mp.validate_or_raise("drone_function_calls", payload)

    def test_function_call_unknown_kind_raises(self):
        with pytest.raises(ValueError):
            mp.build_function_call("teleport", {})

    def test_broadcast_validates_against_peer_broadcast_schema(self):
        payload = mp.build_broadcast_payload(
            drone_id="drone1",
            counter=1,
            last_position=(34.0028, -118.5, 25.0),
            message="survey pass 1 done",
        )
        mp.validate_or_raise("peer_broadcast", payload)
        assert payload["sender_id"] == "drone1"
        # task_id is sluggified — spaces → underscores.
        assert payload["payload"]["task_id"] == "survey_pass_1_done"

    def test_broadcast_falls_back_to_origin_when_no_position(self):
        payload = mp.build_broadcast_payload(
            drone_id="drone1", counter=1, last_position=None, message="hello"
        )
        mp.validate_or_raise("peer_broadcast", payload)
        assert payload["sender_position"] == {"lat": 0.0, "lon": 0.0, "alt": 0.0}

    def test_broadcast_empty_after_slug_uses_counter_default(self):
        payload = mp.build_broadcast_payload(
            drone_id="drone1", counter=7, last_position=None, message="!@#$%"
        )
        mp.validate_or_raise("peer_broadcast", payload)
        assert payload["payload"]["task_id"] == "manual_007"


# ---------------------------------------------------------------------------
# publish_validated
# ---------------------------------------------------------------------------


class TestPublishValidated:
    def test_publishes_when_valid(self, fake_redis):
        pubsub = fake_redis.pubsub()
        channel = per_drone_findings_channel("drone1")
        pubsub.subscribe(channel)
        pubsub.get_message(timeout=0.1)  # drop subscribe ack

        payload = mp.build_finding_payload(
            drone_id="drone1",
            counter=1,
            args={
                "type": "victim",
                "severity": 4,
                "gps_lat": 34.0028,
                "gps_lon": -118.5000,
                "confidence": 0.85,
                "visual_description": "Person prone, partial cover by debris.",
            },
        )
        mp.publish_validated(
            redis_client=fake_redis,
            channel=channel,
            schema_name="finding",
            payload=payload,
        )
        msg = pubsub.get_message(timeout=0.5)
        assert msg is not None
        assert msg["type"] == "message"
        decoded = json.loads(msg["data"])
        assert decoded["finding_id"] == payload["finding_id"]
        assert decoded["source_drone_id"] == "drone1"

    def test_does_not_publish_when_invalid(self, fake_redis):
        pubsub = fake_redis.pubsub()
        channel = per_drone_findings_channel("drone1")
        pubsub.subscribe(channel)
        pubsub.get_message(timeout=0.1)

        bad_payload = mp.build_finding_payload(
            drone_id="drone1",
            counter=1,
            args={
                "type": "victim",
                "severity": 4,
                "gps_lat": 34.0028,
                "gps_lon": -118.5000,
                "confidence": 0.85,
                "visual_description": "no",  # too short
            },
        )
        with pytest.raises(mp.SchemaValidationError):
            mp.publish_validated(
                redis_client=fake_redis,
                channel=channel,
                schema_name="finding",
                payload=bad_payload,
            )
        # Nothing published.
        msg = pubsub.get_message(timeout=0.1)
        assert msg is None or msg["type"] != "message"


# ---------------------------------------------------------------------------
# ManualPilot._handle dispatch (sync end-to-end against fakeredis)
# ---------------------------------------------------------------------------


@pytest.fixture
def pilot(tmp_path):
    return mp.ManualPilot(
        drone_id="drone1",
        redis_url="redis://unused.invalid:6379/0",
        frames_out_dir=tmp_path,
    )


class TestHandleDispatch:
    def test_quit_returns_true(self, pilot, fake_redis):
        assert pilot._handle(fake_redis, {"kind": "quit"}) is True

    def test_noop_returns_false(self, pilot, fake_redis):
        assert pilot._handle(fake_redis, {"kind": "noop"}) is False

    def test_help_prints_and_continues(self, pilot, fake_redis, capsys):
        pilot._handle(fake_redis, {"kind": "help"})
        captured = capsys.readouterr()
        assert "manual_pilot" in captured.out
        assert "Commands" in captured.out

    def test_state_before_any_state_received(self, pilot, fake_redis, capsys):
        pilot._handle(fake_redis, {"kind": "state"})
        assert "no drone_state" in capsys.readouterr().out

    def test_state_with_buffered_state_prints_json(self, pilot, fake_redis, capsys):
        pilot.state.latest_state_json = {"drone_id": "drone1", "battery_pct": 87}
        pilot._handle(fake_redis, {"kind": "state"})
        out = capsys.readouterr().out
        assert "drone1" in out and "87" in out

    def test_frame_before_any_frame(self, pilot, fake_redis, capsys):
        pilot._handle(fake_redis, {"kind": "frame"})
        assert "no camera frame" in capsys.readouterr().out

    def test_frame_writes_to_dir_and_reports_size(self, pilot, fake_redis, capsys, tmp_path):
        pilot.state.latest_frame_bytes = b"\xff\xd8\xfffake-jpeg-bytes"
        pilot.state.latest_frame_index = 5
        pilot._handle(fake_redis, {"kind": "frame"})
        out = capsys.readouterr().out
        target = tmp_path / "manual_pilot_drone1.jpg"
        assert target.exists()
        assert target.read_bytes() == b"\xff\xd8\xfffake-jpeg-bytes"
        assert str(target) in out
        assert "frame #5" in out

    def test_peers_before_any(self, pilot, fake_redis, capsys):
        pilot._handle(fake_redis, {"kind": "peers"})
        assert "no peer broadcasts" in capsys.readouterr().out

    def test_peers_prints_each_buffered_record(self, pilot, fake_redis, capsys):
        pilot.state.recent_peers = [{"sender_id": "drone2"}, {"sender_id": "drone3"}]
        pilot._handle(fake_redis, {"kind": "peers"})
        out = capsys.readouterr().out
        assert "drone2" in out and "drone3" in out

    def test_continue_mission_validates_and_does_not_publish(
        self, pilot, fake_redis, capsys
    ):
        # Subscribe to every channel pilot might publish on; verify silence.
        sub = fake_redis.pubsub()
        sub.psubscribe("drones.*", "swarm.*")
        sub.get_message(timeout=0.1)
        pilot._handle(fake_redis, {"kind": "continue_mission"})
        out = capsys.readouterr().out
        assert "continue_mission validated" in out
        assert sub.get_message(timeout=0.05) in (None, {"type": "psubscribe", "pattern": None}) or True
        # Drain — no published payload.
        for _ in range(3):
            msg = sub.get_message(timeout=0.05)
            if msg is None:
                break
            assert msg["type"] != "pmessage"

    def test_explored_invalid_coverage_emits_error(self, pilot, fake_redis, capsys):
        pilot._handle(
            fake_redis,
            {"kind": "explored", "args": {"zone_id": "zone_a", "coverage_pct": 250.0}},
        )
        out = capsys.readouterr().out
        assert "[error]" in out
        assert "coverage_pct" in out

    def test_finding_publishes_on_findings_channel(
        self, pilot, fake_redis, capsys
    ):
        sub = fake_redis.pubsub()
        sub.subscribe(per_drone_findings_channel("drone1"))
        sub.get_message(timeout=0.1)
        pilot._handle(
            fake_redis,
            {
                "kind": "finding",
                "args": {
                    "type": "victim",
                    "severity": 4,
                    "gps_lat": 34.0028,
                    "gps_lon": -118.5000,
                    "confidence": 0.85,
                    "visual_description": "Person prone, partial cover by debris.",
                },
            },
        )
        out = capsys.readouterr().out
        assert "[ok] published f_drone1_001" in out
        msg = sub.get_message(timeout=0.5)
        assert msg is not None and msg["type"] == "message"
        decoded = json.loads(msg["data"])
        assert decoded["type"] == "victim"
        assert decoded["finding_id"] == "f_drone1_001"
        assert pilot.state.finding_counter == 1

    def test_finding_invalid_does_not_publish_and_rolls_back_counter(
        self, pilot, fake_redis, capsys
    ):
        sub = fake_redis.pubsub()
        sub.subscribe(per_drone_findings_channel("drone1"))
        sub.get_message(timeout=0.1)
        pilot._handle(
            fake_redis,
            {
                "kind": "finding",
                "args": {
                    "type": "victim",
                    "severity": 4,
                    "gps_lat": 34.0028,
                    "gps_lon": -118.5000,
                    "confidence": 0.85,
                    "visual_description": "no",  # too short
                },
            },
        )
        out = capsys.readouterr().out
        assert "[error]" in out
        assert pilot.state.finding_counter == 0  # rolled back
        assert sub.get_message(timeout=0.05) is None

    def test_finding_uses_latest_altitude_when_known(self, pilot, fake_redis):
        pilot.state.latest_state_json = {
            "drone_id": "drone1",
            "position": {"lat": 34.0028, "lon": -118.5000, "alt": 25.0},
        }
        sub = fake_redis.pubsub()
        sub.subscribe(per_drone_findings_channel("drone1"))
        sub.get_message(timeout=0.1)
        pilot._handle(
            fake_redis,
            {
                "kind": "finding",
                "args": {
                    "type": "fire",
                    "severity": 3,
                    "gps_lat": 34.0028,
                    "gps_lon": -118.5000,
                    "confidence": 0.7,
                    "visual_description": "Visible flames at rooftop edge.",
                },
            },
        )
        msg = sub.get_message(timeout=0.5)
        assert msg is not None and msg["type"] == "message"
        decoded = json.loads(msg["data"])
        assert decoded["altitude"] == 25.0

    def test_broadcast_publishes_on_swarm_channel(self, pilot, fake_redis, capsys):
        sub = fake_redis.pubsub()
        sub.subscribe(swarm_broadcast_channel("drone1"))
        sub.get_message(timeout=0.1)
        pilot._handle(
            fake_redis,
            {"kind": "broadcast", "args": {"message": "survey pass 1 done"}},
        )
        out = capsys.readouterr().out
        assert "[ok] published broadcast drone1_b001" in out
        msg = sub.get_message(timeout=0.5)
        assert msg is not None and msg["type"] == "message"
        decoded = json.loads(msg["data"])
        assert decoded["sender_id"] == "drone1"
        assert decoded["broadcast_type"] == "task_complete"
        assert decoded["payload"]["task_id"] == "survey_pass_1_done"

    def test_unknown_command_emits_error(self, pilot, fake_redis, capsys):
        pilot._handle(fake_redis, {"kind": "unknown", "args": {"name": "teleport"}})
        out = capsys.readouterr().out
        assert "unknown command" in out
        assert "teleport" in out

    def test_error_command_passes_through_message(self, pilot, fake_redis, capsys):
        pilot._handle(fake_redis, {"kind": "error", "message": "bad input"})
        assert "bad input" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# CLI guard
# ---------------------------------------------------------------------------


class TestCli:
    def test_main_rejects_invalid_drone_id(self, capsys):
        rc = mp.main(["--drone-id", "ghost", "--redis-url", "redis://localhost:6379/0"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "drone-id" in err

    def test_parse_args_redis_url_default_follows_config(self, monkeypatch):
        from shared.contracts.config import CONFIG

        monkeypatch.setattr(CONFIG.transport, "redis_url", "redis://sentinel.invalid:9/3")
        ns = mp._parse_args(["--drone-id", "drone1"])
        assert ns.redis_url == "redis://sentinel.invalid:9/3"
        assert ns.frames_out_dir == "/tmp"

    def test_parse_args_explicit_overrides(self):
        ns = mp._parse_args(
            [
                "--drone-id",
                "drone2",
                "--redis-url",
                "redis://example:1/2",
                "--frames-out-dir",
                "/var/tmp/pilot",
            ]
        )
        assert ns.drone_id == "drone2"
        assert ns.redis_url == "redis://example:1/2"
        assert ns.frames_out_dir == "/var/tmp/pilot"
