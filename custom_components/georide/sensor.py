"""GeoRide sensor platform.

Eight sensors per tracker:
- odometer (km, total_increasing)
- speed (km/h)
- battery_level (%, computed from external battery voltage)
- last_seen (timestamp of the latest GPS fix)
- altitude (m, diagnostic, disabled by default)
- external_battery_voltage (V, diagnostic, enabled — useful as a fallback)
- internal_battery_voltage (V, diagnostic, disabled by default)
- subscription_expires (timestamp, diagnostic, disabled by default)
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfSpeed,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import GeoRideCoordinator
from .entity import GeoRideBeaconEntity, GeoRideEntity
from .helpers import (
    meters_to_km as _meters_to_km,
    number as _number,
    parse_timestamp as _parse_timestamp,
    voltage_to_battery_pct as _voltage_to_pct,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GeoRideSensorEntityDescription(SensorEntityDescription):
    """A sensor description plus a value extractor."""

    value_fn: Callable[[dict[str, Any]], StateType | datetime]


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
        key="battery_level",
        translation_key="battery_level",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: _voltage_to_pct(d.get("externalBatteryVoltage")),
    ),
    GeoRideSensorEntityDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _parse_timestamp(d.get("fixtime")),
    ),
    GeoRideSensorEntityDescription(
        key="altitude",
        translation_key="altitude",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.METERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _number(d.get("altitude")),
    ),
    GeoRideSensorEntityDescription(
        key="external_battery_voltage",
        translation_key="external_battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _number(d.get("externalBatteryVoltage")),
    ),
    GeoRideSensorEntityDescription(
        key="internal_battery_voltage",
        translation_key="internal_battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _number(d.get("internalBatteryVoltage")),
    ),
    GeoRideSensorEntityDescription(
        key="subscription_expires",
        translation_key="subscription_expires",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _parse_timestamp(d.get("expires")),
    ),
)


BEACON_SENSORS: tuple[GeoRideSensorEntityDescription, ...] = (
    GeoRideSensorEntityDescription(
        key="battery",
        translation_key="beacon_battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda d: _number(d.get("batteryLevel")),
    ),
    GeoRideSensorEntityDescription(
        key="last_seen",
        translation_key="beacon_last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _parse_timestamp(d.get("lastBatteryLevelUpdate")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up tracker + beacon sensors, including ones added after setup.

    Subscribes to the coordinator so that trackers / beacons that appear
    after the integration is set up (e.g. user pairs a new beacon in the
    GeoRide app) get their entities created without an HA restart.
    """
    coordinator: GeoRideCoordinator = entry.runtime_data
    known: set[tuple[str, int, str]] = set()

    @callback
    def _async_add_new() -> None:
        new: list[SensorEntity] = []
        for tracker_id in coordinator.data:
            for desc in SENSORS:
                key = ("tracker", tracker_id, desc.key)
                if key in known:
                    continue
                known.add(key)
                new.append(GeoRideSensor(coordinator, tracker_id, desc))
        for tracker_id, beacons in coordinator.beacons.items():
            for beacon in beacons:
                beacon_id = beacon.get("id")
                if not isinstance(beacon_id, int):
                    continue
                for desc in BEACON_SENSORS:
                    key = ("beacon", beacon_id, desc.key)
                    if key in known:
                        continue
                    known.add(key)
                    new.append(
                        GeoRideBeaconSensor(coordinator, tracker_id, beacon_id, desc)
                    )
        if new:
            async_add_entities(new)

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


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
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self._tracker)


class GeoRideBeaconSensor(GeoRideBeaconEntity, SensorEntity):
    entity_description: GeoRideSensorEntityDescription

    def __init__(
        self,
        coordinator: GeoRideCoordinator,
        tracker_id: int,
        beacon_id: int,
        description: GeoRideSensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, tracker_id, beacon_id)
        self.entity_description = description
        self._attr_unique_id = f"beacon-{beacon_id}-{description.key}"

    @property
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self._beacon)
