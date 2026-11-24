"""Constants for the GeoRide integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "georide_ha"
MANUFACTURER = "GeoRide"

# Domain up to 0.17, renamed so the integration can sit next to
# ptimatth/GeorideHA in HACS. Its entries are taken over at setup (__init__).
LEGACY_DOMAIN = "georide"
# Set on entries taken over from LEGACY_DOMAIN: they keep its event and service names.
CONF_LEGACY = "legacy_domain"
DOCUMENTATION_URL = "https://github.com/bartolije/georide-ha"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.UPDATE,
]

API_HOST = "https://api-v2.georide.com"
API_TIMEOUT = 30

# Home Assistant events fired by the coordinator on tracker state transitions.
EVENT_MOVING = f"{DOMAIN}_moving_event"
EVENT_ALARM = f"{DOMAIN}_alarm_event"
