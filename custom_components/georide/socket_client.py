"""Realtime socket.io client for the GeoRide stream.

GeoRide exposes a socket.io endpoint at https://socket.georide.com that
pushes lock/unlock, position and alarm events as they happen. The REST
polling in `coordinator.py` is still used as the source of truth (and as
a fallback); the socket only fills the latency gap.

The connection is authenticated with the bearer token from /user/login,
passed both as a header (`token`) and as the socket.io `auth` dict —
ptimatth's reference implementation uses the header, but recent
socket.io servers prefer the auth payload, so we send both.

Reconnection is handled by python-socketio automatically with an
exponential backoff. The integration treats socket failures as
informational: polling continues to keep the entities fresh.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import socketio  # type: ignore[import-untyped]

_LOGGER = logging.getLogger(__name__)

SOCKET_URL = "https://socket.georide.com"

# Channels GeoRide pushes on. The list mirrors the reference ptimatth/
# georideapilib implementation; the catch-all handler in this client
# captures anything else the server may emit.
KNOWN_EVENTS: tuple[str, ...] = (
    "message",
    "device",
    "position",
    "alarm",
    "refreshTrackersInstruction",
    "lockedPosition",
)

EventHandler = Callable[[str, Any], Awaitable[None]]


class GeoRideSocketClient:
    """Wrap python-socketio's AsyncClient with GeoRide-specific hooks."""

    def __init__(self, token: str, on_event: EventHandler) -> None:
        self._token = token
        self._on_event = on_event
        self._sio = socketio.AsyncClient(
            reconnection=True,
            reconnection_attempts=0,  # infinite retries
            reconnection_delay=1,
            reconnection_delay_max=60,
            randomization_factor=0.5,
            logger=False,
            engineio_logger=False,
        )
        self._register_handlers()

    def _register_handlers(self) -> None:
        self._sio.on("connect", self._on_connect)
        self._sio.on("disconnect", self._on_disconnect)
        self._sio.on("connect_error", self._on_connect_error)
        for name in KNOWN_EVENTS:
            self._sio.on(name, self._make_named_handler(name))

        @self._sio.on("*")  # type: ignore[untyped-decorator]
        async def _catch_all(event: str, *args: Any) -> None:
            if event in ("connect", "disconnect") or event in KNOWN_EVENTS:
                return
            payload = args[0] if len(args) == 1 else args
            _LOGGER.debug("GeoRide socket [unknown:%s]: %r", event, payload)
            await self._safe_dispatch(event, payload)

    def _make_named_handler(
        self, name: str
    ) -> Callable[[Any], Awaitable[None]]:
        async def _handler(payload: Any = None) -> None:
            _LOGGER.debug("GeoRide socket [%s]: %r", name, payload)
            await self._safe_dispatch(name, payload)
        return _handler

    async def _safe_dispatch(self, event: str, payload: Any) -> None:
        try:
            await self._on_event(event, payload)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("GeoRide socket handler crashed (event=%s)", event)

    async def _on_connect(self) -> None:
        _LOGGER.info("GeoRide socket connected (%s)", SOCKET_URL)

    async def _on_disconnect(self, *args: Any) -> None:
        _LOGGER.info("GeoRide socket disconnected")

    async def _on_connect_error(self, payload: Any) -> None:
        _LOGGER.warning("GeoRide socket connect_error: %s", payload)

    def update_token(self, token: str) -> None:
        """Swap the token for use on the next (re)connection.

        Active sockets keep running on the old token; force a disconnect
        + connect cycle if a re-auth is needed mid-session.
        """
        self._token = token

    async def connect(self) -> None:
        await self._sio.connect(
            SOCKET_URL,
            headers={"token": self._token},
            auth={"token": self._token},
        )

    async def disconnect(self) -> None:
        if self._sio.connected:
            await self._sio.disconnect()

    @property
    def connected(self) -> bool:
        return bool(self._sio.connected)
