"""GeoRide binary_sensor platform: lock, moving, stolen, crashed."""
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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GeoRideCoordinator
from .entity import GeoRideEntity

PARALLEL_UPDATES = 0


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _bool_invert(value: Any) -> bool | None:
    return (not value) if isinstance(value, bool) else None


@dataclass(frozen=True, kw_only=True)
class GeoRideBinarySensorEntityDescription(BinarySensorEntityDescription):
    """A binary_sensor description plus a value extractor."""

    value_fn: Callable[[dict[str, Any]], bool | None]


BINARY_SENSORS: tuple[GeoRideBinarySensorEntityDescription, ...] = (
    GeoRideBinarySensorEntityDescription(
        key="lock",
        translation_key="lock",
        device_class=BinarySensorDeviceClass.LOCK,
        # device_class LOCK semantics: True = unlocked, False = locked.
        # GeoRide gives isLocked, so we invert.
        value_fn=lambda d: _bool_invert(d.get("isLocked")),
    ),
    GeoRideBinarySensorEntityDescription(
        key="moving",
        translation_key="moving",
        device_class=BinarySensorDeviceClass.MOVING,
        value_fn=lambda d: _bool(d.get("moving")),
    ),
    GeoRideBinarySensorEntityDescription(
        key="stolen",
        translation_key="stolen",
        device_class=BinarySensorDeviceClass.SAFETY,
        value_fn=lambda d: _bool(d.get("isStolen")),
    ),
    GeoRideBinarySensorEntityDescription(
        key="crashed",
        translation_key="crashed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d: _bool(d.get("isCrashed")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: GeoRideCoordinator = entry.runtime_data
    async_add_entities(
        GeoRideBinarySensor(coordinator, tracker_id, desc)
        for tracker_id in coordinator.data
        for desc in BINARY_SENSORS
    )


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
        self._attr_unique_id = f"{tracker_id}-{description.key}"

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self._tracker)
