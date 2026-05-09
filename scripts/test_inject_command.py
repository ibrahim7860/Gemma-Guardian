"""Inject a fake operator command directly into Redis to test the EGS subscription."""
import asyncio
import json
import redis.asyncio as aioredis

async def main():
    r = aioredis.from_url("redis://localhost:6379/0")
    
    cmd = {
        "kind": "operator_command",
        "command_id": "test-inject-001",
        "language": "es",
        "raw_text": "Return drone1 to base immediately",
        "bridge_received_at_iso_ms": "2026-05-09T19:40:00.000Z",
        "contract_version": "1.0.0",
    }
    
    print(f"Publishing to egs.operator_commands: {json.dumps(cmd)}")
    count = await r.publish("egs.operator_commands", json.dumps(cmd))
    print(f"Redis PUBLISH returned subscriber count: {count}")
    
    if count == 0:
        print("[!!] No subscribers on egs.operator_commands! The EGS agent is NOT listening.")
    else:
        print(f"[OK] {count} subscriber(s) received the message. Check your EGS terminal for logs.")
    
    await r.aclose()

asyncio.run(main())
