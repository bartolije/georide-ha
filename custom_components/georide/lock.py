"""GeoRide lock platform — lock/unlock the tracker."""
from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GeoRideAuthError, GeoRideConnectionError, GeoRideError
from .const import DOMAIN
from .coordinator import GeoRideCoordinator
from .entity import GeoRideEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the lock entity for every tracker that supports remote lock."""
    coordinator: GeoRideCoordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _async_add_new() -> None:
        new = []
        for tracker_id, tracker in coordinator.data.items():
            if tracker_id in known:
                continue
            if not (tracker.get("canLock", True) or tracker.get("canUnlock", True)):
                continue
            known.add(tracker_id)
            new.append(GeoRideLock(coordinator, tracker_id))
        if new:
            async_add_entities(new)

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


class GeoRideLock(GeoRideEntity, LockEntity):
    """The tracker's anti-theft lock state."""

    _attr_name = None  # use the device name

    def __init__(self, coordinator: GeoRideCoordinator, tracker_id: int) -> None:
        super().__init__(coordinator, tracker_id)
        self._attr_unique_id = f"{tracker_id}-lock"

    @property
    def is_locked(self) -> bool | None:
        v = self._tracker.get("isLocked")
        return bool(v) if isinstance(v, bool) else None

    async def async_lock(self, **kwargs: Any) -> None:
        await self._call(self.coordinator.client.lock_tracker)

    async def async_unlock(self, **kwargs: Any) -> None:
        await self._call(self.coordinator.client.unlock_tracker)

    async def _call(self, fn: Any) -> None:
        try:
            await fn(self._tracker_id)
        except GeoRideAuthError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="token_rejected",
                translation_placeholders={"error": str(err)},
            ) from err
        except (GeoRideConnectionError, GeoRideError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_error",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
