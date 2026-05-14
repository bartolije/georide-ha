"""DataUpdateCoordinator for GeoRide trackers."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    GeoRideApiClient,
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=60)

TrackersById = dict[int, dict[str, Any]]


class GeoRideCoordinator(DataUpdateCoordinator[TrackersById]):
    """Polls /user/trackers and indexes the returned list by trackerId."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: GeoRideApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.client = client

    async def _async_update_data(self) -> TrackersById:
        try:
            trackers = await self.client.get_trackers()
        except GeoRideAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (GeoRideConnectionError, GeoRideError) as err:
            raise UpdateFailed(str(err)) from err

        indexed: TrackersById = {}
        for tracker in trackers:
            tid = tracker.get("trackerId") or tracker.get("id")
            if tid is None:
                _LOGGER.warning(
                    "Skipping tracker without trackerId; keys=%s",
                    sorted(tracker.keys()),
                )
                continue
            indexed[int(tid)] = tracker
        return indexed
