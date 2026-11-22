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

from custom_components.georide_ha.api import (
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
            (403, None, GeoRideNotSupportedError),  # signed in, not allowed: no reauth
            (500, None, GeoRideConnectionError),
            (422, {"code": "VALIDATION_FAILED"}, GeoRideError),
            (422, {"code": "TRACKER_FEATURE_NOT_SUPPORTED"}, GeoRideNotSupportedError),
            (404, {"code": "RESOURCE_NOT_FOUND"}, GeoRideNotSupportedError),
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

    async def test_timeout_is_connection_error(self):
        # aiohttp raises TimeoutError (not ClientError) when the total timeout passes.
        session = FakeSession({}, raises=TimeoutError())
        client = GeoRideApiClient(session, token="t")  # type: ignore[arg-type]
        with pytest.raises(GeoRideConnectionError):
            await client.get_trackers()

    async def test_every_call_is_traced_at_debug_without_the_cookie(self, caplog):
        caplog.set_level("DEBUG", logger="custom_components.georide_ha.api")
        client, _ = _client(_tracker_routes(), token="secret.sig")
        await client.get_trackers()
        assert "GET /v1/vehicles -> 200" in caplog.text
        assert f"GET /v1/trackers/{TID}/manual-lock -> 422 TRACKER_FEATURE_NOT_SUPPORTED" in caplog.text
        assert "secret" not in caplog.text

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
        assert tracker["internalBatteryLevel"] == 100 and tracker["isPlugged"] is True
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

    async def test_manual_lock_404_is_unsupported(self):
        # issue #3: login failed on HTTP 404 RESOURCE_NOT_FOUND on /manual-lock
        missing = _resp(404, {"code": "RESOURCE_NOT_FOUND", "status": 404})
        client, _ = _client(_tracker_routes({("GET", f"/v1/trackers/{TID}/manual-lock"): missing}))
        [tracker] = await client.get_trackers()
        assert tracker["canLock"] is False and tracker["isLocked"] is None

    async def test_subscription_refused_keeps_tracker(self):
        # A shared vehicle's subscription belongs to its owner.
        missing = _resp(404, {"code": "RESOURCE_NOT_FOUND", "status": 404})
        client, _ = _client(_tracker_routes({("GET", "/v1/subscriptions/sub_01"): missing}))
        [tracker] = await client.get_trackers()
        assert tracker["trackerId"] == 2216122 and tracker["expires"] is None

    async def test_unreadable_vehicle_skipped_others_kept(self, caplog):
        shared = {"id": "vehicle_shared", "name": "3S partagé", "trackerId": "tracker_shared"}
        routes = _tracker_routes({
            ("GET", "/v1/vehicles"): _resp(200, [shared, {"id": VID, "name": "ZX-10R", "trackerId": TID}]),
            ("GET", "/v1/vehicles/vehicle_shared"): _resp(200, {**VEHICLE, "id": "vehicle_shared"}),
            ("GET", "/v1/trackers/tracker_shared"): _resp(403, {"code": "FORBIDDEN", "status": 403}),
        })
        client, session = _client(routes)
        [tracker] = await client.get_trackers()
        assert tracker["trackerId"] == 2216122
        assert "3S partagé" in caplog.text
        session.calls.clear()
        await client.get_trackers()
        assert not [c for c in session.calls if "shared" in c[1]]  # not asked again

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


class TestSlowReads:
    async def test_mode_and_subscription_read_every_15_min_not_every_poll(self):
        client, session = await _ready_client({})  # first poll already read them
        await client.get_trackers()
        paths = [c[1] for c in session.calls]
        assert f"/v1/trackers/{TID}/settings/mode" not in paths
        assert "/v1/subscriptions/sub_01" not in paths
        assert f"/v1/trackers/{TID}/battery" in paths  # read every poll

    async def test_slow_reads_refreshed_after_the_ttl(self, monkeypatch):
        import custom_components.georide_ha.api as api_module

        client, session = await _ready_client({})
        now = api_module.time.monotonic()
        monkeypatch.setattr(api_module.time, "monotonic", lambda: now + api_module.SLOW_DATA_TTL + 1)
        await client.get_trackers()
        assert "/v1/subscriptions/sub_01" in [c[1] for c in session.calls]


class TestLastTrip:
    async def test_one_call_newest_first(self):
        trip = {"id": "trip_1", "endTime": "2026-09-13T17:32:41.400Z"}
        client, session = await _ready_client({("GET", f"/v1/vehicles/{VID}/trips"): _resp(200, {"data": [trip], "page": {"nextCursor": "x"}})})
        assert await client.get_last_trip(2216122) == trip
        assert len(session.calls) == 1
        assert session.calls[0][2]["params"] == {"limit": "1", "sort": "startTime:desc"}

    async def test_none_without_trip(self):
        client, _ = await _ready_client({("GET", f"/v1/vehicles/{VID}/trips"): _resp(200, {"data": [], "page": {}})})
        assert await client.get_last_trip(2216122) is None


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
            ("eco_mode_on", "settings/mode/eco"),
            ("eco_mode_off", "settings/mode/running"),
        ],
    )
    async def test_posts_to_tracker_route(self, method, action):
        path = f"/v1/trackers/{TID}/{action}"
        client, session = await _ready_client({("POST", path): _resp(201, {"type": "ecoModeIn", "eta": None})})
        await getattr(client, method)(2216122)
        assert session.calls[0][:2] == ("POST", path)

    async def test_mode_command_returns_eta_and_rereads_mode(self):
        path = f"/v1/trackers/{TID}/settings/mode/eco"
        client, session = await _ready_client({("POST", path): _resp(201, {"type": "ecoModeIn", "eta": "2026-11-07T04:57:00.000Z"})})
        assert await client.eco_mode_on(2216122) == "2026-11-07T04:57:00.000Z"
        session.calls.clear()
        await client.get_trackers()
        assert ("GET", f"/v1/trackers/{TID}/settings/mode") in [c[:2] for c in session.calls]

    async def test_command_auth_error(self):
        client, _ = await _ready_client({("POST", f"/v1/trackers/{TID}/settings/mode/eco"): _resp(401)})
        with pytest.raises(GeoRideAuthError):
            await client.eco_mode_on(2216122)



BASE = f"/v1/trackers/{TID}"
SETTINGS = {
    ("GET", f"{BASE}/firmware-update"): _resp(200, {"stm": {"currentVersion": 50, "latestVersion": 51}, "nrf": {"currentVersion": 5, "latestVersion": 5}}),
    ("GET", f"{BASE}/settings/sleep-mode"): _resp(200, {"enabled": False, "pending": None}),
    ("GET", f"{BASE}/settings/maintenance-mode"): _resp(200, {"enabled": False}),
    ("GET", f"{BASE}/settings/cutoff-voltage"): _resp(200, {"cutoffVoltage": 12250}),
    ("GET", f"{BASE}/settings/vibration-sensitivity"): _resp(200, {"vibrationSensitivity": 2}),
    ("GET", f"{BASE}/settings/fall-detector"): _resp(200, {"enabled": True}),
    ("GET", f"{BASE}/ecall"): _resp(200, {"friendCallEnabled": False, "emergencyCallEnabled": True}),
    ("GET", f"{BASE}/assistance/theft/report"): _resp(200, None),
}


class TestSettings:
    """Shapes read on a real GeoRide 3S on 2026-11-22."""

    async def test_settings_merged_into_the_tracker(self):
        client, _ = _client(_tracker_routes(SETTINGS))
        [t] = await client.get_trackers()
        assert (t["firmwareVersion"], t["firmwareLatest"], t["bleFirmwareVersion"]) == (50, 51, 5)
        assert t["cutoffVoltage"] == 12.25 and t["vibrationSensitivity"] == 2
        assert t["sleepMode"] is False and t["maintenanceMode"] is False and t["fallDetector"] is True
        assert t["emergencyCallEnabled"] is True and t["friendCallEnabled"] is False
        assert t["isStolen"] is False  # route answered null: no theft declared

    async def test_theft_declared(self):
        routes = {**SETTINGS, ("GET", f"{BASE}/assistance/theft/report"): _resp(200, {"id": "report_1"})}
        client, _ = _client(_tracker_routes(routes))
        [t] = await client.get_trackers()
        assert t["isStolen"] is True

    async def test_model_without_settings_gets_none_not_false(self):
        routes = {k: NOT_SUPPORTED for k in SETTINGS}
        client, _ = _client(_tracker_routes(routes))
        [t] = await client.get_trackers()
        assert t["isStolen"] is None and t["cutoffVoltage"] is None and t["firmwareVersion"] is None

    async def test_route_removed_by_georide_is_ignored_with_one_warning(self, caplog):
        client, session = _client(_tracker_routes())  # settings routes answer 404 NOT_FOUND
        [t] = await client.get_trackers()
        await client.get_trackers()
        assert t["trackerId"] == 2216122 and t["sleepMode"] is None
        assert caplog.text.count("optional data unavailable, ignored until reload: HTTP 404 NOT_FOUND on GET /v1/trackers/tracker_01/settings/sleep-mode") == 1

    async def test_settings_read_every_15_min_not_every_poll(self):
        client, session = await _ready_client(SETTINGS)
        await client.get_trackers()
        assert not [c for c in session.calls if "settings/" in c[1] or "firmware" in c[1]]

    async def test_cutoff_voltage_sent_in_millivolts_then_read_again(self):
        path = f"{BASE}/settings/cutoff-voltage"
        client, session = await _ready_client({**SETTINGS, ("PATCH", path): _resp(200, {"type": "newSettings", "eta": None})})
        await client.set_cutoff_voltage(2216122, 12.3)
        assert session.calls[0][:2] == ("PATCH", path) and session.calls[0][2]["json"] == {"cutoffVoltage": 12300}
        session.calls.clear()
        await client.get_trackers()
        assert ("GET", path) in [c[:2] for c in session.calls]

    async def test_fall_detector_and_sleep_mode_routes(self):
        client, session = await _ready_client({
            **SETTINGS,
            ("PATCH", f"{BASE}/settings/fall-detector"): _resp(200, {"enabled": False}),
            ("POST", f"{BASE}/settings/sleep-mode/on"): _resp(201, {}),
            ("POST", f"{BASE}/settings/sleep-mode/off"): _resp(201, {}),
        })
        await client.set_fall_detector(2216122, False)
        await client.set_sleep_mode(2216122, True)
        await client.set_sleep_mode(2216122, False)
        assert [(c[0], c[1].removeprefix(BASE), c[2]["json"]) for c in session.calls] == [
            ("PATCH", "/settings/fall-detector", {"enabled": False}),
            ("POST", "/settings/sleep-mode/on", None),
            ("POST", "/settings/sleep-mode/off", None),
        ]

    async def test_sign_out_and_session_expiry(self):
        client, session = _client({
            ("POST", "/auth/sign-out"): _resp(200, None),
            ("GET", "/auth/session"): _resp(200, {"id": "s", "expiresAt": "2027-02-20T17:28:02.117Z"}),
        })
        assert await client.get_session_expiry() == "2027-02-20T17:28:02.117Z"
        await client.sign_out()
        assert session.calls[-1][2]["json"] == {} and client.token is None
