"""Constants for the GeoRide integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "georide"
MANUFACTURER = "GeoRide"

# ISO 8601 timestamp of when the stored bearer token was minted. GeoRide
# tokens expire 30 days after creation; the coordinator uses this to renew
# the token proactively via /user/new-token.
CONF_TOKEN_CREATED_AT = "token_created_at"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.LOCK,
    Platform.SENSOR,
    Platform.SIREN,
    Platform.SWITCH,
]

API_HOST = "https://api.georide.com"
API_TIMEOUT = 30

# Home Assistant events fired by the coordinator on tracker state transitions.
EVENT_LOCK = f"{DOMAIN}_lock_event"
EVENT_MOVING = f"{DOMAIN}_moving_event"
EVENT_ALARM = f"{DOMAIN}_alarm_event"
