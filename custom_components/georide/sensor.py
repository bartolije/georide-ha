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
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTime,
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


def _ms_to_s(value: Any) -> int | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return round(float(value) / 1000.0)


LAST_TRIP_SENSORS: tuple[GeoRideSensorEntityDescription, ...] = (
    GeoRideSensorEntityDescription(
        key="last_trip_end",
        translation_key="last_trip_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d: _parse_timestamp(d.get("endTime")),
    ),
    GeoRideSensorEntityDescription(
        key="last_trip_distance",
        translation_key="last_trip_distance",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        value_fn=lambda d: _meters_to_km(d.get("distance")),
    ),
    GeoRideSensorEntityDescription(
        key="last_trip_duration",
        translation_key="last_trip_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        value_fn=lambda d: _ms_to_s(d.get("duration")),
    ),
    GeoRideSensorEntityDescription(
        key="last_trip_avg_speed",
        translation_key="last_trip_avg_speed",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        value_fn=lambda d: _number(d.get("averageSpeed")),
    ),
    GeoRideSensorEntityDescription(
        key="last_trip_max_speed",
        translation_key="last_trip_max_speed",
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        value_fn=lambda d: _number(d.get("maxSpeed")),
    ),
    GeoRideSensorEntityDescription(
        key="last_trip_max_lean_angle",
        translation_key="last_trip_max_lean_angle",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=DEGREE,
        entity_registry_enabled_default=False,
        value_fn=lambda d: _number(d.get("maxAngle")),
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
            for desc in LAST_TRIP_SENSORS:
                key = ("last_trip", tracker_id, desc.key)
                if key in known:
                    continue
                known.add(key)
                new.append(GeoRideLastTripSensor(coordinator, tracker_id, desc))
        for tracker_id, items in coordinator.maintenance.items():
            for item in items:
                item_id = item.get("id")
                if not isinstance(item_id, int):
                    continue
                key = ("maintenance", tracker_id, item_id)
                if key in known:
                    continue
                known.add(key)
                new.append(
                    GeoRideMaintenanceSensor(coordinator, tracker_id, item_id)
                )
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


class GeoRideLastTripSensor(GeoRideEntity, SensorEntity):
    """Reads from coordinator.last_trips[tracker_id] rather than the tracker dict."""

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
        trip = self.coordinator.last_trips.get(self._tracker_id) or {}
        return self.entity_description.value_fn(trip)


class GeoRideMaintenanceSensor(GeoRideEntity, SensorEntity):
    """One sensor per user-defined maintenance item.

    The name comes from the GeoRide app (e.g. 'Niveau d'huile') so there's
    no translation_key. The unit and device_class adapt to the item's
    `dateUnitType`: 'days' → DURATION, anything else → DISTANCE (meters
    converted to km).
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: GeoRideCoordinator,
        tracker_id: int,
        item_id: int,
    ) -> None:
        super().__init__(coordinator, tracker_id)
        self._item_id = item_id
        self._attr_unique_id = f"{tracker_id}-maintenance-{item_id}"

    @property
    def _item(self) -> dict[str, Any]:
        for item in self.coordinator.maintenance.get(self._tracker_id, []):
            if item.get("id") == self._item_id:
                return item
        return {}

    @property
    def name(self) -> str | None:
        n = self._item.get("name")
        if isinstance(n, str) and n:
            return n
        return f"Maintenance {self._item_id}"

    @property
    def native_value(self) -> StateType:
        todo = self._item.get("todo")
        if not isinstance(todo, (int, float)) or isinstance(todo, bool):
            return None
        dut = self._item.get("dateUnitType")
        if dut is None:
            # Distance-based: GeoRide stores meters, render as km.
            return round(float(todo) / 1000.0, 2)
        if dut == "days":
            return int(todo)
        if dut == "years":
            # GeoRide stores years-mode counters in hours (8759 h ≈ 1 y).
            # Convert to days for a more readable display.
            return round(float(todo) / 24.0, 1)
        # Unknown time-unit, surface raw value rather than mis-converting.
        return todo

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self._item.get("dateUnitType") is None:
            return UnitOfLength.KILOMETERS
        return UnitOfTime.DAYS

    @property
    def device_class(self) -> SensorDeviceClass | None:
        if self._item.get("dateUnitType") is None:
            return SensorDeviceClass.DISTANCE
        return SensorDeviceClass.DURATION

    @property
    def available(self) -> bool:
        return super().available and bool(self._item)


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
