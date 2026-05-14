"""Service handlers for the GeoRide integration."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv

from .api import (
    GeoRideApiClient,
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
)
from .const import DOMAIN
from .stats import summarize as _summarize

_LOGGER = logging.getLogger(__name__)

SERVICE_TRIP_SUMMARY = "trip_summary"

TRIP_SUMMARY_SCHEMA = vol.Schema(
    {
        vol.Required("start_date"): cv.date,
        vol.Required("end_date"): cv.date,
        vol.Optional("tracker_id"): vol.Any(int, cv.string),
        vol.Optional("include_trips", default=False): cv.boolean,
    }
)


def _to_utc_iso(d: date, *, end_of_day: bool = False) -> str:
    """Convert a date to an ISO 8601 UTC datetime string."""
    t = datetime.combine(
        d,
        datetime.max.time().replace(microsecond=0) if end_of_day else datetime.min.time(),
        tzinfo=timezone.utc,
    )
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register integration services (idempotent)."""

    if hass.services.has_service(DOMAIN, SERVICE_TRIP_SUMMARY):
        return

    async def handle_trip_summary(call: ServiceCall) -> ServiceResponse:
        start_d: date = call.data["start_date"]
        end_d: date = call.data["end_date"]
        if start_d > end_d:
            raise ServiceValidationError("start_date must be on or before end_date")

        from_iso = _to_utc_iso(start_d)
        to_iso = _to_utc_iso(end_d, end_of_day=True)
        requested = call.data.get("tracker_id")
        include_trips = call.data["include_trips"]

        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if hasattr(e, "runtime_data") and e.runtime_data is not None
        ]
        if not entries:
            raise HomeAssistantError("GeoRide integration is not configured")

        per_tracker: dict[str, Any] = {}
        all_trips: list[dict[str, Any]] = []
        matched = False

        for entry in entries:
            coordinator = entry.runtime_data  # GeoRideCoordinator
            client: GeoRideApiClient = coordinator.client
            trackers_by_id: dict[int, dict[str, Any]] = coordinator.data or {}

            for tid, tracker in trackers_by_id.items():
                if requested is not None and str(requested) != str(tid):
                    continue
                matched = True

                try:
                    trips = await client.get_trips(tid, from_iso, to_iso)
                except GeoRideAuthError as err:
                    raise HomeAssistantError(
                        f"GeoRide token expired or rejected: {err}"
                    ) from err
                except GeoRideConnectionError as err:
                    raise HomeAssistantError(
                        f"Cannot reach GeoRide: {err}"
                    ) from err
                except GeoRideError as err:
                    raise HomeAssistantError(str(err)) from err

                if trips:
                    _LOGGER.info(
                        "GeoRide trips: tracker=%s count=%d keys=%s",
                        tid,
                        len(trips),
                        sorted(trips[0].keys()),
                    )

                summary = _summarize(trips)
                tracker_entry: dict[str, Any] = {
                    "tracker_name": tracker.get("trackerName") or tracker.get("name"),
                    "summary": summary,
                }
                if include_trips:
                    tracker_entry["trips"] = trips
                per_tracker[str(tid)] = tracker_entry
                all_trips.extend(trips)

        if requested is not None and not matched:
            raise ServiceValidationError(
                f"No configured tracker matches tracker_id={requested}"
            )

        response: dict[str, Any] = {
            "range": {"from": from_iso, "to": to_iso},
            "trackers": per_tracker,
            "aggregate": _summarize(all_trips),
        }
        return response

    hass.services.async_register(
        DOMAIN,
        SERVICE_TRIP_SUMMARY,
        handle_trip_summary,
        schema=TRIP_SUMMARY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
