"""Async client for the GeoRide REST API."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import API_HOST, API_TIMEOUT

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=API_TIMEOUT)


class GeoRideError(Exception):
    """Base exception for the GeoRide API client."""


class GeoRideAuthError(GeoRideError):
    """Raised when credentials are rejected or a token is no longer valid."""


class GeoRideConnectionError(GeoRideError):
    """Raised for transport-level failures (network, timeouts, 5xx)."""


class GeoRideApiClient:
    """Thin async wrapper over the GeoRide REST API.

    The client only exposes what the integration currently needs: login and
    listing trackers. Other endpoints (positions, lock/unlock, alarms) will be
    added when the corresponding HA entities are implemented.
    """

    def __init__(
        self,
        session: ClientSession,
        token: str | None = None,
    ) -> None:
        self._session = session
        self._token = token

    @property
    def token(self) -> str | None:
        """The current bearer token, or None if not authenticated."""
        return self._token

    async def login(self, email: str, password: str) -> str:
        """Authenticate against GeoRide and cache the returned bearer token."""
        url = f"{API_HOST}/user/login"
        try:
            async with self._session.post(
                url,
                json={"email": email, "password": password},
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    raise GeoRideAuthError(
                        f"GeoRide rejected the credentials (HTTP {resp.status})"
                    )
                resp.raise_for_status()
                data = await resp.json()
        except ClientResponseError as err:
            if err.status in (401, 403):
                raise GeoRideAuthError(str(err)) from err
            raise GeoRideConnectionError(str(err)) from err
        except ClientError as err:
            raise GeoRideConnectionError(str(err)) from err

        if not isinstance(data, dict):
            raise GeoRideError(
                f"Unexpected login response shape: {type(data).__name__}"
            )

        token = data.get("authToken") or data.get("token") or data.get("access_token")
        if not token:
            raise GeoRideAuthError(
                f"Login succeeded but no token field in response (keys: {sorted(data)})"
            )

        self._token = token
        return token

    async def get_trackers(self) -> list[dict[str, Any]]:
        """Return the raw list of trackers for the authenticated user."""
        return await self._get_json_list("/user/trackers")

    async def get_trips(
        self,
        tracker_id: int | str,
        from_iso: str,
        to_iso: str,
    ) -> list[dict[str, Any]]:
        """Return the raw list of trips for a tracker between two ISO 8601 datetimes.

        from_iso / to_iso must be ISO 8601 strings (e.g. "2026-01-01T00:00:00Z").
        The exact param names accepted by the API are not documented publicly, so
        this method sends both common variants (`from`/`to` and `fromDate`/`toDate`)
        and lets the server ignore the unknown ones.
        """
        path = f"/tracker/{tracker_id}/trips"
        params = {
            "from": from_iso,
            "to": to_iso,
            "fromDate": from_iso,
            "toDate": to_iso,
        }
        return await self._get_json_list(path, params=params)

    async def _get_json_list(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Issue an authenticated GET and return the JSON body as a list of dicts."""
        if not self._token:
            raise GeoRideAuthError("Not authenticated; call login() first")

        url = f"{API_HOST}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with self._session.get(
                url, headers=headers, params=params, timeout=_TIMEOUT
            ) as resp:
                if resp.status in (401, 403):
                    raise GeoRideAuthError(
                        f"Token rejected by GeoRide (HTTP {resp.status})"
                    )
                resp.raise_for_status()
                data = await resp.json()
        except ClientResponseError as err:
            if err.status in (401, 403):
                raise GeoRideAuthError(str(err)) from err
            raise GeoRideConnectionError(str(err)) from err
        except ClientError as err:
            raise GeoRideConnectionError(str(err)) from err

        if not isinstance(data, list):
            raise GeoRideError(
                f"Unexpected response shape for {path}: {type(data).__name__}"
            )
        return data

    async def get_maintenance(
        self, tracker_id: int | str
    ) -> list[dict[str, Any]]:
        """Return the tracker's maintenance items (oil, chain, tyres, …).

        The endpoint returns `{"maintenanceList": [...]}` so we unwrap it
        here. Each item is configured by the user in the GeoRide app and
        carries a localised `name` (e.g. 'Niveau d'huile'), a remaining
        counter in `todo`, and a `dateUnitType` of either `'days'` for a
        time-based counter or `null` for a distance-based counter in
        meters.
        """
        if not self._token:
            raise GeoRideAuthError("Not authenticated; call login() first")

        url = f"{API_HOST}/tracker/{tracker_id}/maintenance"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with self._session.get(
                url, headers=headers, timeout=_TIMEOUT
            ) as resp:
                if resp.status in (401, 403):
                    raise GeoRideAuthError(
                        f"Token rejected by GeoRide (HTTP {resp.status})"
                    )
                resp.raise_for_status()
                data = await resp.json()
        except ClientResponseError as err:
            if err.status in (401, 403):
                raise GeoRideAuthError(str(err)) from err
            raise GeoRideConnectionError(str(err)) from err
        except ClientError as err:
            raise GeoRideConnectionError(str(err)) from err

        if not isinstance(data, dict):
            raise GeoRideError(
                f"Unexpected maintenance response shape: {type(data).__name__}"
            )
        items = data.get("maintenanceList", [])
        if not isinstance(items, list):
            raise GeoRideError(
                f"Unexpected maintenanceList shape: {type(items).__name__}"
            )
        return items

    async def get_tracker_beacons(
        self, tracker_id: int | str
    ) -> list[dict[str, Any]]:
        """Return the raw list of beacons paired with the tracker.

        GeoRide beacons are small Bluetooth tags (key fob, top-case, sensors)
        that the tracker listens for. The exact shape returned by the API
        is undocumented, so callers should treat the list as opaque dicts.
        """
        return await self._get_json_list(f"/tracker/{tracker_id}/beacon")

    async def lock_tracker(self, tracker_id: int | str) -> None:
        """Lock the tracker via POST /tracker/{id}/lock."""
        await self._post(f"/tracker/{tracker_id}/lock")

    async def unlock_tracker(self, tracker_id: int | str) -> None:
        """Unlock the tracker via POST /tracker/{id}/unlock."""
        await self._post(f"/tracker/{tracker_id}/unlock")

    async def toggle_lock(self, tracker_id: int | str) -> None:
        """Toggle the tracker lock state via POST /tracker/{id}/toggleLock."""
        await self._post(f"/tracker/{tracker_id}/toggleLock")

    async def siren_on(self, tracker_id: int | str) -> None:
        """Turn the sonor alarm ON via POST /tracker/{id}/sonor-alarm/on."""
        await self._post(f"/tracker/{tracker_id}/sonor-alarm/on")

    async def siren_off(self, tracker_id: int | str) -> None:
        """Turn the sonor alarm OFF via POST /tracker/{id}/sonor-alarm/off."""
        await self._post(f"/tracker/{tracker_id}/sonor-alarm/off")

    async def eco_mode_on(self, tracker_id: int | str) -> None:
        """Enable eco mode via POST /tracker/{id}/eco-mode/on.

        Eco mode reduces the tracker's polling rate to preserve the
        bike battery when the moto is parked for long periods.
        """
        await self._post(f"/tracker/{tracker_id}/eco-mode/on")

    async def eco_mode_off(self, tracker_id: int | str) -> None:
        """Disable eco mode via POST /tracker/{id}/eco-mode/off."""
        await self._post(f"/tracker/{tracker_id}/eco-mode/off")

    async def _post(self, path: str) -> None:
        """Issue an authenticated POST with no body. Used for control endpoints."""
        if not self._token:
            raise GeoRideAuthError("Not authenticated; call login() first")

        url = f"{API_HOST}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with self._session.post(
                url, headers=headers, timeout=_TIMEOUT
            ) as resp:
                if resp.status in (401, 403):
                    raise GeoRideAuthError(
                        f"Token rejected by GeoRide (HTTP {resp.status})"
                    )
                resp.raise_for_status()
        except ClientResponseError as err:
            if err.status in (401, 403):
                raise GeoRideAuthError(str(err)) from err
            raise GeoRideConnectionError(str(err)) from err
        except ClientError as err:
            raise GeoRideConnectionError(str(err)) from err
