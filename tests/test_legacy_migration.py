"""0.18 renamed the domain georide -> georide_ha: the old entry is taken over."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("pytest_homeassistant")

from homeassistant import config_entries  # noqa: E402
from homeassistant.const import CONF_EMAIL, CONF_TOKEN  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from homeassistant.helpers import device_registry as dr  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402
from homeassistant.loader import IntegrationNotFound  # noqa: E402
from pytest_homeassistant.common import MockConfigEntry  # noqa: E402

from custom_components.georide_ha import _async_adopt_legacy_entry, services  # noqa: E402
from custom_components.georide_ha.const import (  # noqa: E402
    CONF_LEGACY,
    DOCUMENTATION_URL,
    DOMAIN,
    EVENT_MOVING,
    LEGACY_DOMAIN,
)
from custom_components.georide_ha.coordinator import GeoRideCoordinator  # noqa: E402

EMAIL = "bike@example.com"
DATA = {CONF_EMAIL: EMAIL, CONF_TOKEN: "session.sig"}


def _legacy_entry(hass):
    entry = MockConfigEntry(domain=LEGACY_DOMAIN, unique_id=EMAIL, title=EMAIL, data=DATA)
    entry.add_to_hass(hass)
    return entry


def _legacy_integration(documentation=DOCUMENTATION_URL):
    integration = SimpleNamespace(
        is_built_in=False,
        documentation=documentation,
        file_path=Path("/config/custom_components/georide"),
    )
    return patch(
        "custom_components.georide_ha.async_get_integration",
        AsyncMock(return_value=integration),
    )


class TestImportStep:
    async def test_creates_entry_with_the_old_session(self, hass):
        old = _legacy_entry(hass)
        with patch("custom_components.georide_ha.async_setup_entry", AsyncMock(return_value=True)):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data={"entry_id": old.entry_id}
            )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == EMAIL
        assert result["data"] == DATA
        assert result["result"].unique_id == EMAIL

    async def test_aborts_when_already_taken_over(self, hass):
        old = _legacy_entry(hass)
        MockConfigEntry(domain=DOMAIN, unique_id=EMAIL, data=DATA).add_to_hass(hass)
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data={"entry_id": old.entry_id}
        )
        assert result["type"] is FlowResultType.ABORT

    async def test_aborts_when_the_old_entry_is_gone(self, hass):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_IMPORT}, data={"entry_id": "gone"}
        )
        assert result["type"] is FlowResultType.ABORT


class TestAdoption:
    async def test_moves_devices_and_entities_then_removes_old_entry(self, hass):
        old = _legacy_entry(hass)
        new = MockConfigEntry(domain=DOMAIN, unique_id=EMAIL, data=DATA)
        new.add_to_hass(hass)
        device = dr.async_get(hass).async_get_or_create(
            config_entry_id=old.entry_id, identifiers={(LEGACY_DOMAIN, "2216122")}
        )
        entity = er.async_get(hass).async_get_or_create(
            "sensor", LEGACY_DOMAIN, "2216122-odometer",
            config_entry=old, device_id=device.id, suggested_object_id="z900_odometer",
        )
        with _legacy_integration():
            await _async_adopt_legacy_entry(hass, new)

        moved = er.async_get(hass).async_get(entity.entity_id)
        assert moved.entity_id == "sensor.z900_odometer"  # same entity_id → history kept
        assert moved.platform == DOMAIN
        assert moved.config_entry_id == new.entry_id
        device = dr.async_get(hass).async_get(device.id)
        assert device.identifiers == {(DOMAIN, "2216122")}
        assert device.config_entry_id == new.entry_id
        assert hass.config_entries.async_get_entry(old.entry_id) is None
        assert new.data[CONF_LEGACY] is True

    async def test_leaves_the_other_georide_integration_alone(self, hass):
        old = _legacy_entry(hass)
        new = MockConfigEntry(domain=DOMAIN, unique_id=EMAIL, data=DATA)
        new.add_to_hass(hass)
        with _legacy_integration("https://github.com/ptimatth/GeorideHA"):
            await _async_adopt_legacy_entry(hass, new)
        assert hass.config_entries.async_get_entry(old.entry_id) is not None
        assert CONF_LEGACY not in new.data

    async def test_nothing_to_do_without_the_old_folder(self, hass):
        new = MockConfigEntry(domain=DOMAIN, unique_id=EMAIL, data=DATA)
        new.add_to_hass(hass)
        with patch(
            "custom_components.georide_ha.async_get_integration",
            AsyncMock(side_effect=IntegrationNotFound(LEGACY_DOMAIN)),
        ):
            await _async_adopt_legacy_entry(hass, new)
        assert CONF_LEGACY not in new.data


class TestLegacyNames:
    async def test_taken_over_entry_fires_both_event_names(self, hass):
        entry = MockConfigEntry(domain=DOMAIN, unique_id=EMAIL, data={**DATA, CONF_LEGACY: True})
        entry.add_to_hass(hass)
        coord = GeoRideCoordinator(hass, entry, MagicMock())
        fired: list[str] = []
        hass.bus.async_listen(EVENT_MOVING, lambda e: fired.append(e.event_type))
        hass.bus.async_listen("georide_moving_event", lambda e: fired.append(e.event_type))
        coord._fire(EVENT_MOVING, {"moving": True})
        await hass.async_block_till_done()
        assert sorted(fired) == ["georide_ha_moving_event", "georide_moving_event"]

    async def test_old_service_is_described_without_an_error(self, hass, caplog):
        """HA must not look for a services.yaml in the gone `georide` integration."""
        from homeassistant.helpers.service import async_get_all_descriptions

        from custom_components.georide_ha.services import async_setup_services

        await async_setup_services(hass, LEGACY_DOMAIN)
        descriptions = await async_get_all_descriptions(hass)
        assert "start_date" in descriptions[LEGACY_DOMAIN]["trip_summary"]["fields"]
        assert "Failed to load services.yaml" not in caplog.text

    async def test_old_service_name_is_registered(self, hass):
        await services.async_setup_services(hass, LEGACY_DOMAIN)
        assert hass.services.has_service(LEGACY_DOMAIN, services.SERVICE_TRIP_SUMMARY)
