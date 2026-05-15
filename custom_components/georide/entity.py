"""Common base classes for every GeoRide entity (tracker + beacon)."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import GeoRideCoordinator


class GeoRideEntity(CoordinatorEntity[GeoRideCoordinator]):
    """Base entity bound to a GeoRide tracker."""

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


class GeoRideBeaconEntity(CoordinatorEntity[GeoRideCoordinator]):
    """Base entity bound to a GeoRide beacon (key fob, top-case, etc.).

    Beacons appear as separate Home Assistant devices, attached to their
    parent tracker via `via_device` so they appear nested in the UI.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GeoRideCoordinator,
        tracker_id: int,
        beacon_id: int,
    ) -> None:
        super().__init__(coordinator)
        self._tracker_id = tracker_id
        self._beacon_id = beacon_id

        beacon = self._beacon
        connections: set[tuple[str, str]] = set()
        mac = beacon.get("macAddress")
        if isinstance(mac, str) and mac:
            connections.add((CONNECTION_NETWORK_MAC, mac.lower()))

        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"beacon-{beacon_id}")},
            via_device=(DOMAIN, str(tracker_id)),
            name=beacon.get("name") or f"GeoRide beacon {beacon_id}",
            manufacturer=MANUFACTURER,
            model=beacon.get("model"),
        )
        if connections:
            device_info["connections"] = connections
        self._attr_device_info = device_info

    @property
    def _beacon(self) -> dict[str, Any]:
        for b in self.coordinator.beacons.get(self._tracker_id, []):
            if b.get("id") == self._beacon_id:
                return b
        return {}

    @property
    def available(self) -> bool:
        return super().available and bool(self._beacon)
