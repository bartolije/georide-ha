"""Tests for the georide.trip_summary service."""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.const import CONF_EMAIL, CONF_TOKEN
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.georide import services
from custom_components.georide.api import (
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
)
from custom_components.georide.const import DOMAIN


def _trip(**overrides):
    base = {
        "id": 1,
        "trackerId": 999,
        "startTime": "2026-04-16T06:47:18.600Z",
        "endTime": "2026-04-16T06:54:57.800Z",
        "distance": 7118,
        "averageSpeed": 30.0,
        "maxSpeed": 60.0,
        "maxAngle": 25.0,
    }
    base.update(overrides)
    return base


def _entry(hass, *, trackers=None, trips=None, client_raises=None):
    """Build a mock GeoRide config entry wired with a fake coordinator."""
    if trackers is None:
        trackers = [{"trackerId": 999, "trackerName": "Test bike"}]
    if trips is None:
        trips = [_trip()]

    client = AsyncMock()
    if client_raises is not None:
        client.get_trips = AsyncMock(side_effect=client_raises)
    else:
        client.get_trips = AsyncMock(return_value=trips)

    coordinator = MagicMock()
    coordinator.client = client
    coordinator.data = {t["trackerId"]: t for t in trackers}

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="bike@example.com",
        data={CONF_EMAIL: "bike@example.com", CONF_TOKEN: "t"},
    )
    entry.add_to_hass(hass)
    entry.runtime_data = coordinator
    return entry, coordinator, client


async def _call_service(hass, **data):
    return await hass.services.async_call(
        DOMAIN,
        services.SERVICE_TRIP_SUMMARY,
        data,
        blocking=True,
        return_response=True,
    )


class TestTripSummaryHappyPath:
    async def test_aggregates_single_tracker(self, hass):
        _entry(hass)
        await services.async_setup_services(hass)

        result = await _call_service(
            hass,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
        )

        assert "trackers" in result and "999" in result["trackers"]
        per_tracker = result["trackers"]["999"]
        assert per_tracker["tracker_name"] == "Test bike"
        assert per_tracker["summary"]["trips_count"] == 1
        assert per_tracker["summary"]["total_km"] == 7.12
        # Aggregate matches single-tracker stats here.
        assert result["aggregate"]["total_km"] == 7.12

    async def test_include_trips_returns_raw(self, hass):
        _entry(hass)
        await services.async_setup_services(hass)

        result = await _call_service(
            hass,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            include_trips=True,
        )
        assert "trips" in result["trackers"]["999"]
        assert result["trackers"]["999"]["trips"][0]["id"] == 1

    async def test_filter_by_tracker_id(self, hass):
        _entry(
            hass,
            trackers=[
                {"trackerId": 1, "trackerName": "A"},
                {"trackerId": 2, "trackerName": "B"},
            ],
        )
        await services.async_setup_services(hass)

        result = await _call_service(
            hass,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            tracker_id=2,
        )
        # Only tracker 2 should appear in the per-tracker breakdown.
        assert list(result["trackers"].keys()) == ["2"]


class TestTripSummaryErrors:
    async def test_invalid_date_range_raises_validation_error(self, hass):
        _entry(hass)
        await services.async_setup_services(hass)

        with pytest.raises(ServiceValidationError):
            await _call_service(
                hass,
                start_date=date(2026, 5, 30),
                end_date=date(2026, 5, 1),  # end < start
            )

    async def test_unknown_tracker_id_raises_validation_error(self, hass):
        _entry(hass)
        await services.async_setup_services(hass)

        with pytest.raises(ServiceValidationError):
            await _call_service(
                hass,
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 30),
                tracker_id="not-a-real-tracker",
            )

    async def test_no_entry_configured_raises(self, hass):
        await services.async_setup_services(hass)
        with pytest.raises(HomeAssistantError):
            await _call_service(
                hass,
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 30),
            )

    async def test_auth_error_propagates(self, hass):
        _entry(hass, client_raises=GeoRideAuthError("token rejected"))
        await services.async_setup_services(hass)
        with pytest.raises(HomeAssistantError):
            await _call_service(
                hass,
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 30),
            )

    async def test_connection_error_propagates(self, hass):
        _entry(hass, client_raises=GeoRideConnectionError("dns"))
        await services.async_setup_services(hass)
        with pytest.raises(HomeAssistantError):
            await _call_service(
                hass,
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 30),
            )

    async def test_api_error_propagates(self, hass):
        _entry(hass, client_raises=GeoRideError("weird"))
        await services.async_setup_services(hass)
        with pytest.raises(HomeAssistantError):
            await _call_service(
                hass,
                start_date=date(2026, 4, 1),
                end_date=date(2026, 4, 30),
            )


class TestIdempotency:
    async def test_setup_services_is_idempotent(self, hass):
        _entry(hass)
        await services.async_setup_services(hass)
        # Second call must not raise nor double-register.
        await services.async_setup_services(hass)
        assert hass.services.has_service(DOMAIN, services.SERVICE_TRIP_SUMMARY)
