"""Unit tests for the trip statistics aggregator (no Home Assistant needed)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_STATS_PATH = (
    Path(__file__).parent.parent / "custom_components" / "georide" / "stats.py"
)
_spec = importlib.util.spec_from_file_location("georide_stats_under_test", _STATS_PATH)
stats = importlib.util.module_from_spec(_spec)
sys.modules["georide_stats_under_test"] = stats
_spec.loader.exec_module(stats)


def _trip(**overrides):
    """Build a trip dict matching the shape returned by GeoRide.

    Sane defaults are present; pass overrides to mutate the test fixture.
    """
    base = {
        "id": 1,
        "trackerId": 999,
        "startTime": "2026-04-16T06:47:18.600Z",
        "endTime": "2026-04-16T06:54:57.800Z",
        "distance": 7118,  # meters
        "averageSpeed": 30.0,
        "maxSpeed": 60.0,
        "maxAngle": 25.0,
    }
    base.update(overrides)
    return base


class TestSummarizeEmpty:
    def test_empty_list_returns_zero_shape(self):
        result = stats.summarize([])
        assert result == {
            "trips_count": 0,
            "total_km": 0.0,
            "avg_km_per_trip": 0.0,
            "km_per_month": {},
            "avg_top_speed": None,
            "max_top_speed": None,
            "max_lean_angle": None,
        }


class TestSummarizeSingleTrip:
    def test_distance_in_meters(self):
        r = stats.summarize([_trip(distance=7118)])
        assert r["trips_count"] == 1
        assert r["total_km"] == 7.12
        assert r["avg_km_per_trip"] == 7.12

    def test_distance_already_in_km(self):
        # < 1000 → assumed already km
        r = stats.summarize([_trip(distance=42.5)])
        assert r["total_km"] == 42.5

    def test_max_and_avg_speed(self):
        r = stats.summarize([_trip(maxSpeed=100.0)])
        assert r["max_top_speed"] == 100.0
        assert r["avg_top_speed"] == 100.0

    def test_max_lean_angle(self):
        r = stats.summarize([_trip(maxAngle=47.3)])
        assert r["max_lean_angle"] == 47.3

    def test_km_per_month(self):
        r = stats.summarize([_trip(startTime="2026-04-16T06:47:18Z", distance=10_000)])
        assert r["km_per_month"] == {"2026-04": 10.0}


class TestSummarizeMultipleTrips:
    def test_aggregates_across_months(self):
        r = stats.summarize([
            _trip(distance=10_000, startTime="2026-03-01T10:00:00Z", maxSpeed=80),
            _trip(distance=20_000, startTime="2026-04-01T10:00:00Z", maxSpeed=120),
            _trip(distance=5_000, startTime="2026-04-15T10:00:00Z", maxSpeed=100),
        ])
        assert r["trips_count"] == 3
        assert r["total_km"] == 35.0
        assert r["avg_km_per_trip"] == pytest.approx(11.67, abs=0.01)
        assert r["km_per_month"] == {"2026-03": 10.0, "2026-04": 25.0}
        assert r["max_top_speed"] == 120
        assert r["avg_top_speed"] == 100.0


class TestSummarizeDefensive:
    def test_missing_keys_dont_crash(self):
        # Trip with only an id — every numeric is missing.
        r = stats.summarize([{"id": 1}])
        assert r["trips_count"] == 1
        assert r["total_km"] == 0.0
        assert r["max_top_speed"] is None
        assert r["max_lean_angle"] is None
        assert r["avg_top_speed"] is None

    def test_alternate_distance_key(self):
        r = stats.summarize([{"id": 1, "tripDistance": 5_000}])
        assert r["total_km"] == 5.0

    def test_string_values_are_skipped(self):
        # Defensive: numeric fields delivered as strings shouldn't crash.
        r = stats.summarize([{"id": 1, "distance": "7118", "maxSpeed": "60"}])
        assert r["total_km"] == 0.0
        assert r["max_top_speed"] is None

    def test_bool_values_are_skipped(self):
        # True is technically int in Python; make sure we don't count it.
        r = stats.summarize([{"id": 1, "distance": True, "maxSpeed": True}])
        assert r["total_km"] == 0.0
        assert r["max_top_speed"] is None


class TestTripMonth:
    def test_iso_string(self):
        assert stats.trip_month("2026-04-16T06:47:18Z") == "2026-04"

    def test_iso_with_offset(self):
        assert stats.trip_month("2026-04-16T08:47:18+02:00") == "2026-04"

    def test_epoch_seconds(self):
        # 2024-01-01 00:00:00 UTC
        assert stats.trip_month(1_704_067_200) == "2024-01"

    def test_epoch_milliseconds(self):
        assert stats.trip_month(1_704_067_200_000) == "2024-01"

    @pytest.mark.parametrize("v", [None, "garbage", True, [2026]])
    def test_invalid(self, v):
        assert stats.trip_month(v) is None


class TestPick:
    def test_first_present(self):
        assert stats.pick({"a": 1, "b": 2}, ("a", "b")) == 1

    def test_skips_none(self):
        assert stats.pick({"a": None, "b": 2}, ("a", "b")) == 2

    def test_all_missing(self):
        assert stats.pick({}, ("a", "b")) is None
