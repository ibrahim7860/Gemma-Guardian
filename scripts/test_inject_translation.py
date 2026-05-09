"""Inject a PERFECT translation directly into egs.command_translations."""
import asyncio
import json
import redis.asyncio as aioredis

async def main():
    r = aioredis.from_url("redis://localhost:6379/0")

    # Exactly matches exclude_zone schema: only zone_id, no reason
    translation = {
        "kind": "command_translation",
        "command_id": "test-perfect-001",
        "structured": {
            "command": "exclude_zone",
            "args": {
                "zone_id": "alpha"
            }
        },
        "valid": True,
        "preview_text": "Exclude zone alpha from drone operations.",
        "preview_text_in_operator_language": "Excluir zona alfa de operaciones de drones.",
        "egs_published_at_iso_ms": "2026-05-09T19:49:00.000Z",
        "contract_version": "1.0.0",
    }

    print(f"Publishing PERFECT translation to egs.command_translations:")
    print(json.dumps(translation, indent=2))
    count = await r.publish("egs.command_translations", json.dumps(translation))
    print(f"\nRedis PUBLISH subscriber count: {count}")
    
    if count == 0:
        print("[FAIL] No subscribers!")
    else:
        print(f"[OK] {count} subscriber(s). Check Flutter dashboard NOW.")

    await r.aclose()

asyncio.run(main())
