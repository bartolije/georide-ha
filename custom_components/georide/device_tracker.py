"""GeoRide device_tracker platform."""
from __future__ import annotations

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GeoRideCoordinator
from .entity import GeoRideEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: GeoRideCoordinator = entry.runtime_data
    async_add_entities(
        GeoRideDeviceTracker(coordinator, tracker_id)
        for tracker_id in coordinator.data
    )


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
