"""GeoRide update platform: tracker firmware (shown only, installed from the GeoRide app)."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import GeoRideCoordinator
from .entity import GeoRideEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class GeoRideUpdateEntityDescription(UpdateEntityDescription):
    """An update description plus the tracker keys holding its versions."""

    installed_key: str
    latest_key: str


UPDATES: tuple[GeoRideUpdateEntityDescription, ...] = (
    GeoRideUpdateEntityDescription(
        key="firmware",
        translation_key="firmware",
        installed_key="firmwareVersion",
        latest_key="firmwareLatest",
    ),
    GeoRideUpdateEntityDescription(
        key="ble_firmware",
        translation_key="ble_firmware",
        installed_key="bleFirmwareVersion",
        latest_key="bleFirmwareLatest",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the firmware entities of trackers that report their versions."""
    coordinator: GeoRideCoordinator = entry.runtime_data
    known: set[tuple[int, str]] = set()

    @callback
    def _async_add_new() -> None:
        new = []
        for tracker_id, tracker in coordinator.data.items():
            for desc in UPDATES:
                if (tracker_id, desc.key) in known or tracker.get(desc.installed_key) is None:
                    continue
                known.add((tracker_id, desc.key))
                new.append(GeoRideFirmwareUpdate(coordinator, tracker_id, desc))
        if new:
            async_add_entities(new)

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


class GeoRideFirmwareUpdate(GeoRideEntity, UpdateEntity):
    """Installed and latest firmware of one part of the tracker."""

    entity_description: GeoRideUpdateEntityDescription
    _attr_device_class = UpdateDeviceClass.FIRMWARE
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: GeoRideCoordinator,
        tracker_id: int,
        description: GeoRideUpdateEntityDescription,
    ) -> None:
        super().__init__(coordinator, tracker_id)
        self.entity_description = description
        self._attr_unique_id = f"{self._uid}-{description.key}"

    @property
    def installed_version(self) -> str | None:
        v = self._tracker.get(self.entity_description.installed_key)
        return None if v is None else str(v)

    @property
    def latest_version(self) -> str | None:
        v = self._tracker.get(self.entity_description.latest_key)
        return None if v is None else str(v)
