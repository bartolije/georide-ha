"""Unit tests for the GeoRide v2 REST client with aiohttp fully mocked.

Payload shapes are the ones captured from the GeoRide app 5.5.6 on 2026-11-06
(personal values replaced).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientError
from multidict import CIMultiDict

from custom_components.georide.api import (
    SESSION_COOKIE,
    GeoRideApiClient,
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
    GeoRideNotSupportedError,
)

HOST = "https://api-v2.georide.com"
VID = "vehicle_01"
TID = "tracker_01"


def _resp(status: int = 200, body: Any = None, set_cookie: list[str] | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=body)
    resp.headers = CIMultiDict(("Set-Cookie", h) for h in set_cookie or [])
    return resp


# Real header shape (value replaced): the `Partitioned` flag makes
# http.cookies before Python 3.14 drop the whole cookie.
SET_COOKIE = (
    f"{SESSION_COOKIE}=tok.s%2Big%3D; Max-Age=7776000; Path=/; HttpOnly; Secure; "
    "SameSite=None; Partitioned"
)


class FakeSession:
    """Routes `request`/`post` by (METHOD, path) and records every call."""

    def __init__(self, routes: dict[tuple[str, str], Any], raises: Exception | None = None):
        self.routes = routes
        self.raises = raises
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    @asynccontextmanager
    async def request(self, method: str, url: str, **kwargs: Any):
        if self.raises is not None:
            raise self.raises
        path = url.removeprefix(HOST)
        self.calls.append((method, path, kwargs))
        route = self.routes.get((method, path))
        if route is None:
            yield _resp(404, {"code": "NOT_FOUND", "status": 404})
        elif isinstance(route, list):  # successive responses (pagination)
            yield route.pop(0)
        else:
            yield route

    def post(self, url: str, **kwargs: Any):
        return self.request("POST", url, **kwargs)


def _client(routes: dict[tuple[str, str], Any], token: str | None = "tok.sig") -> tuple[GeoRideApiClient, FakeSession]:
    session = FakeSession(routes)
    return GeoRideApiClient(session, token=token), session  # type: ignore[arg-type]


VEHICLE = {
    "id": VID,
    "name": "ZX-10R",
    "odometer": 36665791,
    "trackerId": TID,
    "model": {"brand": "Kawasaki", "name": "Kawasaki Ninja ZX-10R"},
    "role": "owner",
    "position": {
        "timestamp": "2026-09-13T17:32:41.400Z",
        "coordinate": {"latitude": 45.78, "longitude": 4.8},
    },
}
TRACKER = {
    "id": TID,
    "realtimeId": 2216122,
    "capabilities": ["accessory/live-alarm", "accessory/live-detect"],
    "platform": "cloud",
    "online": True,
    "subscriptionId": "sub_01",
    "operatingMode": "running",
}
NOT_SUPPORTED = _resp(422, {"code": "TRACKER_FEATURE_NOT_SUPPORTED", "status": 422})


def _tracker_routes(overrides: dict[tuple[str, str], Any] | None = None) -> dict[tuple[str, str], Any]:
    routes: dict[tuple[str, str], Any] = {
        ("GET", "/v1/vehicles"): _resp(200, [{"id": VID, "name": "ZX-10R", "trackerId": TID}]),
        ("GET", f"/v1/vehicles/{VID}"): _resp(200, VEHICLE),
        ("GET", f"/v1/trackers/{TID}"): _resp(200, TRACKER),
        ("GET", f"/v1/trackers/{TID}/battery"): _resp(200, {"external": 13.4, "internal": 100, "updatedAt": "2026-11-06T15:57:57Z", "isPlugged": True}),
        ("GET", f"/v1/trackers/{TID}/settings/mode"): _resp(200, {"mode": "eco"}),
        ("GET", f"/v1/trackers/{TID}/manual-lock"): NOT_SUPPORTED,
        ("GET", "/v1/subscriptions/sub_01"): _resp(200, {"dates": {"expiresAt": "2027-06-07T18:50:58.523Z"}}),
    }
    routes.update(overrides or {})
    return routes


async def _ready_client(routes: dict[tuple[str, str], Any]) -> tuple[GeoRideApiClient, FakeSession]:
    """A client whose id map is filled, as after the coordinator's first refresh."""
    client, session = _client({**_tracker_routes(), **routes})
    await client.get_trackers()
    session.calls.clear()
    return client, session


class TestAuth:
    async def test_send_otp_posts_email_without_cookie(self):
        client, session = _client({("POST", "/auth/otp/send"): _resp(204)}, token=None)
        await client.send_otp("me@example.com")
        method, path, kwargs = session.calls[0]
        assert (method, path) == ("POST", "/auth/otp/send")
        assert kwargs["json"] == {"email": "me@example.com"}
        assert "Cookie" not in kwargs["headers"]

    async def test_verify_otp_returns_signed_cookie(self):
        client, session = _client(
            {("POST", "/auth/otp/verify"): _resp(200, {"token": "tok"}, ["other=1; Path=/", SET_COOKIE])},
            token=None,
        )
        # Kept URL-encoded, exactly as the app sends it back.
        assert await client.verify_otp("me@example.com", "123456") == "tok.s%2Big%3D"
        assert client.token == "tok.s%2Big%3D"
        assert session.calls[0][2]["json"] == {"email": "me@example.com", "otp": "123456"}

    @pytest.mark.parametrize("status", [400, 401, 422])
    async def test_verify_otp_rejected_code(self, status):
        client, _ = _client({("POST", "/auth/otp/verify"): _resp(status, {"code": "INVALID_OTP"})}, token=None)
        with pytest.raises(GeoRideAuthError):
            await client.verify_otp("me@example.com", "000000")

    async def test_verify_otp_without_cookie(self):
        client, _ = _client({("POST", "/auth/otp/verify"): _resp(200, {"token": "tok"})}, token=None)
        with pytest.raises(GeoRideAuthError):
            await client.verify_otp("me@example.com", "123456")

    async def test_verify_otp_5xx_is_connection_error(self):
        client, _ = _client({("POST", "/auth/otp/verify"): _resp(503)}, token=None)
        with pytest.raises(GeoRideConnectionError):
            await client.verify_otp("me@example.com", "123456")

    async def test_session_cookie_sent(self):
        client, session = _client({("GET", "/v1/vehicles"): _resp(200, [])})
        await client.get_trackers()
        assert session.calls[0][2]["headers"]["Cookie"] == f"{SESSION_COOKIE}=tok.sig"

    async def test_no_token_raises_auth(self):
        client, _ = _client({}, token=None)
        with pytest.raises(GeoRideAuthError):
            await client.get_trackers()


class TestErrors:
    @pytest.mark.parametrize(
        ("status", "body", "exc"),
        [
            (401, {"code": "UNAUTHENTICATED"}, GeoRideAuthError),
            (403, None, GeoRideAuthError),
            (500, None, GeoRideConnectionError),
            (422, {"code": "VALIDATION_FAILED"}, GeoRideError),
            (422, {"code": "TRACKER_FEATURE_NOT_SUPPORTED"}, GeoRideNotSupportedError),
            (404, {"code": "NOT_FOUND"}, GeoRideError),
        ],
    )
    async def test_status_mapping(self, status, body, exc):
        client, _ = _client({("GET", "/v1/vehicles"): _resp(status, body)})
        with pytest.raises(exc):
            await client.get_trackers()

    async def test_client_error_is_connection_error(self):
        session = FakeSession({}, raises=ClientError("boom"))
        client = GeoRideApiClient(session, token="t")  # type: ignore[arg-type]
        with pytest.raises(GeoRideConnectionError):
            await client.get_trackers()

    async def test_unknown_tracker_before_refresh(self):
        client, _ = _client({})
        with pytest.raises(GeoRideError):
            await client.get_maintenance(2216122)


class TestGetTrackers:
    async def test_builds_v1_shaped_tracker(self):
        client, _ = _client(_tracker_routes())
        [tracker] = await client.get_trackers()
        assert tracker["trackerId"] == 2216122  # realtimeId = former v1 id
        assert tracker["trackerName"] == "ZX-10R"
        assert tracker["model"] == "Kawasaki Ninja ZX-10R"
        assert tracker["odometer"] == 36665791
        assert (tracker["latitude"], tracker["longitude"]) == (45.78, 4.8)
        assert tracker["fixtime"] == "2026-09-13T17:32:41.400Z"
        assert tracker["moving"] is False  # fix is weeks old
        assert tracker["externalBatteryVoltage"] == 13.4
        assert tracker["isInEco"] is True and tracker["isInElectricMode"] is False
        assert tracker["canLock"] is False and tracker["isLocked"] is None
        assert tracker["expires"] == "2027-06-07T18:50:58.523Z"
        assert "accessory/live-alarm" in tracker["capabilities"]

    async def test_recent_fix_means_moving(self):
        fresh = (datetime.now(tz=timezone.utc) - timedelta(seconds=30)).isoformat()
        vehicle = {**VEHICLE, "position": {"timestamp": fresh, "coordinate": {}}}
        client, _ = _client(_tracker_routes({("GET", f"/v1/vehicles/{VID}"): _resp(200, vehicle)}))
        [tracker] = await client.get_trackers()
        assert tracker["moving"] is True

    async def test_manual_lock_tracker(self):
        client, _ = _client(_tracker_routes({("GET", f"/v1/trackers/{TID}/manual-lock"): _resp(200, {"enabled": True})}))
        [tracker] = await client.get_trackers()
        assert tracker["canLock"] is True and tracker["isLocked"] is True

    async def test_unsupported_feature_not_asked_twice(self):
        client, session = _client(_tracker_routes())
        await client.get_trackers()
        await client.get_trackers()
        lock_calls = [c for c in session.calls if c[1].endswith("/manual-lock")]
        assert len(lock_calls) == 1

    async def test_vehicle_without_tracker_skipped(self):
        client, _ = _client({("GET", "/v1/vehicles"): _resp(200, [{"id": VID, "trackerId": None}])})
        assert await client.get_trackers() == []

    async def test_non_list_vehicles_raises(self):
        client, _ = _client({("GET", "/v1/vehicles"): _resp(200, {"data": []})})
        with pytest.raises(GeoRideError):
            await client.get_trackers()


class TestTrips:
    async def test_paginates_with_cursor_and_filter(self):
        path = f"/v1/vehicles/{VID}/trips"
        client, session = await _ready_client({
            ("GET", path): [
                _resp(200, {"data": [{"id": "trip_2"}], "page": {"nextCursor": "c1", "hasMore": True}}),
                _resp(200, {"data": [{"id": "trip_1"}], "page": {"nextCursor": None, "hasMore": False}}),
            ]
        })
        trips = await client.get_trips(2216122, "2026-01-01T00:00:00Z", "2026-12-31T23:59:59Z")
        assert [t["id"] for t in trips] == ["trip_2", "trip_1"]
        first, second = (c[2]["params"] for c in session.calls)
        assert first["filter"] == "startTime:gte:2026-01-01T00:00:00Z,startTime:lte:2026-12-31T23:59:59Z"
        assert first["limit"] == "100" and "cursor" not in first
        assert second["cursor"] == "c1"

    async def test_metrics_merged(self):
        client, _ = await _ready_client({
            ("GET", f"/v1/vehicles/{VID}/trips"): _resp(200, {"data": [{"id": "trip_1", "maxSpeed": 110.19}], "page": {}}),
            ("GET", f"/v1/vehicles/{VID}/trips/trip_1/metrics"): _resp(200, {"speed": {"average": 35}, "lean": {"maxLeftAngle": 12.5, "maxRightAngle": 24.3}}),
        })
        [trip] = await client.get_trips(2216122, "a", "b", metrics=True)
        assert trip == {"id": "trip_1", "maxSpeed": 110.19, "averageSpeed": 35, "maxLeftAngle": 12.5, "maxRightAngle": 24.3}


class TestOtherReads:
    async def test_maintenance_time_counter_in_days(self):
        client, _ = await _ready_client({
            ("GET", f"/v1/vehicles/{VID}/maintenances"): _resp(200, [
                {"id": "maintenance_1", "name": "Pneu avant", "distance": None,
                 "time": {"every": 15, "unit": "days", "lastMaintenanceDate": "2026-09-13T11:27:50Z", "todo": -3389630}},
                {"id": "maintenance_2", "name": "Vidange", "time": None, "distance": {"every": 6000000, "todo": 1500000}},
            ])
        })
        time_item, dist_item = await client.get_maintenance(2216122)
        assert time_item["todo"] == -39 and time_item["dateUnitType"] == "days"
        assert dist_item["todo"] == 1500000 and dist_item["dateUnitType"] is None

    async def test_beacons_empty_when_unsupported(self):
        client, _ = await _ready_client({("GET", f"/v1/trackers/{TID}/recognition/beacons"): NOT_SUPPORTED})
        assert await client.get_tracker_beacons(2216122) == []

    async def test_beacons_list(self):
        beacon = {"id": "beacon_1", "name": "Badge", "batteryLevel": 100}
        client, _ = await _ready_client({("GET", f"/v1/trackers/{TID}/recognition/beacons"): _resp(200, [beacon])})
        assert await client.get_tracker_beacons(2216122) == [beacon]

    async def test_events(self):
        event = {"kind": "event/vibration/detected", "occurredAt": "2026-11-01T15:02:46.000Z"}
        client, session = await _ready_client({("GET", f"/v1/trackers/{TID}/events"): _resp(200, {"data": [event], "page": {}})})
        assert await client.get_events(2216122) == [event]
        assert session.calls[0][2]["params"] == {"limit": "10"}


class TestCommands:
    @pytest.mark.parametrize(
        ("method", "action"),
        [
            ("lock_tracker", "manual-lock/enable"),
            ("unlock_tracker", "manual-lock/disable"),
            ("siren_on", "accessories/live-alarm/trigger"),
            ("eco_mode_on", "settings/mode/eco"),
            ("eco_mode_off", "settings/mode/running"),
        ],
    )
    async def test_posts_to_tracker_route(self, method, action):
        path = f"/v1/trackers/{TID}/{action}"
        client, session = await _ready_client({("POST", path): _resp(201, {"type": "ecoModeIn", "eta": None})})
        await getattr(client, method)(2216122)
        assert session.calls[0][:2] == ("POST", path)

    async def test_command_auth_error(self):
        client, _ = await _ready_client({("POST", f"/v1/trackers/{TID}/settings/mode/eco"): _resp(401)})
        with pytest.raises(GeoRideAuthError):
            await client.eco_mode_on(2216122)

