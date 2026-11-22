"""Service handlers for the GeoRide integration."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

try:
    import probatio as vol  # type: ignore[import-not-found, unused-ignore]  # HA 2026.11+
except ImportError:  # older Home Assistant
    import voluptuous as vol  # type: ignore[no-redef, unused-ignore]

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.helpers.config_validation as cv
from homeassistant.util import dt as dt_util

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
    """Start (or last second) of local day `d` in Home Assistant's time zone, as UTC ISO 8601."""
    t = dt_util.start_of_local_day(d + timedelta(days=1) if end_of_day else d)
    if end_of_day:
        t -= timedelta(seconds=1)
    return dt_util.as_utc(t).strftime("%Y-%m-%dT%H:%M:%SZ")


async def async_setup_services(hass: HomeAssistant, domain: str = DOMAIN) -> None:
    """Register integration services (idempotent).

    `domain` is LEGACY_DOMAIN for the 0.17 service name kept for entries taken over.
    """

    if hass.services.has_service(domain, SERVICE_TRIP_SUMMARY):
        return

    async def handle_trip_summary(call: ServiceCall) -> ServiceResponse:
        start_d: date = call.data["start_date"]
        end_d: date = call.data["end_date"]
        if start_d > end_d:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_date_range",
            )

        tz = dt_util.get_default_time_zone()
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
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="not_configured",
            )

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
                    trips = await client.get_trips(tid, from_iso, to_iso, metrics=True)
                except GeoRideAuthError as err:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="token_rejected",
                        translation_placeholders={"error": str(err)},
                    ) from err
                except GeoRideConnectionError as err:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="cannot_connect_api",
                        translation_placeholders={"error": str(err)},
                    ) from err
                except GeoRideError as err:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN,
                        translation_key="api_error",
                        translation_placeholders={"error": str(err)},
                    ) from err

                if trips:
                    _LOGGER.debug(
                        "GeoRide trips: tracker=%s count=%d keys=%s",
                        tid,
                        len(trips),
                        sorted(trips[0].keys()),
                    )

                summary = _summarize(trips, tz)
                tracker_entry: dict[str, Any] = {
                    "tracker_name": tracker.get("trackerName"),
                    "summary": summary,
                }
                if include_trips:
                    tracker_entry["trips"] = trips
                per_tracker[str(tid)] = tracker_entry
                all_trips.extend(trips)

        if requested is not None and not matched:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="tracker_not_found",
                translation_placeholders={"tracker_id": str(requested)},
            )

        response: dict[str, Any] = {
            "range": {"from": from_iso, "to": to_iso},
            "trackers": per_tracker,
            "aggregate": _summarize(all_trips, tz),
        }
        return response

    hass.services.async_register(
        domain,
        SERVICE_TRIP_SUMMARY,
        handle_trip_summary,
        schema=TRIP_SUMMARY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
