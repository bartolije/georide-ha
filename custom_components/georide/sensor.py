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
from datetime import datetime, timezone
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
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import GeoRideCoordinator
from .entity import GeoRideEntity

PARALLEL_UPDATES = 0


# Approximate moto-battery curve: 11.0 V = empty, 12.7 V = full.
# Linear interpolation; gives a usable badge percentage even though real
# discharge curves are non-linear.
_BATTERY_EMPTY_V = 11.0
_BATTERY_FULL_V = 12.7


def _meters_to_km(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return round(float(value) / 1000.0, 2)


def _number(value: Any) -> StateType:
    return value if isinstance(value, (int, float)) else None


def _voltage_to_pct(value: Any) -> int | None:
    if not isinstance(value, (int, float)):
        return None
    span = _BATTERY_FULL_V - _BATTERY_EMPTY_V
    pct = (float(value) - _BATTERY_EMPTY_V) / span * 100.0
    return max(0, min(100, round(pct)))


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO 8601 string or an epoch (s or ms) into an aware datetime."""
    if isinstance(value, (int, float)):
        try:
            seconds = float(value) / 1000.0 if value > 1e12 else float(value)
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


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
    def native_value(self) -> StateType | datetime:
        return self.entity_description.value_fn(self._tracker)
