"""Tests for diagnostics download — checks redaction and lookups."""
from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from datetime import timedelta  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from homeassistant.const import CONF_EMAIL, CONF_TOKEN  # noqa: E402
from homeassistant.helpers import device_registry as dr  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.georide import diagnostics  # noqa: E402
from custom_components.georide.const import DOMAIN  # noqa: E402


def _mock_coordinator(trackers):
    coord = MagicMock()
    coord.data = {t["trackerId"]: t for t in trackers}
    coord.last_update_success = True
    coord.update_interval = timedelta(seconds=60)
    return coord


SAMPLE_TRACKER = {
    "trackerId": 999,
    "trackerName": "Test bike",
    "latitude": 45.7,
    "longitude": 4.8,
    "lockedLatitude": 45.7,
    "lockedLongitude": 4.8,
    "altitude": 250,
    "odometer": 12345,
    "isLocked": True,
}


class TestEntryDiagnostics:
    async def test_redacts_token_email_and_unique_id(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="bike@example.com",
            data={CONF_EMAIL: "bike@example.com", CONF_TOKEN: "very-secret"},
        )
        entry.add_to_hass(hass)
        entry.runtime_data = _mock_coordinator([SAMPLE_TRACKER])

        result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)

        # Sensitive entry fields are masked.
        assert "very-secret" not in str(result)
        assert result["entry"]["data"][CONF_TOKEN] == "**REDACTED**"
        assert result["entry"]["data"][CONF_EMAIL] == "**REDACTED**"

    async def test_redacts_tracker_coordinates(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="bike@example.com",
            data={CONF_EMAIL: "bike@example.com", CONF_TOKEN: "t"},
        )
        entry.add_to_hass(hass)
        entry.runtime_data = _mock_coordinator([SAMPLE_TRACKER])

        result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
        tracker = result["trackers"][0]
        # GPS lat/lon and lockedLat/lon must be redacted.
        for key in ("latitude", "longitude", "lockedLatitude", "lockedLongitude", "altitude"):
            assert tracker[key] == "**REDACTED**", key
        # Non-sensitive fields stay.
        assert tracker["trackerName"] == "Test bike"
        assert tracker["odometer"] == 12345

    async def test_includes_coordinator_meta(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="bike@example.com",
            data={CONF_EMAIL: "x", CONF_TOKEN: "t"},
        )
        entry.add_to_hass(hass)
        entry.runtime_data = _mock_coordinator([SAMPLE_TRACKER])

        result = await diagnostics.async_get_config_entry_diagnostics(hass, entry)
        assert result["update_interval_seconds"] == 60.0
        assert result["last_update_success"] is True


class TestDeviceDiagnostics:
    async def test_returns_redacted_tracker_payload(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="bike@example.com",
            data={CONF_EMAIL: "x", CONF_TOKEN: "t"},
        )
        entry.add_to_hass(hass)
        entry.runtime_data = _mock_coordinator([SAMPLE_TRACKER])

        # Register the device in the device registry so async_get_device works.
        device_registry = dr.async_get(hass)
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "999")},
            name="Test bike",
        )

        result = await diagnostics.async_get_device_diagnostics(hass, entry, device)
        assert "tracker" in result
        assert result["tracker"]["latitude"] == "**REDACTED**"
        assert result["tracker"]["trackerName"] == "Test bike"

    async def test_unknown_tracker_returns_error(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="bike@example.com",
            data={CONF_EMAIL: "x", CONF_TOKEN: "t"},
        )
        entry.add_to_hass(hass)
        entry.runtime_data = _mock_coordinator([])  # empty snapshot

        # Build a device with an identifier the coordinator doesn't know.
        device_registry = dr.async_get(hass)
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "404")},
            name="Phantom",
        )

        result = await diagnostics.async_get_device_diagnostics(hass, entry, device)
        assert "error" in result

    async def test_no_georide_identifier_returns_error(self, hass):
        entry = MockConfigEntry(
            domain=DOMAIN,
            unique_id="bike@example.com",
            data={CONF_EMAIL: "x", CONF_TOKEN: "t"},
        )
        entry.add_to_hass(hass)
        entry.runtime_data = _mock_coordinator([SAMPLE_TRACKER])

        # Device with only a non-georide identifier (would be a HA bug if ever
        # happened, but the diagnostics code guards against it).
        device_registry = dr.async_get(hass)
        device = device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={("other_domain", "x")},
            name="Foreign",
        )

        result = await diagnostics.async_get_device_diagnostics(hass, entry, device)
        assert "error" in result
