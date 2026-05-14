"""The GeoRide integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GeoRideApiClient, GeoRideAuthError, GeoRideConnectionError
from .const import DOMAIN, PLATFORMS
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GeoRide from a config entry: build the client, fetch trackers."""
    session = async_get_clientsession(hass)
    client = GeoRideApiClient(session, token=entry.data[CONF_TOKEN])

    try:
        trackers = await client.get_trackers()
    except GeoRideAuthError as err:
        raise ConfigEntryAuthFailed("Stored GeoRide token was rejected") from err
    except GeoRideConnectionError as err:
        raise ConfigEntryNotReady("Cannot reach the GeoRide API") from err

    _LOGGER.info(
        "GeoRide: %d tracker(s) found for %s", len(trackers), entry.title
    )
    if trackers:
        _LOGGER.info(
            "GeoRide: tracker payload keys = %s", sorted(trackers[0].keys())
        )
        for tracker in trackers:
            _LOGGER.debug("GeoRide tracker raw payload: %s", tracker)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "trackers": trackers,
    }
    await async_setup_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
