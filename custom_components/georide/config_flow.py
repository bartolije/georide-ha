"""Config flow for the GeoRide integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    GeoRideApiClient,
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
)
from .const import CONF_TOKEN_CREATED_AT, DOMAIN

_LOGGER = logging.getLogger(__name__)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

STEP_PASSWORD_ONLY_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


def _token_data(token: str | None) -> dict[str, Any]:
    """Token + mint date, ready to merge into config entry data.

    The mint date lets the coordinator renew the token via /user/new-token
    before its 30-day expiry.
    """
    return {
        CONF_TOKEN: token,
        CONF_TOKEN_CREATED_AT: datetime.now(tz=timezone.utc).isoformat(),
    }


async def _authenticate(
    hass: HomeAssistant, email: str, password: str
) -> tuple[str | None, str | None]:
    """Login + validate the resulting token. Return (token, error_key)."""
    session = async_get_clientsession(hass)
    client = GeoRideApiClient(session)
    try:
        token = await client.login(email, password)
        await client.get_trackers()
    except GeoRideAuthError:
        return None, "invalid_auth"
    except GeoRideConnectionError:
        return None, "cannot_connect"
    except GeoRideError:
        _LOGGER.exception("Unexpected GeoRide API error during login")
        return None, "unknown"
    return token, None


class GeoRideConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GeoRide."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial step: collect email + password, validate, store token."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            token, error = await _authenticate(
                self.hass, email, user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=email,
                    data={CONF_EMAIL: email, **_token_data(token)},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Triggered when ConfigEntryAuthFailed is raised at runtime."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-prompt for the password to mint a fresh token."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        email = entry.data[CONF_EMAIL]

        if user_input is not None:
            token, error = await _authenticate(
                self.hass, email, user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, **_token_data(token)}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_PASSWORD_ONLY_SCHEMA,
            description_placeholders={"email": email},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """User-initiated reconfigure (Settings → Devices → Configure)."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        email = entry.data[CONF_EMAIL]

        if user_input is not None:
            token, error = await _authenticate(
                self.hass, email, user_input[CONF_PASSWORD]
            )
            if error:
                errors["base"] = error
            else:
                return self.async_update_reload_and_abort(
                    entry, data={**entry.data, **_token_data(token)}
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=STEP_PASSWORD_ONLY_SCHEMA,
            description_placeholders={"email": email},
            errors=errors,
        )
