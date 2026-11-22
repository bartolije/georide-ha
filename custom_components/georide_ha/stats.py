"""Trip statistics. Pure compute, no Home Assistant imports.

Lives outside services.py so the summary logic can be unit-tested in
isolation (services.py pulls in Home Assistant which we don't depend on
for these calculations).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, tzinfo
from typing import Any

from .helpers import meters_to_km, number


def trip_month(start_time: Any, tz: tzinfo | None = None) -> str | None:
    """Bucket an ISO 8601 trip start into a YYYY-MM string, in `tz` (UTC if None)."""
    if not isinstance(start_time, str):
        return None
    try:
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (start.astimezone(tz) if tz else start).strftime("%Y-%m")


def summarize(trips: list[dict[str, Any]], tz: tzinfo | None = None) -> dict[str, Any]:
    """Aggregate stats across a list of v2 trip dicts; months are counted in `tz`.

    Defensive against missing or wrongly-typed keys; missing values are
    skipped rather than counted as zero. Distances are in meters.
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
            "max_left_lean_angle": None,
            "max_right_lean_angle": None,
        }

    total_km = 0.0
    km_per_month: defaultdict[str, float] = defaultdict(float)
    speeds: list[float] = []
    max_top_speed: float | None = None
    max_angle: float | None = None
    max_left: float | None = None
    max_right: float | None = None

    for trip in trips:
        km = meters_to_km(trip.get("distance"))
        if km is not None:
            total_km += km
            month = trip_month(trip.get("startTime"), tz)
            if month is not None:
                km_per_month[month] += km

        # The v2 API reports speeds in km/h.
        top_speed = _kmh(trip.get("maxSpeed"))
        if top_speed is not None:
            speeds.append(top_speed)
            max_top_speed = (
                top_speed if max_top_speed is None else max(max_top_speed, top_speed)
            )

        # Angles are degrees from vertical; the trip-level one is signed
        # (negative = left), so compare magnitudes.
        left = _deg(trip.get("maxLeftAngle"))
        right = _deg(trip.get("maxRightAngle"))
        max_left = _max_or(max_left, left)
        max_right = _max_or(max_right, right)
        max_angle = _max_or(max_angle, _deg(trip.get("maxLeanAngle")))
        max_angle = _max_or(_max_or(max_angle, left), right)

    return {
        "trips_count": len(trips),
        "total_km": round(total_km, 2),
        "avg_km_per_trip": round(total_km / len(trips), 2),
        "km_per_month": {k: round(v, 2) for k, v in sorted(km_per_month.items())},
        "avg_top_speed": round(sum(speeds) / len(speeds), 1) if speeds else None,
        "max_top_speed": max_top_speed,
        "max_lean_angle": max_angle,
        "max_left_lean_angle": max_left,
        "max_right_lean_angle": max_right,
    }


def _max_or(current: float | None, value: float | None) -> float | None:
    """Running maximum that ignores missing values."""
    if value is None:
        return current
    return value if current is None else max(current, value)


def _kmh(value: Any) -> float | None:
    v = number(value)
    return None if v is None else round(float(v), 2)


def _deg(value: Any) -> float | None:
    v = number(value)
    return None if v is None else round(abs(float(v)), 2)
