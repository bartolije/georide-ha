"""Trip statistics. Pure compute, no Home Assistant imports.

Lives outside services.py so the summary logic can be unit-tested in
isolation (services.py pulls in Home Assistant which we don't depend on
for these calculations).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

DISTANCE_KEYS = ("distance", "tripDistance", "tripKm", "kmDistance")
MAX_SPEED_KEYS = ("maxSpeed", "topSpeed", "speedMax")
MAX_ANGLE_KEYS = ("maxAngle", "leanAngle", "maxLeanAngle", "angleMax")
START_TIME_KEYS = ("startTime", "start_time", "startDate", "startedAt", "start")


def pick(trip: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first non-None value among `keys`, else None."""
    for k in keys:
        if k in trip and trip[k] is not None:
            return trip[k]
    return None


def trip_month(start_time: Any) -> str | None:
    """Bucket a trip start time into a YYYY-MM string in UTC."""
    if isinstance(start_time, bool):
        return None
    if isinstance(start_time, (int, float)):
        try:
            seconds = (
                float(start_time) / 1000.0 if start_time > 1e12 else float(start_time)
            )
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


def summarize(trips: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate stats across a list of trip dicts.

    Defensive against missing or wrongly-typed keys; missing values are
    skipped rather than counted as zero. Distances larger than 1000 are
    assumed to be in meters and converted to km.
    """
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
        raw_distance = pick(trip, DISTANCE_KEYS)
        if isinstance(raw_distance, (int, float)) and not isinstance(
            raw_distance, bool
        ):
            km = (
                float(raw_distance) / 1000.0
                if raw_distance > 1000
                else float(raw_distance)
            )
            total_km += km
            month = trip_month(pick(trip, START_TIME_KEYS))
            if month is not None:
                km_per_month[month] += km

        raw_max = pick(trip, MAX_SPEED_KEYS)
        if isinstance(raw_max, (int, float)) and not isinstance(raw_max, bool):
            speeds.append(float(raw_max))
            max_top_speed = (
                float(raw_max)
                if max_top_speed is None
                else max(max_top_speed, float(raw_max))
            )

        raw_angle = pick(trip, MAX_ANGLE_KEYS)
        if isinstance(raw_angle, (int, float)) and not isinstance(raw_angle, bool):
            max_angle = (
                float(raw_angle)
                if max_angle is None
                else max(max_angle, float(raw_angle))
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
