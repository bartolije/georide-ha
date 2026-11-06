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
