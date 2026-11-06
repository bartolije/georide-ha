"""Config flow for the GeoRide integration.

GeoRide v2 logs in without a password: the user receives a one-time code by
email and types it here; the flow stores the resulting session cookie.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import aiohttp
try:
    import probatio as vol  # type: ignore[import-not-found, unused-ignore]  # HA 2026.11+
except ImportError:  # older Home Assistant
    import voluptuous as vol  # type: ignore[no-redef, unused-ignore]

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_TOKEN
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import (
    GeoRideApiClient,
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CONF_OTP = "otp"

STEP_USER_DATA_SCHEMA = vol.Schema({vol.Required(CONF_EMAIL): str})
STEP_OTP_DATA_SCHEMA = vol.Schema({vol.Required(CONF_OTP): str})


class GeoRideConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GeoRide."""

    VERSION = 1

    def __init__(self) -> None:
        self._email = ""
        self._entry: ConfigEntry | None = None  # set for reauth / reconfigure
        self._client: GeoRideApiClient | None = None

    def _api(self) -> GeoRideApiClient:
        if self._client is None:
            # Own session without cookie jar: the session cookie is sent explicitly.
            session = async_create_clientsession(
                self.hass, cookie_jar=aiohttp.DummyCookieJar()
            )
            self._client = GeoRideApiClient(session)
        return self._client

    async def _send_code(self) -> str | None:
        """Mail a login code to self._email. Return an error key or None."""
        try:
            await self._api().send_otp(self._email)
        except GeoRideConnectionError:
            return "cannot_connect"
        except GeoRideError:
            _LOGGER.exception("Unexpected GeoRide API error while sending the code")
            return "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial step: collect the email and send the login code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            await self.async_set_unique_id(self._email.lower())
            self._abort_if_unique_id_configured()
            error = await self._send_code()
            if error is None:
                return await self.async_step_otp()
            errors["base"] = error

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_otp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Exchange the mailed code for a session and store it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = self._api()
            try:
                token = await client.verify_otp(self._email, user_input[CONF_OTP].strip())
                await client.get_trackers()
            except GeoRideAuthError:
                errors["base"] = "invalid_code"
            except GeoRideConnectionError:
                errors["base"] = "cannot_connect"
            except GeoRideError:
                _LOGGER.exception("Unexpected GeoRide API error during login")
                errors["base"] = "unknown"
            else:
                data = {CONF_EMAIL: self._email, CONF_TOKEN: token}
                if self._entry is not None:
                    return self.async_update_reload_and_abort(self._entry, data=data)
                return self.async_create_entry(title=self._email, data=data)

        return self.async_show_form(
            step_id="otp",
            data_schema=STEP_OTP_DATA_SCHEMA,
            description_placeholders={"email": self._email},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Triggered when the session expired (or the entry still holds a v1 token)."""
        self._entry = self._get_reauth_entry()
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm, then mail a new code to the account's email."""
        return await self._confirm_and_send("reauth_confirm", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """User-initiated reconfigure (Settings → Devices → Configure)."""
        self._entry = self._get_reconfigure_entry()
        return await self._confirm_and_send("reconfigure", user_input)

    async def _confirm_and_send(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        assert self._entry is not None
        self._email = self._entry.data[CONF_EMAIL]
        errors: dict[str, str] = {}
        if user_input is not None:
            error = await self._send_code()
            if error is None:
                return await self.async_step_otp()
            errors["base"] = error
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({}),
            description_placeholders={"email": self._email},
            errors=errors,
        )
