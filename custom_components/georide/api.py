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
        if not self._token:
            raise GeoRideAuthError("Not authenticated; call login() first")

        url = f"{API_HOST}/user/trackers"
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

        if not isinstance(data, list):
            raise GeoRideError(
                f"Unexpected trackers response shape: {type(data).__name__}"
            )
        return data
