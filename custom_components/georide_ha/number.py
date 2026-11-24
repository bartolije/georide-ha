"""GeoRide number platform: battery cutoff voltage."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfElectricPotential
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GeoRideError
from .const import DOMAIN
from .coordinator import GeoRideCoordinator
from .entity import GeoRideEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the cutoff voltage of trackers that have the setting."""
    coordinator: GeoRideCoordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _async_add_new() -> None:
        new = []
        for tracker_id, tracker in coordinator.data.items():
            if tracker_id in known or tracker.get("cutoffVoltage") is None:
                continue
            known.add(tracker_id)
            new.append(GeoRideCutoffVoltage(coordinator, tracker_id))
        if new:
            async_add_entities(new)

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


class GeoRideCutoffVoltage(GeoRideEntity, NumberEntity):
    """Bike battery voltage under which the tracker stops drawing from it."""

    _attr_translation_key = "cutoff_voltage"
    _attr_device_class = NumberDeviceClass.VOLTAGE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    # Range of the GeoRide app; the API refuses values outside its own limits.
    _attr_native_min_value = 11.0
    _attr_native_max_value = 16.0
    _attr_native_step = 0.05
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: GeoRideCoordinator, tracker_id: int) -> None:
        super().__init__(coordinator, tracker_id)
        self._attr_unique_id = f"{self._uid}-cutoff_voltage"

    @property
    def native_value(self) -> float | None:
        v = self._tracker.get("cutoffVoltage")
        return float(v) if isinstance(v, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.client.set_cutoff_voltage(self._tracker_id, value)
        except GeoRideError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_error",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()
