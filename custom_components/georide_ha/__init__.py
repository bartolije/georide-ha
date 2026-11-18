"""The GeoRide integration."""
from __future__ import annotations

import logging
import shutil

import aiohttp
from homeassistant.config_entries import ConfigEntry, OperationNotAllowed
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import IntegrationNotFound, async_get_integration

from .api import GeoRideApiClient
from .const import CONF_LEGACY, DOCUMENTATION_URL, DOMAIN, LEGACY_DOMAIN, PLATFORMS
from .coordinator import GeoRideCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

# Set up from the UI only; async_setup exists just to register the services.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide services (independent of any config entry).

    Per the Bronze tier rule `action-setup`, services are registered once at
    integration setup rather than on each config entry. The handler itself
    is idempotent so calling this for the first entry, then for subsequent
    ones, has no extra cost.
    """
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GeoRide from a config entry: build the coordinator, fan out platforms."""
    await _async_adopt_legacy_entry(hass, entry)
    if entry.data.get(CONF_LEGACY):
        await async_setup_services(hass, LEGACY_DOMAIN)

    # Own session without cookie jar: the session cookie is sent explicitly,
    # so two GeoRide accounts can't leak into each other through a shared jar.
    session = async_create_clientsession(hass, cookie_jar=aiohttp.DummyCookieJar())
    client = GeoRideApiClient(session, token=entry.data[CONF_TOKEN])
    coordinator = GeoRideCoordinator(hass, entry, client)

    # First refresh: raises ConfigEntryAuthFailed (→ reauth) or
    # ConfigEntryNotReady (→ retry) on its own when needed. Entries created
    # before the v2 API hold a v1 token, which v2 rejects → reauth by code.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    _cleanup_stale_devices(
        hass,
        entry,
        tracker_ids=set(coordinator.data),
        beacon_ids={
            b["id"]
            for beacons in coordinator.beacons.values()
            for b in beacons
            if isinstance(b.get("id"), (int, str))
        },
    )
    _cleanup_stale_maintenance(hass, entry, coordinator)

    _LOGGER.info(
        "GeoRide: setup complete for %s with %d tracker(s)",
        entry.title,
        len(coordinator.data),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_adopt_legacy_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Take over the same account's entry of the 0.17 `georide` domain.

    HACS installs 0.18 next to the old `georide` folder and leaves that folder
    in place. Moving the old devices and entities to this entry keeps their
    entity_ids, history, dashboards and automations; the old entry and folder
    are then removed.
    """
    try:
        legacy = await async_get_integration(hass, LEGACY_DOMAIN)
    except IntegrationNotFound:
        return
    if legacy.is_built_in or legacy.documentation != DOCUMENTATION_URL:
        return  # ptimatth/GeorideHA, the other integration on that domain
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    for old in hass.config_entries.async_entries(LEGACY_DOMAIN):
        if old.unique_id != entry.unique_id:
            continue
        # Registry entries can only change platform once their entities are unloaded.
        try:
            await hass.config_entries.async_unload(old.entry_id)
        except OperationNotAllowed as err:  # old entry still setting up: retry shortly
            raise ConfigEntryNotReady(f"waiting for the old {old.title} entry") from err
        # Entities first: detaching a device from the old entry deletes its entities.
        for ent in er.async_entries_for_config_entry(entity_registry, old.entry_id):
            if entity_registry.async_get_entity_id(ent.domain, DOMAIN, ent.unique_id):
                entity_registry.async_remove(ent.entity_id)
            else:
                entity_registry.async_update_entity_platform(
                    ent.entity_id, DOMAIN, new_config_entry_id=entry.entry_id
                )
        for device in dr.async_entries_for_config_entry(device_registry, old.entry_id):
            identifiers = {
                (DOMAIN if domain == LEGACY_DOMAIN else domain, ident)
                for domain, ident in device.identifiers
            }
            try:
                device_registry.async_update_device(
                    device.id, new_config_entry_id=entry.entry_id, new_identifiers=identifiers
                )
            except dr.DeviceIdentifierCollisionError:  # already created by this entry
                device_registry.async_remove_device(device.id)
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_LEGACY: True}
        )
        await hass.config_entries.async_remove(old.entry_id)
        _LOGGER.info("GeoRide: took over %s from the 0.17 domain", old.title)
    if not hass.config_entries.async_entries(LEGACY_DOMAIN):
        # shortcut: deletes our own 0.17 folder left behind by HACS; drop once nobody runs 0.17.
        await hass.async_add_executor_job(shutil.rmtree, legacy.file_path, True)


def _cleanup_stale_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    *,
    tracker_ids: set[int],
    beacon_ids: set[int | str],
) -> None:
    """Drop devices whose tracker_id or beacon_id is no longer in GeoRide.

    Runs once at setup. Dynamic addition of newly-appeared trackers / beacons
    between setups is a separate concern handled by a future coordinator
    listener.
    """
    device_registry = dr.async_get(hass)
    valid_identifiers = {(DOMAIN, str(tid)) for tid in tracker_ids} | {
        (DOMAIN, f"beacon-{bid}") for bid in beacon_ids
    }
    for device in dr.async_entries_for_config_entry(
        device_registry, entry.entry_id
    ):
        if not any(ident in valid_identifiers for ident in device.identifiers):
            _LOGGER.info(
                "Removing stale GeoRide device %s (no longer in account)",
                device.name or device.id,
            )
            device_registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


def _cleanup_stale_maintenance(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: GeoRideCoordinator
) -> None:
    """Drop maintenance entities whose item no longer exists.

    The v2 API renumbered maintenance items (`maintenance_…` instead of an
    int), so removing the old registry entries before the platforms run lets
    the new entities take over the same entity_ids, and their history.
    """
    current = {
        f"{tid}-maintenance-{item.get('id')}"
        for tid, items in coordinator.maintenance.items()
        for item in items
    }
    fetched = {str(tid) for tid in coordinator.maintenance}
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        tid, sep, _ = entity.unique_id.partition("-maintenance-")
        if sep and tid in fetched and entity.unique_id not in current:
            _LOGGER.info("Removing stale GeoRide maintenance entity %s", entity.entity_id)
            registry.async_remove(entity.entity_id)
