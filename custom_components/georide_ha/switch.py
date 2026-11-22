"""GeoRide switch platform: eco mode toggle.

Eco mode trades fix frequency for battery life on the moto's main battery
— useful for long winter parking. GeoRide applies a mode change at the
tracker's next connection, hours later when it sleeps: until then the switch
shows the requested mode, with the expected time in `pending_until`.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import GeoRideApiClient, GeoRideAuthError, GeoRideConnectionError, GeoRideError
from .const import DOMAIN
from .coordinator import GeoRideCoordinator
from .entity import GeoRideEntity
from .helpers import parse_timestamp

PARALLEL_UPDATES = 1

# A request still not applied this long after GeoRide's expected time is shown as lost.
PENDING_GRACE = timedelta(hours=1)


@dataclass(frozen=True, kw_only=True)
class GeoRideSettingSwitchDescription(SwitchEntityDescription):
    """A tracker setting that is a plain on/off."""

    state_key: str
    set_fn: Callable[[GeoRideApiClient, int, bool], Awaitable[None]]
    attrs: tuple[str, ...] = ()


SETTING_SWITCHES: tuple[GeoRideSettingSwitchDescription, ...] = (
    GeoRideSettingSwitchDescription(
        key="fall_detector",
        translation_key="fall_detector",
        entity_category=EntityCategory.CONFIG,
        state_key="fallDetector",
        set_fn=lambda client, tid, on: client.set_fall_detector(tid, on),
    ),
    GeoRideSettingSwitchDescription(
        # Applied at the tracker's next connection; GeoRide reports the wait in `pending`.
        key="sleep_mode",
        translation_key="sleep_mode",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,  # opt-in: only `off` was tried on a real tracker
        state_key="sleepMode",
        set_fn=lambda client, tid, on: client.set_sleep_mode(tid, on),
        attrs=("sleepModePending",),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one eco-mode switch per tracker that has modes, picking up newcomers later."""
    coordinator: GeoRideCoordinator = entry.runtime_data
    known: set[tuple[int, str]] = set()

    @callback
    def _async_add_new() -> None:
        new: list[SwitchEntity] = []
        for tracker_id, tracker in coordinator.data.items():
            # No value read (GeoRide 1, Mini…): the tracker lacks the feature.
            if (tracker_id, "eco") not in known and tracker.get("isInEco") is not None:
                known.add((tracker_id, "eco"))
                new.append(GeoRideEcoModeSwitch(coordinator, tracker_id))
            for desc in SETTING_SWITCHES:
                if (tracker_id, desc.key) in known or tracker.get(desc.state_key) is None:
                    continue
                known.add((tracker_id, desc.key))
                new.append(GeoRideSettingSwitch(coordinator, tracker_id, desc))
        if new:
            async_add_entities(new)

    _async_add_new()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new))


class GeoRideEcoModeSwitch(GeoRideEntity, SwitchEntity):
    """Toggle the tracker's eco mode."""

    _attr_translation_key = "eco_mode"

    def __init__(self, coordinator: GeoRideCoordinator, tracker_id: int) -> None:
        super().__init__(coordinator, tracker_id)
        self._attr_unique_id = f"{self._uid}-eco_mode"
        # Requested mode the tracker has not applied yet, and GeoRide's expected time.
        self._pending: tuple[bool, datetime | None] | None = None

    @property
    def _actual(self) -> bool | None:
        v = self._tracker.get("isInEco")
        return v if isinstance(v, bool) else None

    @property
    def is_on(self) -> bool | None:
        return self._actual if self._pending is None else self._pending[0]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._pending is None:
            return None
        eta = self._pending[1]
        return {"pending_until": eta.isoformat() if eta else None}

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._pending is not None:
            target, eta = self._pending
            lost = eta is not None and dt_util.utcnow() > eta + PENDING_GRACE
            if self._actual == target or lost:
                self._pending = None
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, eco: bool) -> None:
        client = self.coordinator.client
        eta = await _call((client.eco_mode_on if eco else client.eco_mode_off)(self._tracker_id))
        self._pending = None if self._actual == eco else (eco, parse_timestamp(eta))
        await self.coordinator.async_request_refresh()


class GeoRideSettingSwitch(GeoRideEntity, SwitchEntity):
    """An on/off setting of the tracker."""

    entity_description: GeoRideSettingSwitchDescription

    def __init__(
        self,
        coordinator: GeoRideCoordinator,
        tracker_id: int,
        description: GeoRideSettingSwitchDescription,
    ) -> None:
        super().__init__(coordinator, tracker_id)
        self.entity_description = description
        self._attr_unique_id = f"{self._uid}-{description.key}"

    @property
    def is_on(self) -> bool | None:
        v = self._tracker.get(self.entity_description.state_key)
        return v if isinstance(v, bool) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs = self.entity_description.attrs
        return {"pending": self._tracker.get(attrs[0])} if attrs else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, on: bool) -> None:
        await _call(self.entity_description.set_fn(self.coordinator.client, self._tracker_id, on))
        await self.coordinator.async_request_refresh()


async def _call[T](request: Awaitable[T]) -> T:
    """Await a client call, turning its errors into translated HomeAssistantErrors."""
    try:
        return await request
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
