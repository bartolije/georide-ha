"""GeoRide sensor platform: odometer, speed, battery voltages."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfSpeed,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import GeoRideCoordinator
from .entity import GeoRideEntity

PARALLEL_UPDATES = 0


def _meters_to_km(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(float(value) / 1000.0, 2)


def _number(value: Any) -> StateType:
    return value if isinstance(value, (int, float)) else None


@dataclass(frozen=True, kw_only=True)
class GeoRideSensorEntityDescription(SensorEntityDescription):
    """A sensor description plus a value extractor."""

    value_fn: Callable[[dict[str, Any]], StateType]


SENSORS: tuple[GeoRideSensorEntityDescription, ...] = (
    GeoRideSensorEntityDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        value_fn=lambda d: _meters_to_km(d.get("odometer")),
    ),
    GeoRideSensorEntityDescription(
        key="speed",
        translation_key="speed",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        value_fn=lambda d: _number(d.get("speed")),
    ),
    GeoRideSensorEntityDescription(
        key="internal_battery_voltage",
        translation_key="internal_battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn=lambda d: _number(d.get("internalBatteryVoltage")),
    ),
    GeoRideSensorEntityDescription(
        key="external_battery_voltage",
        translation_key="external_battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        value_fn=lambda d: _number(d.get("externalBatteryVoltage")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: GeoRideCoordinator = entry.runtime_data
    async_add_entities(
        GeoRideSensor(coordinator, tracker_id, desc)
        for tracker_id in coordinator.data
        for desc in SENSORS
    )


class GeoRideSensor(GeoRideEntity, SensorEntity):
    entity_description: GeoRideSensorEntityDescription

    def __init__(
        self,
        coordinator: GeoRideCoordinator,
        tracker_id: int,
        description: GeoRideSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, tracker_id)
        self.entity_description = description
        self._attr_unique_id = f"{tracker_id}-{description.key}"

    @property
    def native_value(self) -> StateType:
        return self.entity_description.value_fn(self._tracker)
