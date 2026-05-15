"""Unit tests for the GeoRide socket.io client.

Mocks `socketio.AsyncClient` so we test our own dispatch / lifecycle
logic without ever opening a real socket.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.georide.socket_client import (
    KNOWN_EVENTS,
    GeoRideSocketClient,
)


def _make_client(handler):
    """Build a GeoRideSocketClient with socketio.AsyncClient patched."""
    fake_sio = MagicMock()
    fake_sio.connect = AsyncMock()
    fake_sio.disconnect = AsyncMock()
    fake_sio.connected = False

    on_handlers: dict[str, callable] = {}

    def _on(name, handler=None):
        # Supports both `sio.on(name, fn)` and `@sio.on("*")` styles.
        if handler is not None:
            on_handlers[name] = handler
            return None

        def _decorator(fn):
            on_handlers[name] = fn
            return fn

        return _decorator

    fake_sio.on = _on

    with patch(
        "custom_components.georide.socket_client.socketio.AsyncClient",
        return_value=fake_sio,
    ):
        client = GeoRideSocketClient("token-abc", handler)
    return client, fake_sio, on_handlers


class TestInit:
    def test_registers_lifecycle_and_named_handlers(self):
        events = []

        async def handler(name, payload):
            events.append((name, payload))

        client, sio, on = _make_client(handler)

        # Lifecycle hooks
        assert "connect" in on
        assert "disconnect" in on
        assert "connect_error" in on
        # Known events
        for name in KNOWN_EVENTS:
            assert name in on
        # Catch-all
        assert "*" in on


class TestConnectDisconnect:
    async def test_connect_calls_socketio_with_token(self):
        client, sio, _ = _make_client(AsyncMock())
        await client.connect()
        sio.connect.assert_awaited_once()
        args, kwargs = sio.connect.call_args
        assert args[0] == "https://socket.georide.com"
        assert kwargs["headers"] == {"token": "token-abc"}
        assert kwargs["auth"] == {"token": "token-abc"}

    async def test_disconnect_only_when_connected(self):
        client, sio, _ = _make_client(AsyncMock())
        sio.connected = False
        await client.disconnect()
        sio.disconnect.assert_not_awaited()

        sio.connected = True
        await client.disconnect()
        sio.disconnect.assert_awaited_once()

    def test_connected_property(self):
        client, sio, _ = _make_client(AsyncMock())
        sio.connected = False
        assert client.connected is False
        sio.connected = True
        assert client.connected is True


class TestTokenUpdate:
    def test_update_token_swaps(self):
        client, _, _ = _make_client(AsyncMock())
        assert client._token == "token-abc"
        client.update_token("new-tok")
        assert client._token == "new-tok"


class TestDispatch:
    async def test_known_event_dispatches_to_handler(self):
        received = []

        async def handler(name, payload):
            received.append((name, payload))

        client, _, on = _make_client(handler)
        await on["position"]({"trackerId": 1, "lat": 45.0})
        assert received == [("position", {"trackerId": 1, "lat": 45.0})]

    async def test_handler_exceptions_are_swallowed(self):
        async def boom(name, payload):
            raise RuntimeError("intentional")

        _, _, on = _make_client(boom)
        # Should not raise.
        await on["alarm"]({"type": "vibration"})

    async def test_catchall_ignores_lifecycle_events(self):
        received = []

        async def handler(name, payload):
            received.append((name, payload))

        client, _, on = _make_client(handler)
        # Catch-all skips connect/disconnect.
        await on["*"]("connect")
        await on["*"]("disconnect")
        assert received == []

    async def test_catchall_ignores_known_events(self):
        # Known events are routed by the named handlers, not the catch-all.
        received = []

        async def handler(name, payload):
            received.append((name, payload))

        client, _, on = _make_client(handler)
        await on["*"]("position", {"x": 1})
        # Catch-all should NOT re-dispatch for known events.
        assert received == []

    async def test_catchall_dispatches_unknown_event(self):
        received = []

        async def handler(name, payload):
            received.append((name, payload))

        client, _, on = _make_client(handler)
        await on["*"]("something_new", {"hello": "world"})
        assert received == [("something_new", {"hello": "world"})]

    async def test_catchall_collapses_single_arg_to_payload(self):
        received = []

        async def handler(name, payload):
            received.append((name, payload))

        client, _, on = _make_client(handler)
        # Single positional arg becomes the payload directly.
        await on["*"]("unknown_evt", "string-payload")
        assert received == [("unknown_evt", "string-payload")]

    async def test_catchall_multiple_args_kept_as_tuple(self):
        received = []

        async def handler(name, payload):
            received.append((name, payload))

        client, _, on = _make_client(handler)
        await on["*"]("multi_evt", "a", "b", "c")
        # Multiple args are kept as a tuple to avoid info loss.
        assert received[0][1] == ("a", "b", "c")


class TestLifecycleLogs:
    async def test_connect_handler_runs(self, caplog):
        client, sio, on = _make_client(AsyncMock())
        # Just ensure the connect logger callback runs without raising.
        await on["connect"]()

    async def test_disconnect_handler_runs(self):
        client, sio, on = _make_client(AsyncMock())
        await on["disconnect"]()

    async def test_connect_error_handler_runs(self):
        client, sio, on = _make_client(AsyncMock())
        await on["connect_error"]({"why": "auth"})
