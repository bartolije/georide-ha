"""Diagnostics support for the GeoRide integration.

Both entry-level and device-level diagnostics. Lat/lon/addresses and the bearer
token are redacted before returning the snapshot to the user.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import GeoRideCoordinator

_ENTRY_TO_REDACT = {CONF_TOKEN, CONF_EMAIL, "unique_id"}

_TRACKER_TO_REDACT = {
    "latitude",
    "longitude",
    "lockedLatitude",
    "lockedLongitude",
    "altitude",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Snapshot of the config entry and the coordinator's last view of every tracker."""
    coordinator: GeoRideCoordinator = entry.runtime_data
    return {
        "entry": async_redact_data(entry.as_dict(), _ENTRY_TO_REDACT),
        "trackers": [
            async_redact_data(tracker, _TRACKER_TO_REDACT)
            for tracker in coordinator.data.values()
        ],
        "update_interval_seconds": (
            coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None
        ),
        "last_update_success": coordinator.last_update_success,
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry, device: dr.DeviceEntry
) -> dict[str, Any]:
    """Snapshot of a single tracker."""
    coordinator: GeoRideCoordinator = entry.runtime_data

    tracker_id: int | None = None
    for ident in device.identifiers:
        if ident[0] == DOMAIN:
            try:
                tracker_id = int(ident[1])
            except (TypeError, ValueError):
                tracker_id = None
            break

    if tracker_id is None or tracker_id not in coordinator.data:
        return {"error": f"tracker {tracker_id} not found in coordinator snapshot"}

    return {
        "tracker": async_redact_data(coordinator.data[tracker_id], _TRACKER_TO_REDACT),
    }
