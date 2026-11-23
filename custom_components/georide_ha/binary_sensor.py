"""GeoRide binary_sensor platform: moving, power plugged, stolen, online, …

An entity without a value is unavailable: crashed and the beacon firmware
flag have no source in the v2 API (disabled by default).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GeoRideCoordinator
from .entity import GeoRideBeaconEntity, GeoRideEntity

PARALLEL_UPDATES = 0


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


@dataclass(frozen=True, kw_only=True)
class GeoRideBinarySensorEntityDescription(BinarySensorEntityDescription):
    """A binary_sensor description plus a value extractor."""

    value_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[GeoRideBinarySensorEntityDescription, ...] = (
    GeoRideBinarySensorEntityDescription(
        key="moving",
        translation_key="moving",
        device_class=BinarySensorDeviceClass.MOVING,
        value_fn=lambda d: _bool(d.get("moving")),
    ),
    GeoRideBinarySensorEntityDescription(
        # Off when the tracker loses the bike's power: cable cut or battery removed.
        key="plugged",
        translation_key="plugged",
        device_class=BinarySensorDeviceClass.PLUG,
        value_fn=lambda d: _bool(d.get("isPlugged")),
    ),
    GeoRideBinarySensorEntityDescription(
        key="stolen",
        translation_key="stolen",
        # On while a theft is declared to GeoRide's assistance.
        device_class=BinarySensorDeviceClass.SAFETY,
        value_fn=lambda d: _bool(d.get("isStolen")),
    ),
    GeoRideBinarySensorEntityDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _bool(d.get("online")),
    ),
    GeoRideBinarySensorEntityDescription(
        key="maintenance_mode",
        translation_key="maintenance_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _bool(d.get("maintenanceMode")),
    ),
    GeoRideBinarySensorEntityDescription(
        key="emergency_call",
        translation_key="emergency_call",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _bool(d.get("emergencyCallEnabled")),
    ),
    GeoRideBinarySensorEntityDescription(
        key="friend_call",
        translation_key="friend_call",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _bool(d.get("friendCallEnabled")),
    ),
    GeoRideBinarySensorEntityDescription(
        key="crashed",
        translation_key="crashed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_registry_enabled_default=False,  # no source in the v2 API
        value_fn=lambda d: _bool(d.get("isCrashed")),
    ),
    GeoRideBinarySensorEntityDescription(
        key="has_beacon",
        translation_key="has_beacon",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _bool(d.get("hasBeacon")),
    ),
)


BEACON_BINARY_SENSORS: tuple[GeoRideBinarySensorEntityDescription, ...] = (
    GeoRideBinarySensorEntityDescription(
        key="firmware_update",
        translation_key="beacon_firmware_update",
        device_class=BinarySensorDeviceClass.UPDATE,
        entity_registry_enabled_default=False,  # no source in the v2 API
        # UPDATE device_class: on = update available. GeoRide's isUpdated
        # field is True when firmware is up to date, so we invert.
        value_fn=lambda d: (
            (not d["isUpdated"]) if isinstance(d.get("isUpdated"), bool) else None
        ),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up tracker + beacon binary sensors, picking up newcomers on the fly."""
    coordinator: GeoRideCoordinator = entry.runtime_data
    known: set[tuple[str, int | str, str]] = set()

    @callback
    def _async_add_new() -> None:
        new: list[BinarySensorEntity] = []
        for tracker_id in coordinator.data:
            for desc in BINARY_SENSORS:
                key: tuple[str, int | str, str] = ("tracker", tracker_id, desc.key)
                if key in known:
                    continue
                known.add(key)
                new.append(GeoRideBinarySensor(coordinator, tracker_id, desc))
        for tracker_id, beacons in coordinator.beacons.items():
            for beacon in beacons:
                beacon_id = beacon.get("id")
                if not isinstance(beacon_id, (int, str)):
                    continue
                for desc in BEACON_BINARY_SENSORS:
                    key = ("beacon", beacon_id, desc.key)
                    if key in known:
                        continue
                    known.add(key)
                    new.append(
                        GeoRideBeaconBinarySensor(
                            coordinator, tracker_id, beacon_id, desc
                        )
                    )
        if new:
            async_add_entities(new)

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


class GeoRideBinarySensor(GeoRideEntity, BinarySensorEntity):
    entity_description: GeoRideBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: GeoRideCoordinator,
        tracker_id: int,
        description: GeoRideBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, tracker_id)
        self.entity_description = description
        self._attr_unique_id = f"{self._uid}-{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self._tracker)

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None


class GeoRideBeaconBinarySensor(GeoRideBeaconEntity, BinarySensorEntity):
    entity_description: GeoRideBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: GeoRideCoordinator,
        tracker_id: int,
        beacon_id: int | str,
        description: GeoRideBinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, tracker_id, beacon_id)
        self.entity_description = description
        self._attr_unique_id = f"{self._uid}-{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self._beacon)

    @property
    def available(self) -> bool:
        return super().available and self.is_on is not None
