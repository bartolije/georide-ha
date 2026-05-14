"""The GeoRide integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import GeoRideApiClient
from .const import DOMAIN, PLATFORMS
from .coordinator import GeoRideCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GeoRide from a config entry: build the coordinator, fan out platforms."""
    session = async_get_clientsession(hass)
    client = GeoRideApiClient(session, token=entry.data[CONF_TOKEN])
    coordinator = GeoRideCoordinator(hass, entry, client)

    # First refresh: raises ConfigEntryAuthFailed (→ reauth) or
    # ConfigEntryNotReady (→ retry) on its own when needed.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    _LOGGER.info(
        "GeoRide: setup complete for %s with %d tracker(s)",
        entry.title,
        len(coordinator.data),
    )

    await async_setup_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
