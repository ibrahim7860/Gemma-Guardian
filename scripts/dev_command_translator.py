#!/usr/bin/env python3
"""Phase 4 stub EGS: subscribe to egs.operator_commands, publish translations
to egs.command_translations with hard-coded substring matching.

Stand-in for Qasim's real Gemma 4 E4B translator. Identical Redis contract
on both sides — drop-in replaceable.

Usage:
    PYTHONPATH=. python3 scripts/dev_command_translator.py
    PYTHONPATH=. python3 scripts/dev_command_translator.py --redis-url redis://localhost:6379
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import redis.asyncio as redis_async

from shared.contracts import VERSION, validate
from shared.contracts.topics import EGS_COMMAND_TRANSLATIONS, EGS_OPERATOR_COMMANDS

_ZONE_PATTERNS = [
    (re.compile(r"\b(north|south|east|west|central)\b", re.IGNORECASE), 1),
    (re.compile(r"zona\s+(norte|sur|este|oeste|central)", re.IGNORECASE), 1),
]
_ZONE_TRANSLATE = {
    "norte": "north",
    "sur": "south",
    "este": "east",
    "oeste": "west",
    "central": "central",
}

_DRONE_PATTERN = re.compile(r"\b(drone\d+)\b", re.IGNORECASE)

# Adversarial finding #9: full-word matches only. Bare "concentr" was matching
# concentric / concentration. Spanish "concéntrate" is handled via NFKD
# normalization in _fold so the operator typing the accent (or not) is the
# same matcher input.
_RECALL_VERBS = ("recall", "regresa", "vuelve")
_RESTRICT_VERBS = ("restrict", "focus", "concentrate")  # NOT "concentr"
_EXCLUDE_VERBS = ("exclude", "avoid", "evita")


def _now_iso_ms() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _fold(text: str) -> str:
    """Lowercase + strip accent marks via NFKD decomposition.

    Adversarial finding #9: an operator typing "concéntrate" (with accent) and
    "concentrate" (without) should match the same intent. NFKD splits each
    accented character into a base + combining mark; we drop the marks.
    """
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _has_word(text: str, words: tuple) -> bool:
    """True iff any of `words` appears as a full word (\\b boundaries)."""
    for w in words:
        if re.search(rf"\b{re.escape(w)}\b", text):
            return True
    return False


def _detect_zone(text: str) -> Optional[str]:
    for pat, group in _ZONE_PATTERNS:
        m = pat.search(text)
        if m:
            value = m.group(group).lower()
            return _ZONE_TRANSLATE.get(value, value)
    return None


def _detect_drone(text: str) -> Optional[str]:
    m = _DRONE_PATTERN.search(text)
    return m.group(1).lower() if m else None


def _intent_from_text(text: str) -> Tuple[str, Dict[str, Any]]:
    """Return (command, args) for the matched intent, or unknown_command.

    Word-boundary + accent-folded matching prevents false positives like
    "concentric" → restrict_zone.
    """
    folded = _fold(text)
    drone = _detect_drone(folded)
    zone = _detect_zone(folded)

    if _has_word(folded, _RECALL_VERBS):
        if drone:
            return "recall_drone", {"drone_id": drone, "reason": "operator request"}

    if _has_word(folded, _RESTRICT_VERBS):
        if zone:
            return "restrict_zone", {"zone_id": zone}

    if _has_word(folded, _EXCLUDE_VERBS):
        if zone:
            return "exclude_zone", {"zone_id": zone}

    return "unknown_command", {
        "operator_text": text,
        "suggestion": "Try 'recall drone1' or 'focus on zone east'",
    }


def build_translation(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Pure function: take an operator_commands_envelope, return a
    command_translations_envelope. Exposed for unit tests."""
    cid = envelope["command_id"]
    raw = envelope["raw_text"]
    command, args = _intent_from_text(raw)
    structured = {"command": command, "args": args}
    valid = command != "unknown_command"

    if valid:
        if command == "recall_drone":
            preview = f"Will recall {args['drone_id']}: {args['reason']}"
        elif command == "restrict_zone":
            preview = f"Will restrict mission to zone '{args['zone_id']}'"
        elif command == "exclude_zone":
            preview = f"Will exclude zone '{args['zone_id']}'"
        else:
            preview = f"Will execute {command}"
    else:
        preview = "Command not understood"

    # Stub does not actually translate the preview into other languages.
    # Qasim's real EGS replaces this with Gemma 4 output.
    preview_local = preview

    return {
        "kind": "command_translation",
        "command_id": cid,
        "structured": structured,
        "valid": valid,
        "preview_text": preview,
        "preview_text_in_operator_language": preview_local,
        "egs_published_at_iso_ms": _now_iso_ms(),
        "contract_version": VERSION,
    }


async def _run(redis_url: str) -> None:
    client = redis_async.Redis.from_url(redis_url)
    pubsub = client.pubsub()
    await pubsub.subscribe(EGS_OPERATOR_COMMANDS)
    print(
        f"[stub-egs] subscribed to {EGS_OPERATOR_COMMANDS} on {redis_url}",
        file=sys.stderr,
    )
    try:
        while True:
            msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if msg is None:
                continue
            data = msg.get("data")
            if isinstance(data, (bytes, bytearray)):
                raw = bytes(data).decode("utf-8", errors="replace")
            else:
                raw = str(data)
            try:
                envelope = json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"[stub-egs] INVALID json: {exc}", file=sys.stderr)
                continue
            outcome = validate("operator_commands_envelope", envelope)
            if not outcome.valid:
                print(
                    f"[stub-egs] INVALID envelope: {[e.message for e in outcome.errors][:2]}",
                    file=sys.stderr,
                )
                continue

            translation = build_translation(envelope)
            t_outcome = validate("command_translations_envelope", translation)
            if not t_outcome.valid:
                print(
                    f"[stub-egs] BUG: produced invalid translation: {[e.message for e in t_outcome.errors][:2]}",
                    file=sys.stderr,
                )
                continue

            await client.publish(
                EGS_COMMAND_TRANSLATIONS, json.dumps(translation),
            )
            print(
                f"[stub-egs] cid={envelope['command_id']} raw={envelope['raw_text']!r} "
                f"-> {translation['structured']['command']}"
            )
    finally:
        try:
            await pubsub.unsubscribe()
        finally:
            await pubsub.aclose()
            await client.aclose()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--redis-url", default="redis://localhost:6379")
    args = p.parse_args()
    try:
        asyncio.run(_run(args.redis_url))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
