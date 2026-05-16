"""Pure helpers for value extraction and unit conversion.

No Home Assistant imports — keeps these functions trivially unit-testable
in any Python environment.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def meters_to_km(value: Any) -> float | None:
    """Convert a raw distance to km. Returns None if not numeric.

    GeoRide's API returns the odometer in meters when the value exceeds
    1000; smaller values are assumed to already be km. The threshold
    avoids divide-by-1000 on already-km payloads, but is a heuristic.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    if value > 1000:
        return round(float(value) / 1000.0, 2)
    return round(float(value), 2)


def voltage_to_battery_pct(
    value: Any,
    *,
    empty_v: float = 11.0,
    full_v: float = 12.7,
) -> int | None:
    """Linear-map a lead-acid moto battery voltage to 0–100 %.

    Real discharge curves are not linear; this is an approximation good
    enough for a percentage badge. Anything below `empty_v` clamps to 0,
    anything above `full_v` clamps to 100.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    span = full_v - empty_v
    if span <= 0:
        return None
    pct = (float(value) - empty_v) / span * 100.0
    return max(0, min(100, round(pct)))


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an ISO 8601 string, epoch seconds, or epoch ms.

    Returns a tz-aware datetime in UTC, or None for unsupported values.
    Epoch values larger than 1e12 are treated as milliseconds.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            seconds = float(value) / 1000.0 if value > 1e12 else float(value)
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def number(value: Any) -> int | float | None:
    """Return the value if it is numeric (excluding bool), else None."""
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


# GeoRide's API reports every speed (live tracker `speed`, trip `averageSpeed`,
# trip `maxSpeed`) in knots — not km/h. Verified against the GeoRide web app:
# averageSpeed=37.62 displays as 70 km/h, maxSpeed=100.5 displays as 186 km/h,
# both an exact ×1.852 (knots→km/h) match.
KNOTS_TO_KMH = 1.852


def knots_to_kmh(value: Any) -> float | None:
    """Convert a GeoRide speed payload (knots) to km/h."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return round(float(value) * KNOTS_TO_KMH, 2)


def lean_angle_deg(value: Any) -> float | None:
    """Convert a GeoRide trip angle payload to lean-from-vertical in degrees.

    GeoRide reports angles as offsets from a 90° vertical reference:
    `maxRightAngle = 90 + right_lean`, `maxLeftAngle = 90 - left_lean`, and
    `maxAngle` is whichever side had the larger absolute deviation. The
    physical lean is therefore `|raw - 90|`.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return round(abs(float(value) - 90.0), 2)
