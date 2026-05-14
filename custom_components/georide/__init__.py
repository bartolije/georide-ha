"""The GeoRide integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
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

    _cleanup_stale_devices(
        hass,
        entry,
        tracker_ids=set(coordinator.data),
        beacon_ids={
            b["id"]
            for beacons in coordinator.beacons.values()
            for b in beacons
            if isinstance(b.get("id"), int)
        },
    )

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


def _cleanup_stale_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    tracker_ids: set[int],
    beacon_ids: set[int],
) -> None:
    """Drop devices whose tracker_id or beacon_id is no longer in GeoRide.

    Runs once at setup. Dynamic addition of newly-appeared trackers / beacons
    between setups is a separate concern handled by a future coordinator
    listener.
    """
    device_registry = dr.async_get(hass)
    valid_identifiers = {(DOMAIN, str(tid)) for tid in tracker_ids} | {
        (DOMAIN, f"beacon-{bid}") for bid in beacon_ids
    }
    for device in dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    ):
        if not any(ident in valid_identifiers for ident in device.identifiers):
            _LOGGER.info(
                "Removing stale GeoRide device %s (no longer in account)",
                device.name or device.id,
            )
            device_registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )
