"""One-shot discovery of the GeoRide socket.io stream.

Run with: .venv/bin/python tests/discovery_socket.py [DURATION_SECONDS] [MODE]

MODE: header (default), auth, both
"""
from __future__ import annotations

import asyncio
import json
import os
import pprint
import sys
from pathlib import Path

import aiohttp
import socketio


SECRETS = Path(__file__).parent / "secrets.local.env"
if SECRETS.exists():
    for line in SECRETS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

EMAIL = os.environ.get("GEORIDE_EMAIL")
PASSWORD = os.environ.get("GEORIDE_PASSWORD")
DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 60
MODE = sys.argv[2] if len(sys.argv) > 2 else "header"


async def main() -> int:
    if not EMAIL or not PASSWORD:
        print("Missing credentials")
        return 1

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.georide.com/user/login",
            json={"email": EMAIL, "password": PASSWORD},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
    token = data.get("authToken") or data.get("token") or data.get("access_token")
    print(f"[REST] Got token len={len(token)} | MODE={MODE}")

    sio = socketio.AsyncClient(logger=False, engineio_logger=False)
    seen: list[tuple[str, object]] = []

    @sio.event
    async def connect() -> None:
        print(f"[SIO] connected via transport={sio.transport()}")

    @sio.event
    async def disconnect(*args) -> None:  # noqa: ARG001
        print("[SIO] disconnected")

    @sio.event
    async def connect_error(payload) -> None:
        print(f"[SIO] connect_error: {payload}")

    for name in (
        "message",
        "device",
        "position",
        "alarm",
        "refreshTrackersInstruction",
        "lockedPosition",
    ):
        def _make(event_name: str):
            async def _handler(payload):
                seen.append((event_name, payload))
                print(f"\n[{event_name}] {pprint.pformat(payload, compact=True, width=110)}")
            return _handler
        sio.on(name, _make(name))

    @sio.on("*")
    async def catchall(event, *args):
        if event in ("connect", "disconnect"):
            return
        seen.append((f"*:{event}", args))
        print(f"\n[CATCHALL:{event}] args={pprint.pformat(args, compact=True, width=110)}")

    # Variant: auth dict (socket.io v5+ pattern) vs header.
    connect_kwargs = {}
    if MODE in ("auth", "both"):
        connect_kwargs["auth"] = {"token": token}
    if MODE in ("header", "both"):
        connect_kwargs["headers"] = {"token": token}
    # Let socket.io pick the default transport ladder (polling -> upgrade).
    try:
        await sio.connect("https://socket.georide.com", **connect_kwargs)
    except Exception as err:
        print(f"[SIO] connect failed: {err}")
        return 2

    print(f"\nListening for {DURATION}s...\n")
    await asyncio.sleep(DURATION)

    print(f"\n=== Summary: {len(seen)} event(s) received ===")
    counts: dict[str, int] = {}
    for name, _ in seen:
        counts[name] = counts.get(name, 0) + 1
    for name, count in sorted(counts.items()):
        print(f"  {name:32s} x{count}")

    await sio.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
