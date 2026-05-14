"""Constants for the GeoRide integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "georide"
MANUFACTURER = "GeoRide"

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
]

API_HOST = "https://api.georide.com"
API_TIMEOUT = 30
