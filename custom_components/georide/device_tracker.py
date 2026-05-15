"""GeoRide device_tracker platform."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GeoRideCoordinator
from .entity import GeoRideEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one device_tracker per moto, including ones added later."""
    coordinator: GeoRideCoordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _async_add_new() -> None:
        new = []
        for tracker_id in coordinator.data:
            if tracker_id in known:
                continue
            known.add(tracker_id)
            new.append(GeoRideDeviceTracker(coordinator, tracker_id))
        if new:
            async_add_entities(new)

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


class GeoRideDeviceTracker(GeoRideEntity, TrackerEntity):
    """A GeoRide tracker exposed as a GPS device_tracker."""

    _attr_name = None  # use the device name as the entity name

    def __init__(self, coordinator: GeoRideCoordinator, tracker_id: int) -> None:
        super().__init__(coordinator, tracker_id)
        self._attr_unique_id = str(tracker_id)

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        v = self._tracker.get("latitude")
        return float(v) if isinstance(v, (int, float)) else None

    @property
    def longitude(self) -> float | None:
        v = self._tracker.get("longitude")
        return float(v) if isinstance(v, (int, float)) else None

    @property
    def location_accuracy(self) -> int:
        # GeoRide doesn't expose accuracy; report a reasonable GPS fix radius.
        return 10
