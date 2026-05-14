"""Common base class for every GeoRide entity."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import GeoRideCoordinator


class GeoRideEntity(CoordinatorEntity[GeoRideCoordinator]):
    """Base entity: holds the tracker_id and the shared DeviceInfo."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GeoRideCoordinator, tracker_id: int) -> None:
        super().__init__(coordinator)
        self._tracker_id = tracker_id
        tracker = coordinator.data[tracker_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(tracker_id))},
            name=tracker.get("trackerName") or f"GeoRide {tracker_id}",
            manufacturer=MANUFACTURER,
            model=tracker.get("model"),
            sw_version=tracker.get("version") or tracker.get("softwareVersion"),
        )

    @property
    def _tracker(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._tracker_id) or {}

    @property
    def available(self) -> bool:
        return super().available and self._tracker_id in self.coordinator.data
