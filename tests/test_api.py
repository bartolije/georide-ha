"""Unit tests for the GeoRide REST client with aiohttp fully mocked.

These complement test_api_live.py (which talks to the real server). The
mocked variants stay fast and cover every error branch without burning
real API quota.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp import ClientResponseError, ClientError

from custom_components.georide.api import (
    GeoRideApiClient,
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
)


# ---------------------------------------------------------------------------
# Helpers — build mock aiohttp.ClientSession + responses
# ---------------------------------------------------------------------------
def _response(status=200, json_body=None, *, raise_for_status_error=None):
    """Build a fake aiohttp response usable as an async context manager."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_body)

    def _rfs():
        if raise_for_status_error is not None:
            raise raise_for_status_error
        if 400 <= status < 600:
            raise ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=status,
                message=f"HTTP {status}",
            )

    resp.raise_for_status = _rfs
    return resp


def _session(*, post_response=None, get_response=None, post_raises=None, get_raises=None):
    """Build a fake ClientSession whose post/get returns the configured response."""
    session = MagicMock(spec=aiohttp.ClientSession)

    @asynccontextmanager
    async def _post(*args, **kwargs):
        if post_raises is not None:
            raise post_raises
        yield post_response

    @asynccontextmanager
    async def _get(*args, **kwargs):
        if get_raises is not None:
            raise get_raises
        yield get_response

    session.post = _post
    session.get = _get
    return session


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------
class TestLogin:
    async def test_returns_token_from_authToken(self):
        session = _session(post_response=_response(200, {"authToken": "abc"}))
        client = GeoRideApiClient(session)
        assert await client.login("u", "p") == "abc"
        assert client.token == "abc"

    async def test_falls_back_to_token_key(self):
        session = _session(post_response=_response(200, {"token": "xyz"}))
        client = GeoRideApiClient(session)
        assert await client.login("u", "p") == "xyz"

    async def test_falls_back_to_access_token_key(self):
        session = _session(post_response=_response(200, {"access_token": "k"}))
        client = GeoRideApiClient(session)
        assert await client.login("u", "p") == "k"

    async def test_401_raises_auth_error(self):
        session = _session(post_response=_response(401, {}))
        with pytest.raises(GeoRideAuthError):
            await GeoRideApiClient(session).login("u", "p")

    async def test_403_raises_auth_error(self):
        session = _session(post_response=_response(403, {}))
        with pytest.raises(GeoRideAuthError):
            await GeoRideApiClient(session).login("u", "p")

    async def test_500_raises_connection_error(self):
        session = _session(post_response=_response(500, {}))
        with pytest.raises(GeoRideConnectionError):
            await GeoRideApiClient(session).login("u", "p")

    async def test_client_error_raises_connection_error(self):
        session = _session(post_raises=ClientError("dns"))
        with pytest.raises(GeoRideConnectionError):
            await GeoRideApiClient(session).login("u", "p")

    async def test_response_not_dict_raises(self):
        session = _session(post_response=_response(200, ["unexpected", "list"]))
        with pytest.raises(GeoRideError):
            await GeoRideApiClient(session).login("u", "p")

    async def test_no_token_field_raises_auth_error(self):
        session = _session(post_response=_response(200, {"unexpected": "shape"}))
        with pytest.raises(GeoRideAuthError):
            await GeoRideApiClient(session).login("u", "p")


# ---------------------------------------------------------------------------
# Authenticated GETs (get_trackers / get_trips / get_tracker_beacons)
# ---------------------------------------------------------------------------
class TestGetTrackers:
    async def test_returns_list(self):
        session = _session(get_response=_response(200, [{"trackerId": 1}]))
        client = GeoRideApiClient(session, token="t")
        assert await client.get_trackers() == [{"trackerId": 1}]

    async def test_missing_token_raises(self):
        session = _session()
        with pytest.raises(GeoRideAuthError):
            await GeoRideApiClient(session).get_trackers()

    async def test_401_raises_auth(self):
        session = _session(get_response=_response(401, {}))
        with pytest.raises(GeoRideAuthError):
            await GeoRideApiClient(session, token="t").get_trackers()

    async def test_500_raises_connection(self):
        session = _session(get_response=_response(500, {}))
        with pytest.raises(GeoRideConnectionError):
            await GeoRideApiClient(session, token="t").get_trackers()

    async def test_client_error_raises_connection(self):
        session = _session(get_raises=ClientError("dns"))
        with pytest.raises(GeoRideConnectionError):
            await GeoRideApiClient(session, token="t").get_trackers()

    async def test_non_list_response_raises(self):
        session = _session(get_response=_response(200, {"oops": True}))
        with pytest.raises(GeoRideError):
            await GeoRideApiClient(session, token="t").get_trackers()


class TestGetTrips:
    async def test_returns_list(self):
        session = _session(get_response=_response(200, [{"id": 1}]))
        client = GeoRideApiClient(session, token="t")
        out = await client.get_trips(7, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        assert out == [{"id": 1}]

    async def test_auth_error(self):
        session = _session(get_response=_response(403, {}))
        with pytest.raises(GeoRideAuthError):
            await GeoRideApiClient(session, token="t").get_trips(1, "a", "b")


class TestGetMaintenance:
    async def test_unwraps_maintenanceList(self):
        session = _session(
            get_response=_response(200, {"maintenanceList": [{"id": 1}, {"id": 2}]})
        )
        client = GeoRideApiClient(session, token="t")
        out = await client.get_maintenance(5)
        assert out == [{"id": 1}, {"id": 2}]

    async def test_non_dict_response_raises(self):
        session = _session(get_response=_response(200, ["not", "dict"]))
        with pytest.raises(GeoRideError):
            await GeoRideApiClient(session, token="t").get_maintenance(5)

    async def test_non_list_inner_raises(self):
        session = _session(get_response=_response(200, {"maintenanceList": "oops"}))
        with pytest.raises(GeoRideError):
            await GeoRideApiClient(session, token="t").get_maintenance(5)

    async def test_missing_token_raises(self):
        session = _session()
        with pytest.raises(GeoRideAuthError):
            await GeoRideApiClient(session).get_maintenance(5)

    async def test_auth_error_propagates(self):
        session = _session(get_response=_response(401, {}))
        with pytest.raises(GeoRideAuthError):
            await GeoRideApiClient(session, token="t").get_maintenance(5)

    async def test_connection_error_propagates(self):
        session = _session(get_raises=ClientError("net"))
        with pytest.raises(GeoRideConnectionError):
            await GeoRideApiClient(session, token="t").get_maintenance(5)


class TestGetBeacons:
    async def test_returns_list(self):
        session = _session(get_response=_response(200, [{"id": 999}]))
        client = GeoRideApiClient(session, token="t")
        assert await client.get_tracker_beacons(7) == [{"id": 999}]


# ---------------------------------------------------------------------------
# Control endpoints (POST)
# ---------------------------------------------------------------------------
class TestControlEndpoints:
    async def test_lock_tracker_posts(self):
        session = _session(post_response=_response(200, {}))
        await GeoRideApiClient(session, token="t").lock_tracker(7)

    async def test_unlock_tracker_posts(self):
        session = _session(post_response=_response(200, {}))
        await GeoRideApiClient(session, token="t").unlock_tracker(7)

    async def test_toggle_lock_posts(self):
        session = _session(post_response=_response(200, {}))
        await GeoRideApiClient(session, token="t").toggle_lock(7)

    async def test_siren_on_posts(self):
        session = _session(post_response=_response(200, {}))
        await GeoRideApiClient(session, token="t").siren_on(7)

    async def test_siren_off_posts(self):
        session = _session(post_response=_response(200, {}))
        await GeoRideApiClient(session, token="t").siren_off(7)

    async def test_eco_mode_on_posts(self):
        session = _session(post_response=_response(200, {}))
        await GeoRideApiClient(session, token="t").eco_mode_on(7)

    async def test_eco_mode_off_posts(self):
        session = _session(post_response=_response(200, {}))
        await GeoRideApiClient(session, token="t").eco_mode_off(7)

    async def test_post_without_token_raises(self):
        session = _session()
        with pytest.raises(GeoRideAuthError):
            await GeoRideApiClient(session).lock_tracker(7)

    async def test_post_auth_error_propagates(self):
        session = _session(post_response=_response(401, {}))
        with pytest.raises(GeoRideAuthError):
            await GeoRideApiClient(session, token="t").lock_tracker(7)

    async def test_post_connection_error_propagates(self):
        session = _session(post_raises=ClientError("net"))
        with pytest.raises(GeoRideConnectionError):
            await GeoRideApiClient(session, token="t").lock_tracker(7)

    async def test_post_500_raises_connection_error(self):
        session = _session(post_response=_response(500, {}))
        with pytest.raises(GeoRideConnectionError):
            await GeoRideApiClient(session, token="t").lock_tracker(7)
