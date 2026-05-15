"""GeoRide siren platform — trigger the sonor alarm on the tracker."""
from __future__ import annotations

from typing import Any

from homeassistant.components.siren import SirenEntity, SirenEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import GeoRideAuthError, GeoRideConnectionError, GeoRideError
from .const import DOMAIN
from .coordinator import GeoRideCoordinator
from .entity import GeoRideEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one siren per tracker, including those added after setup."""
    coordinator: GeoRideCoordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _async_add_new() -> None:
        new = []
        for tracker_id in coordinator.data:
            if tracker_id in known:
                continue
            known.add(tracker_id)
            new.append(GeoRideSiren(coordinator, tracker_id))
        if new:
            async_add_entities(new)

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


class GeoRideSiren(GeoRideEntity, SirenEntity):
    """The tracker's sonor alarm.

    GeoRide's API exposes turn-on / turn-off but not a read-back state for the
    siren, so `is_on` is reported as None (unknown). The integration trusts the
    last command issued from Home Assistant.
    """

    _attr_supported_features = (
        SirenEntityFeature.TURN_ON | SirenEntityFeature.TURN_OFF
    )
    _attr_name = "Siren"
    _attr_translation_key = "siren"

    def __init__(self, coordinator: GeoRideCoordinator, tracker_id: int) -> None:
        super().__init__(coordinator, tracker_id)
        self._attr_unique_id = f"{tracker_id}-siren"

    @property
    def is_on(self) -> bool | None:
        return None  # not exposed by GeoRide; treated as unknown

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._call(self.coordinator.client.siren_on)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._call(self.coordinator.client.siren_off)

    async def _call(self, fn) -> None:
        try:
            await fn(self._tracker_id)
        except GeoRideAuthError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="token_rejected",
                translation_placeholders={"error": str(err)},
            ) from err
        except (GeoRideConnectionError, GeoRideError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_error",
                translation_placeholders={"error": str(err)},
            ) from err
