"""Trip statistics. Pure compute, no Home Assistant imports.

Lives outside services.py so the summary logic can be unit-tested in
isolation (services.py pulls in Home Assistant which we don't depend on
for these calculations).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .helpers import number

DISTANCE_KEYS = ("distance", "tripDistance", "tripKm", "kmDistance")
MAX_SPEED_KEYS = ("maxSpeed", "topSpeed", "speedMax")
MAX_ANGLE_KEYS = ("maxLeanAngle", "maxAngle", "leanAngle", "angleMax")
MAX_LEFT_ANGLE_KEYS = ("maxLeftAngle",)
MAX_RIGHT_ANGLE_KEYS = ("maxRightAngle",)
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

        # The v2 API reports speeds in km/h.
        top_speed = _kmh(pick(trip, MAX_SPEED_KEYS))
        if top_speed is not None:
            speeds.append(top_speed)
            max_top_speed = (
                top_speed if max_top_speed is None else max(max_top_speed, top_speed)
            )

        # Angles are degrees from vertical; the trip-level one is signed
        # (negative = left), so compare magnitudes.
        left = _deg(pick(trip, MAX_LEFT_ANGLE_KEYS))
        right = _deg(pick(trip, MAX_RIGHT_ANGLE_KEYS))
        max_left = _max_or(max_left, left)
        max_right = _max_or(max_right, right)
        max_angle = _max_or(max_angle, _deg(pick(trip, MAX_ANGLE_KEYS)))
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
