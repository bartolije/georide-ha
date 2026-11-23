"""Diagnostics support for the GeoRide integration.

Both entry-level and device-level diagnostics. Lat/lon/addresses, the session
token and the account email are redacted before returning the snapshot to the user.
"""
from __future__ import annotations

import re
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .api import GeoRideError
from .const import DOMAIN
from .coordinator import GeoRideCoordinator

# The entry title is the account email (config_flow).
_ENTRY_TO_REDACT = {CONF_TOKEN, CONF_EMAIL, "unique_id", "title"}

_TRACKER_TO_REDACT = {
    "latitude",
    "longitude",
    "lockedLatitude",
    "lockedLongitude",
    "altitude",
    # Account-specific GeoRide identifiers.
    "vehicleId",
    "georideTrackerId",
}


def _mask_ids(path: str) -> str:
    """Hide the account-specific identifiers of an API path, keep its shape."""
    return re.sub(r"(?<=/)([a-z]+)_[a-z0-9]{6,}", r"\1_…", path)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Snapshot of the config entry and the coordinator's last view of every tracker."""
    coordinator: GeoRideCoordinator = entry.runtime_data
    try:
        session_expires: str | None = await coordinator.client.get_session_expiry()
    except GeoRideError as err:
        session_expires = f"unknown ({err})"
    return {
        "session_expires": session_expires,
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
        # What this account may not read: features the model lacks, vehicles shared without access.
        "unsupported_paths": sorted(_mask_ids(p) for p in coordinator.client._unsupported),
        "skipped_vehicles": len(coordinator.client._skipped),
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
