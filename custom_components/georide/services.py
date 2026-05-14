"""Service handlers for the GeoRide integration."""
from __future__ import annotations

import logging
from collections import defaultdict
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

DISTANCE_KEYS = ("distance", "tripDistance", "tripKm", "kmDistance")
MAX_SPEED_KEYS = ("maxSpeed", "topSpeed", "speedMax")
MAX_ANGLE_KEYS = ("maxAngle", "leanAngle", "maxLeanAngle", "angleMax")
START_TIME_KEYS = ("startTime", "start_time", "startDate", "startedAt", "start")


def _to_utc_iso(d: date, *, end_of_day: bool = False) -> str:
    """Convert a date to an ISO 8601 UTC datetime string."""
    t = datetime.combine(
        d,
        datetime.max.time().replace(microsecond=0) if end_of_day else datetime.min.time(),
        tzinfo=timezone.utc,
    )
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _pick(trip: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in trip and trip[k] is not None:
            return trip[k]
    return None


def _trip_month(start_time: Any) -> str | None:
    """Best-effort: extract a YYYY-MM bucket from a trip start time."""
    if isinstance(start_time, (int, float)):
        try:
            seconds = start_time / 1000.0 if start_time > 1e12 else float(start_time)
            return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m")
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(start_time, str):
        try:
            return datetime.fromisoformat(start_time.replace("Z", "+00:00")).strftime(
                "%Y-%m"
            )
        except ValueError:
            return None
    return None


def _summarize(trips: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute a summary across a list of trips with defensive key probing."""
    if not trips:
        return {
            "trips_count": 0,
            "total_km": 0.0,
            "avg_km_per_trip": 0.0,
            "km_per_month": {},
            "avg_top_speed": None,
            "max_top_speed": None,
            "max_lean_angle": None,
        }

    total_km = 0.0
    km_per_month: defaultdict[str, float] = defaultdict(float)
    speeds: list[float] = []
    max_top_speed: float | None = None
    max_angle: float | None = None

    for trip in trips:
        raw_distance = _pick(trip, DISTANCE_KEYS)
        if isinstance(raw_distance, (int, float)):
            # GeoRide returns distance in meters; convert to km. Heuristic:
            # values > 1000 are assumed meters, smaller values already km.
            km = float(raw_distance) / 1000.0 if raw_distance > 1000 else float(raw_distance)
            total_km += km
            month = _trip_month(_pick(trip, START_TIME_KEYS))
            if month is not None:
                km_per_month[month] += km

        raw_max = _pick(trip, MAX_SPEED_KEYS)
        if isinstance(raw_max, (int, float)):
            speeds.append(float(raw_max))
            max_top_speed = (
                float(raw_max) if max_top_speed is None else max(max_top_speed, float(raw_max))
            )

        raw_angle = _pick(trip, MAX_ANGLE_KEYS)
        if isinstance(raw_angle, (int, float)):
            max_angle = (
                float(raw_angle) if max_angle is None else max(max_angle, float(raw_angle))
            )

    return {
        "trips_count": len(trips),
        "total_km": round(total_km, 2),
        "avg_km_per_trip": round(total_km / len(trips), 2),
        "km_per_month": {k: round(v, 2) for k, v in sorted(km_per_month.items())},
        "avg_top_speed": round(sum(speeds) / len(speeds), 1) if speeds else None,
        "max_top_speed": max_top_speed,
        "max_lean_angle": max_angle,
    }


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
