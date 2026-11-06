"""Offline tests for the config flow (user / otp / reauth / reconfigure).

Requires `pytest-homeassistant-custom-component`. Skipped automatically on
venvs that don't have Home Assistant installed.
"""
from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip the whole file unless pytest-homeassistant-custom-component is
# installed. The lightweight conftest shim fakes a `homeassistant` module
# for the API-only tests, so `importorskip("homeassistant")` is not enough
# — we need a marker library that only the real HA test environment has.
pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_TOKEN
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.georide.api import (
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
)
from custom_components.georide.config_flow import CONF_OTP
from custom_components.georide.const import DOMAIN

EMAIL = "rider@example.com"
CODE = "123456"
TOKEN = "tok.sig"


@contextlib.contextmanager
def _mock_client(*, verify_return=TOKEN, verify_raises=None, send_raises=None, trackers_raises=None):
    """Patch every use-site of GeoRideApiClient so the network is never touched.

    `from .api import GeoRideApiClient` creates a binding per importer, so
    config_flow and __init__ need separate patches; otherwise an entry that
    reaches CREATE_ENTRY triggers async_setup_entry which would dial the
    real GeoRide API. The session factory is stubbed too, so no aiohttp
    resolver thread lingers past teardown.
    """
    clients: list[AsyncMock] = []

    def _factory(*args, **kwargs):
        client = AsyncMock()
        client.send_otp = AsyncMock(side_effect=send_raises)
        if verify_raises is not None:
            client.verify_otp = AsyncMock(side_effect=verify_raises)
        else:
            client.verify_otp = AsyncMock(return_value=verify_return)
        if trackers_raises is not None:
            client.get_trackers = AsyncMock(side_effect=trackers_raises)
        else:
            client.get_trackers = AsyncMock(return_value=[])
        client.get_tracker_beacons = AsyncMock(return_value=[])
        client.get_maintenance = AsyncMock(return_value=[])
        client.get_events = AsyncMock(return_value=[])
        clients.append(client)
        return client

    with patch(
        "custom_components.georide.config_flow.GeoRideApiClient", side_effect=_factory
    ), patch(
        "custom_components.georide.GeoRideApiClient", side_effect=_factory
    ), patch(
        "custom_components.georide.config_flow.async_create_clientsession",
        return_value=MagicMock(),
    ), patch(
        "custom_components.georide.async_create_clientsession",
        return_value=MagicMock(),
    ):
        yield clients


async def _start_user(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMAIL: EMAIL}
    )


# ---------------------------------------------------------------------------
# async_step_user + async_step_otp
# ---------------------------------------------------------------------------
class TestUserFlow:
    async def test_happy_path_creates_entry(self, hass):
        with _mock_client() as clients:
            result = await _start_user(hass)
            assert result["step_id"] == "otp"
            clients[0].send_otp.assert_awaited_once_with(EMAIL)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_OTP: f" {CODE} "}
            )
            # Drain the post-create_entry setup under the patch so the
            # background tasks don't leak a real aiohttp resolver.
            await hass.async_block_till_done()
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == EMAIL
        assert result["data"] == {CONF_EMAIL: EMAIL, CONF_TOKEN: TOKEN}
        clients[0].verify_otp.assert_awaited_once_with(EMAIL, CODE)

    async def test_invalid_code_shows_error_and_stays(self, hass):
        with _mock_client(verify_raises=GeoRideAuthError("bad code")):
            result = await _start_user(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_OTP: "000000"}
            )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "otp"
        assert result["errors"] == {"base": "invalid_code"}

    @pytest.mark.parametrize(
        ("exc", "error"),
        [(GeoRideConnectionError("dns"), "cannot_connect"), (GeoRideError("weird"), "unknown")],
    )
    async def test_send_errors(self, hass, exc, error):
        with _mock_client(send_raises=exc):
            result = await _start_user(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": error}

    async def test_validation_error_after_code(self, hass):
        with _mock_client(trackers_raises=GeoRideConnectionError("down")):
            result = await _start_user(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_OTP: CODE}
            )
        assert result["errors"] == {"base": "cannot_connect"}

    async def test_duplicate_account_aborts(self, hass):
        MockConfigEntry(
            domain=DOMAIN,
            unique_id=EMAIL.lower(),
            data={CONF_EMAIL: EMAIL, CONF_TOKEN: "old"},
        ).add_to_hass(hass)

        with _mock_client() as clients:
            result = await _start_user(hass)
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"
        assert all(not c.send_otp.await_count for c in clients)


# ---------------------------------------------------------------------------
# async_step_reauth / async_step_reconfigure
# ---------------------------------------------------------------------------
def _entry(hass, token="v1-jwt"):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=EMAIL.lower(),
        data={CONF_EMAIL: EMAIL, CONF_TOKEN: token, "token_created_at": "2026-10-01T00:00:00+00:00"},
    )
    entry.add_to_hass(hass)
    return entry


class TestReauthFlow:
    async def test_reauth_sends_code_and_replaces_v1_data(self, hass):
        entry = _entry(hass)
        with _mock_client(verify_return="fresh.sig") as clients:
            result = await entry.start_reauth_flow(hass)
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "reauth_confirm"

            result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
            assert result["step_id"] == "otp"
            clients[0].send_otp.assert_awaited_once_with(EMAIL)

            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_OTP: CODE}
            )
            # async_update_reload_and_abort schedules the reload as a
            # background task. Drain it under the patch.
            await hass.async_block_till_done()
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        # v1 leftovers (token_created_at) are dropped.
        assert entry.data == {CONF_EMAIL: EMAIL, CONF_TOKEN: "fresh.sig"}

    async def test_reauth_invalid_code_keeps_entry(self, hass):
        entry = _entry(hass, token="stale")
        with _mock_client(verify_raises=GeoRideAuthError("still bad")):
            result = await entry.start_reauth_flow(hass)
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_OTP: "000000"}
            )
        assert result["errors"] == {"base": "invalid_code"}
        assert entry.data[CONF_TOKEN] == "stale"

    async def test_reauth_send_failure(self, hass):
        entry = _entry(hass)
        with _mock_client(send_raises=GeoRideConnectionError("down")):
            result = await entry.start_reauth_flow(hass)
            result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["step_id"] == "reauth_confirm"
        assert result["errors"] == {"base": "cannot_connect"}


class TestReconfigureFlow:
    async def test_reconfigure_updates_token(self, hass):
        entry = _entry(hass, token="old")
        with _mock_client(verify_return="reconfig.sig"):
            result = await entry.start_reconfigure_flow(hass)
            assert result["type"] is FlowResultType.FORM
            assert result["step_id"] == "reconfigure"

            result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_OTP: CODE}
            )
            await hass.async_block_till_done()
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert entry.data[CONF_TOKEN] == "reconfig.sig"
