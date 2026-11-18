"""0.17.7 hands its entries over to georide_ha (0.18) once HACS installed it."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("pytest_homeassistant")

from homeassistant.config_entries import SOURCE_IMPORT  # noqa: E402
from homeassistant.loader import IntegrationNotFound  # noqa: E402
from pytest_homeassistant.common import MockConfigEntry  # noqa: E402

import custom_components.georide as georide  # noqa: E402
from custom_components.georide.const import DOMAIN  # noqa: E402


def _new_domain(installed: bool):
    side_effect = None if installed else IntegrationNotFound("georide_ha")
    return patch(
        "custom_components.georide.async_get_integration",
        AsyncMock(return_value=SimpleNamespace(), side_effect=side_effect),
    )


async def test_hands_the_entry_over_without_loading_platforms(hass):
    entry = MockConfigEntry(domain=DOMAIN, unique_id="bike@example.com", data={"token": "t"})
    entry.add_to_hass(hass)
    with _new_domain(True), patch.object(
        hass.config_entries.flow, "async_init", AsyncMock()
    ) as init, patch.object(hass.config_entries, "async_forward_entry_setups") as forward, patch(
        "custom_components.georide.GeoRideApiClient"
    ) as client:
        assert await georide.async_setup_entry(hass, entry)
        await hass.async_block_till_done()
    init.assert_awaited_once_with(
        "georide_ha", context={"source": SOURCE_IMPORT}, data={"entry_id": entry.entry_id}
    )
    forward.assert_not_called()
    client.assert_not_called()
    assert await georide.async_unload_entry(hass, entry)


async def test_services_left_to_the_new_domain(hass):
    with _new_domain(True):
        assert await georide.async_setup(hass, {})
    assert not hass.services.has_service(DOMAIN, "trip_summary")
    with _new_domain(False):
        assert await georide.async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, "trip_summary")
