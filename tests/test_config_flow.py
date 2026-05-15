"""Offline tests for the config flow (user / reauth / reconfigure).

Requires `pytest-homeassistant-custom-component`. Skipped automatically on
venvs that don't have Home Assistant installed.
"""
from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, patch

import pytest

# Skip the whole file unless pytest-homeassistant-custom-component is
# installed. The lightweight conftest shim fakes a `homeassistant` module
# for the API-only tests, so `importorskip("homeassistant")` is not enough
# — we need a marker library that only the real HA test environment has.
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.georide.api import (
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
)
from custom_components.georide.const import DOMAIN

EMAIL = "rider@example.com"
PASSWORD = "moto-power"
TOKEN = "tok-abc-123"


@contextlib.contextmanager
def _mock_client(*, login_return=TOKEN, login_raises=None, trackers_raises=None):
    """Patch every use-site of GeoRideApiClient so the network is never touched.

    `from .api import GeoRideApiClient` creates a binding per importer, so
    config_flow and __init__ need separate patches; otherwise an entry that
    reaches CREATE_ENTRY triggers async_setup_entry which would dial the
    real GeoRide API.

    `async_get_clientsession` is also stubbed to avoid spinning up the
    aiohttp resolver thread — it would linger past teardown and trip
    pytest-homeassistant-custom-component's cleanup verifier.
    """

    def _factory(*args, **kwargs):
        client = AsyncMock()
        if login_raises is not None:
            client.login = AsyncMock(side_effect=login_raises)
        else:
            client.login = AsyncMock(return_value=login_return)
        if trackers_raises is not None:
            client.get_trackers = AsyncMock(side_effect=trackers_raises)
        else:
            client.get_trackers = AsyncMock(return_value=[])
        client.get_tracker_beacons = AsyncMock(return_value=[])
        client.token = login_return
        return client

    fake_session = AsyncMock()

    with patch(
        "custom_components.georide.config_flow.GeoRideApiClient",
        side_effect=_factory,
    ), patch(
        "custom_components.georide.GeoRideApiClient",
        side_effect=_factory,
    ), patch(
        "custom_components.georide.config_flow.async_get_clientsession",
        return_value=fake_session,
    ), patch(
        "custom_components.georide.async_get_clientsession",
        return_value=fake_session,
    ):
        yield


# ---------------------------------------------------------------------------
# async_step_user
# ---------------------------------------------------------------------------
class TestUserFlow:
    async def test_happy_path_creates_entry(self, hass):
        with _mock_client():
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "user"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD},
            )
            # Drain the post-create_entry setup under the patch so the
            # background tasks don't leak a real aiohttp resolver.
            await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == EMAIL
        assert result["data"] == {CONF_EMAIL: EMAIL, CONF_TOKEN: TOKEN}

    async def test_invalid_auth_shows_error(self, hass):
        with _mock_client(login_raises=GeoRideAuthError("bad creds")):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_EMAIL: EMAIL, CONF_PASSWORD: "wrong"},
            )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}

    async def test_cannot_connect_shows_error(self, hass):
        with _mock_client(login_raises=GeoRideConnectionError("dns")):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD},
            )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}

    async def test_unknown_error_shows_generic(self, hass):
        with _mock_client(login_raises=GeoRideError("weird")):
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD},
            )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}

    async def test_duplicate_account_aborts(self, hass):
        MockConfigEntry(
            domain=DOMAIN,
            unique_id=EMAIL.lower(),
            data={CONF_EMAIL: EMAIL, CONF_TOKEN: "old"},
        ).add_to_hass(hass)

        with _mock_client():
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": config_entries.SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_EMAIL: EMAIL, CONF_PASSWORD: PASSWORD},
            )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"


# ---------------------------------------------------------------------------
# async_step_reauth
# ---------------------------------------------------------------------------
class TestReauthFlow:
    async def test_reauth_updates_token(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=EMAIL.lower(),
            data={CONF_EMAIL: EMAIL, CONF_TOKEN: "stale"},
        )
        entry.add_to_hass(hass)

        with _mock_client(login_return="fresh-tok"):
            result = await entry.start_reauth_flow(hass)
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "reauth_confirm"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_PASSWORD: PASSWORD},
            )
            # async_update_reload_and_abort schedules the reload as a
            # background task. Drain it under the patch so the reloaded
            # async_setup_entry doesn't spin up a real aiohttp resolver.
            await hass.async_block_till_done()
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert entry.data[CONF_TOKEN] == "fresh-tok"

    async def test_reauth_invalid_auth(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=EMAIL.lower(),
            data={CONF_EMAIL: EMAIL, CONF_TOKEN: "stale"},
        )
        entry.add_to_hass(hass)

        with _mock_client(login_raises=GeoRideAuthError("still bad")):
            result = await entry.start_reauth_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_PASSWORD: "still-wrong"},
            )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}
        # Token not touched on failure.
        assert entry.data[CONF_TOKEN] == "stale"


# ---------------------------------------------------------------------------
# async_step_reconfigure
# ---------------------------------------------------------------------------
class TestReconfigureFlow:
    async def test_reconfigure_updates_token(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id=EMAIL.lower(),
            data={CONF_EMAIL: EMAIL, CONF_TOKEN: "old"},
        )
        entry.add_to_hass(hass)

        with _mock_client(login_return="reconfig-tok"):
            result = await entry.start_reconfigure_flow(hass)
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "reconfigure"

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_PASSWORD: PASSWORD},
            )
            await hass.async_block_till_done()
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_TOKEN] == "reconfig-tok"
