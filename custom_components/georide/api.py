"""Async client for the GeoRide v2 REST API (api-v2.georide.com).

The GeoRide app moved to this API in 2026 (app 5.5.x). Login is passwordless:
a one-time code is mailed (`/auth/otp/send`) and exchanged for a session
cookie (`/auth/otp/verify`, 90-day session). Every other call sends that
cookie; a bearer header is refused.

The rest of the integration was written against the v1 payloads, so
`get_trackers()` assembles one v1-shaped dict per vehicle from the v2
resources. `trackerId` is the tracker's `realtimeId`, which is the former
numeric v1 id: entity unique ids and history survive the migration.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
from aiohttp import ClientError, ClientSession

from .const import API_HOST, API_TIMEOUT

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=API_TIMEOUT)

SESSION_COOKIE = "__Secure-georide-auth.session_token"

# The v2 position carries no speed / moving flag. A fix this recent means the
# tracker is reporting live, i.e. the bike is riding.
# shortcut: moving is inferred from fix age, switch to a real flag if the API grows one.
MOVING_FIX_AGE = timedelta(minutes=5)

TRIPS_PAGE_SIZE = 100  # API maximum
METRICS_CONCURRENCY = 5


class GeoRideError(Exception):
    """Base exception for the GeoRide API client."""


class GeoRideAuthError(GeoRideError):
    """Raised when the code is rejected or the session is no longer valid."""


class GeoRideConnectionError(GeoRideError):
    """Raised for transport-level failures (network, timeouts, 5xx)."""


class GeoRideNotSupportedError(GeoRideError):
    """The tracker model lacks this feature (HTTP 422 TRACKER_FEATURE_NOT_SUPPORTED)."""


class GeoRideApiClient:
    """Thin async wrapper over the GeoRide v2 REST API.

    `token` is the signed session cookie value returned by `verify_otp()`.
    Pass a session without a cookie jar (or a dedicated one): the cookie is
    sent explicitly so several accounts can't mix in a shared jar.
    """

    def __init__(self, session: ClientSession, token: str | None = None) -> None:
        self._session = session
        self._token = token
        # realtimeId → (vehicle id, tracker id), filled by get_trackers().
        self._ids: dict[int, tuple[str, str]] = {}
        # Paths that answered TRACKER_FEATURE_NOT_SUPPORTED: not asked again.
        self._unsupported: set[str] = set()

    @property
    def token(self) -> str | None:
        """The current session cookie value, or None if not authenticated."""
        return self._token

    # -- auth ---------------------------------------------------------------

    async def send_otp(self, email: str) -> None:
        """Ask GeoRide to mail a one-time login code to `email`."""
        await self._request("POST", "/auth/otp/send", json={"email": email}, auth=False)

    async def verify_otp(self, email: str, otp: str) -> str:
        """Exchange the mailed code for a session; return and cache the cookie value."""
        try:
            async with self._session.post(
                f"{API_HOST}/auth/otp/verify",
                json={"email": email, "otp": otp},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (400, 401, 403, 422):
                    raise GeoRideAuthError(f"GeoRide rejected the code (HTTP {resp.status})")
                if resp.status >= 400:
                    raise GeoRideConnectionError(f"HTTP {resp.status} on /auth/otp/verify")
                token = _session_cookie(resp.headers.getall("Set-Cookie", []))
        except ClientError as err:
            raise GeoRideConnectionError(str(err)) from err
        if not token:
            raise GeoRideAuthError("Code accepted but no session cookie returned")
        self._token = token
        return self._token

    # -- data ---------------------------------------------------------------

    async def get_trackers(self) -> list[dict[str, Any]]:
        """Return one v1-shaped tracker dict per vehicle that has a tracker."""
        vehicles = await self._request("GET", "/v1/vehicles")
        if not isinstance(vehicles, list):
            raise GeoRideError(f"Unexpected /v1/vehicles shape: {type(vehicles).__name__}")
        trackers = []
        for summary in vehicles:
            if not summary.get("trackerId"):
                continue
            vid, trid = summary["id"], summary["trackerId"]
            vehicle, tracker, battery, mode, lock = await asyncio.gather(
                self._request("GET", f"/v1/vehicles/{vid}"),
                self._request("GET", f"/v1/trackers/{trid}"),
                self._optional(f"/v1/trackers/{trid}/battery"),
                self._optional(f"/v1/trackers/{trid}/settings/mode"),
                self._optional(f"/v1/trackers/{trid}/manual-lock"),
            )
            expires = None
            if tracker.get("subscriptionId"):
                sub = await self._request("GET", f"/v1/subscriptions/{tracker['subscriptionId']}")
                expires = (sub.get("dates") or {}).get("expiresAt")
            payload = _tracker_payload(vehicle, tracker, battery, mode, lock, expires)
            if isinstance(payload.get("trackerId"), int):
                self._ids[payload["trackerId"]] = (vid, trid)
            trackers.append(payload)
        return trackers

    async def get_trips(
        self,
        tracker_id: int,
        from_iso: str,
        to_iso: str,
        *,
        metrics: bool = False,
    ) -> list[dict[str, Any]]:
        """Return the trips started between two ISO 8601 datetimes, newest first.

        Distances are in meters, durations in seconds, speeds in km/h. With
        `metrics=True`, each trip also gets `averageSpeed` and the per-side
        lean angles (one extra call per trip).
        """
        vid = self._vehicle_id(tracker_id)
        params = {
            "limit": str(TRIPS_PAGE_SIZE),
            "sort": "startTime:desc",
            "filter": f"startTime:gte:{from_iso},startTime:lte:{to_iso}",
        }
        trips: list[dict[str, Any]] = []
        while True:
            page = await self._request("GET", f"/v1/vehicles/{vid}/trips", params=dict(params))
            trips.extend(page.get("data") or [])
            cursor = (page.get("page") or {}).get("nextCursor")
            if not cursor:
                break
            params["cursor"] = cursor
        if metrics:
            sem = asyncio.Semaphore(METRICS_CONCURRENCY)

            async def _one(trip: dict[str, Any]) -> dict[str, Any]:
                async with sem:
                    return await self.add_trip_metrics(tracker_id, trip)

            trips = list(await asyncio.gather(*(_one(t) for t in trips)))
        return trips

    async def add_trip_metrics(self, tracker_id: int, trip: dict[str, Any]) -> dict[str, Any]:
        """Return `trip` merged with its average speed and per-side max lean."""
        vid = self._vehicle_id(tracker_id)
        metrics = await self._request("GET", f"/v1/vehicles/{vid}/trips/{trip['id']}/metrics")
        lean = metrics.get("lean") or {}
        return {
            **trip,
            "averageSpeed": (metrics.get("speed") or {}).get("average"),
            "maxLeftAngle": lean.get("maxLeftAngle"),
            "maxRightAngle": lean.get("maxRightAngle"),
        }

    async def get_maintenance(self, tracker_id: int) -> list[dict[str, Any]]:
        """Return maintenance items in the v1 shape (`todo` + `dateUnitType`).

        v2 nests the counter under `time` (todo in seconds) or `distance`;
        time counters are converted to days.
        """
        vid = self._vehicle_id(tracker_id)
        items = await self._request("GET", f"/v1/vehicles/{vid}/maintenances")
        return [_maintenance_payload(item) for item in items or []]

    async def get_tracker_beacons(self, tracker_id: int) -> list[dict[str, Any]]:
        """Return the Bluetooth badges paired with the tracker ([] if unsupported)."""
        trid = self._tracker_id(tracker_id)
        beacons = await self._optional(f"/v1/trackers/{trid}/recognition/beacons")
        return beacons if isinstance(beacons, list) else []

    async def get_events(self, tracker_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """Return the latest tracker events (`kind`, `occurredAt`), newest first."""
        trid = self._tracker_id(tracker_id)
        page = await self._request(
            "GET", f"/v1/trackers/{trid}/events", params={"limit": str(limit)}
        )
        return list(page.get("data") or [])

    # -- commands -----------------------------------------------------------

    async def lock_tracker(self, tracker_id: int) -> None:
        """Enable the manual lock (GeoRide 1; GeoRide 3 locks itself)."""
        await self._command(tracker_id, "manual-lock/enable")

    async def unlock_tracker(self, tracker_id: int) -> None:
        """Disable the manual lock."""
        await self._command(tracker_id, "manual-lock/disable")

    async def eco_mode_on(self, tracker_id: int) -> None:
        """Queue the switch to eco mode (applied at the tracker's next connection)."""
        await self._command(tracker_id, "settings/mode/eco")

    async def eco_mode_off(self, tracker_id: int) -> None:
        """Queue the switch back to the standard (running) mode."""
        await self._command(tracker_id, "settings/mode/running")

    # -- plumbing -----------------------------------------------------------

    def _vehicle_id(self, tracker_id: int) -> str:
        return self._lookup(tracker_id)[0]

    def _tracker_id(self, tracker_id: int) -> str:
        return self._lookup(tracker_id)[1]

    def _lookup(self, tracker_id: int) -> tuple[str, str]:
        try:
            return self._ids[int(tracker_id)]
        except (KeyError, ValueError) as err:
            raise GeoRideError(f"Unknown tracker {tracker_id}; refresh trackers first") from err

    async def _command(self, tracker_id: int, action: str) -> None:
        await self._request("POST", f"/v1/trackers/{self._tracker_id(tracker_id)}/{action}")

    async def _optional(self, path: str) -> Any:
        """GET that returns None when the tracker model lacks the feature."""
        if path in self._unsupported:
            return None
        try:
            return await self._request("GET", path)
        except GeoRideNotSupportedError:
            self._unsupported.add(path)
            return None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        """Issue a request and return the decoded JSON body (None when empty)."""
        headers = {}
        if auth:
            if not self._token:
                raise GeoRideAuthError("Not authenticated; log in with a code first")
            headers["Cookie"] = f"{SESSION_COOKIE}={self._token}"
        try:
            async with self._session.request(
                method,
                f"{API_HOST}{path}",
                headers=headers,
                params=params,
                json=json,
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status < 400:
                    return await resp.json(content_type=None)
                try:
                    code = (await resp.json(content_type=None) or {}).get("code")
                except (ValueError, AttributeError):
                    code = None
        except ClientError as err:
            raise GeoRideConnectionError(str(err)) from err
        if resp.status in (401, 403):
            raise GeoRideAuthError(f"Session rejected by GeoRide (HTTP {resp.status})")
        if resp.status == 422 and code == "TRACKER_FEATURE_NOT_SUPPORTED":
            raise GeoRideNotSupportedError(path)
        if resp.status >= 500:
            raise GeoRideConnectionError(f"HTTP {resp.status} on {path}")
        raise GeoRideError(f"HTTP {resp.status} {code or ''} on {method} {path}".strip())


def _session_cookie(set_cookie_headers: list[str]) -> str | None:
    """Value of the session cookie, kept URL-encoded as the server sent it.

    Parsed by hand: before Python 3.14, http.cookies drops the whole cookie
    because of its `Partitioned` attribute, so `resp.cookies` comes back empty.
    """
    for header in set_cookie_headers:
        name, _, rest = header.partition("=")
        if name.strip() == SESSION_COOKIE:
            return rest.split(";", 1)[0].strip() or None
    return None


def _tracker_payload(
    vehicle: dict[str, Any],
    tracker: dict[str, Any],
    battery: dict[str, Any] | None,
    mode: dict[str, Any] | None,
    lock: dict[str, Any] | None,
    expires: str | None,
) -> dict[str, Any]:
    """Assemble the v1-shaped tracker dict the entities read."""
    position = vehicle.get("position") or {}
    coordinate = position.get("coordinate") or {}
    fixtime = position.get("timestamp")
    current_mode = (mode or {}).get("mode")
    locked = _lock_state(lock)
    return {
        "trackerId": tracker.get("realtimeId"),
        "trackerName": vehicle.get("name"),
        "model": (vehicle.get("model") or {}).get("name"),
        "odometer": vehicle.get("odometer"),
        "latitude": coordinate.get("latitude"),
        "longitude": coordinate.get("longitude"),
        "fixtime": fixtime,
        "moving": _is_recent(fixtime),
        "online": tracker.get("online"),
        "capabilities": tracker.get("capabilities") or [],
        "externalBatteryVoltage": (battery or {}).get("external"),
        "batteryUpdatedAt": (battery or {}).get("updatedAt"),
        "isInEco": current_mode == "eco" if current_mode else None,
        "isInElectricMode": current_mode == "electric" if current_mode else None,
        "canLock": lock is not None,
        "canUnlock": lock is not None,
        "isLocked": locked,
        "expires": expires,
        "role": vehicle.get("role"),
        "vehicleId": vehicle.get("id"),
        "georideTrackerId": tracker.get("id"),
    }


def _lock_state(lock: dict[str, Any] | None) -> bool | None:
    # shortcut: ManualLockStatusResponseDto never seen (GeoRide 1 only); guess the bool key.
    for key in ("locked", "isLocked", "enabled", "active"):
        value = (lock or {}).get(key)
        if isinstance(value, bool):
            return value
    return None


def _is_recent(timestamp: Any) -> bool | None:
    if not isinstance(timestamp, str):
        return None
    try:
        fix = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return datetime.now(tz=timezone.utc) - fix < MOVING_FIX_AGE


def _maintenance_payload(item: dict[str, Any]) -> dict[str, Any]:
    time = item.get("time") or {}
    distance = item.get("distance") or {}
    out = {"id": item.get("id"), "name": item.get("name")}
    if time:
        todo = time.get("todo")
        days = round(todo / 86400) if isinstance(todo, (int, float)) else None
        return {**out, "todo": days, "dateUnitType": "days", "every": time.get("every"),
                "lastMaintenanceDate": time.get("lastMaintenanceDate")}
    # shortcut: distance counters never seen live; todo assumed in meters like v1.
    return {**out, "todo": distance.get("todo"), "dateUnitType": None,
            "every": distance.get("every")}
