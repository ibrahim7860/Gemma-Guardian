"""Minimal Ollama /api/chat mock for CI-friendly drone agent e2e tests.

Returns a canned report_finding tool call for the first request, then
continue_mission afterwards. Lets a real drone agent process publish a
real Contract-4 finding without needing a GPU or a Gemma 4 download.
"""
from __future__ import annotations

import argparse
import json

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI()
_call_count = {"n": 0}


@app.post("/api/chat")
async def chat(request: Request) -> dict:
    _call_count["n"] += 1
    if _call_count["n"] == 1:
        # First step: report a victim finding.
        return {
            "message": {
                "tool_calls": [{
                    "function": {
                        "name": "report_finding",
                        "arguments": json.dumps({
                            "type": "victim",
                            "severity": 4,
                            "gps_lat": 34.0005,
                            "gps_lon": -118.5003,
                            "confidence": 0.78,
                            "visual_description": "person prone in rubble, partial cover",
                        }),
                    },
                }],
            },
        }
    return {
        "message": {
            "tool_calls": [{
                "function": {"name": "continue_mission", "arguments": "{}"},
            }],
        },
    }


@app.get("/api/tags")
async def tags() -> dict:
    return {"models": [{"name": "gemma4:e2b"}, {"name": "gemma4:e4b"}]}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=11434)
    args = p.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
