"""Unit tests for the trip statistics aggregator."""
from __future__ import annotations

import pytest

from custom_components.georide import stats


def _trip(**overrides):
    base = {
        "id": 1,
        "trackerId": 999,
        "startTime": "2026-04-16T06:47:18.600Z",
        "endTime": "2026-04-16T06:54:57.800Z",
        "distance": 7118,
        "averageSpeed": 30.0,
        "maxSpeed": 60.0,
        "maxLeanAngle": 25.0,
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
            "max_left_lean_angle": None,
            "max_right_lean_angle": None,
        }


class TestSummarizeSingleTrip:
    def test_distance_in_meters(self):
        r = stats.summarize([_trip(distance=7118)])
        assert r["trips_count"] == 1
        assert r["total_km"] == 7.12
        assert r["avg_km_per_trip"] == 7.12

    def test_distance_already_in_km(self):
        r = stats.summarize([_trip(distance=42.5)])
        assert r["total_km"] == 42.5

    def test_speeds_are_kmh(self):
        # v2 reports km/h: the 2026-09-13 ride shows 167 km/h in the app.
        r = stats.summarize([_trip(maxSpeed=167.2356)])
        assert r["max_top_speed"] == 167.24
        assert r["avg_top_speed"] == 167.2

    def test_signed_trip_lean_compared_by_magnitude(self):
        # Negative = left lean.
        assert stats.summarize([_trip(maxLeanAngle=-47.71)])["max_lean_angle"] == 47.71
        assert stats.summarize([_trip(maxLeanAngle=24.31)])["max_lean_angle"] == 24.31

    def test_left_and_right_lean_from_metrics(self):
        trip = _trip(maxLeftAngle=47.7, maxRightAngle=47.3)
        del trip["maxLeanAngle"]  # list items don't carry it
        r = stats.summarize([trip])
        assert r["max_left_lean_angle"] == 47.7
        assert r["max_right_lean_angle"] == 47.3
        assert r["max_lean_angle"] == 47.7

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

    def test_left_lean_is_not_beaten_by_a_smaller_right_lean(self):
        r = stats.summarize([
            _trip(maxLeanAngle=-50.0, maxLeftAngle=50.0, maxRightAngle=5.0),
            _trip(maxLeanAngle=10.0, maxLeftAngle=5.0, maxRightAngle=10.0),
        ])
        assert r["max_lean_angle"] == 50.0
        assert r["max_left_lean_angle"] == 50.0
        assert r["max_right_lean_angle"] == 10.0


class TestSummarizeDefensive:
    def test_missing_keys_dont_crash(self):
        r = stats.summarize([{"id": 1}])
        assert r["trips_count"] == 1
        assert r["total_km"] == 0.0
        assert r["max_top_speed"] is None
        assert r["max_lean_angle"] is None
        assert r["max_left_lean_angle"] is None
        assert r["max_right_lean_angle"] is None
        assert r["avg_top_speed"] is None

    def test_alternate_distance_key(self):
        r = stats.summarize([{"id": 1, "tripDistance": 5_000}])
        assert r["total_km"] == 5.0

    def test_string_values_are_skipped(self):
        r = stats.summarize([{"id": 1, "distance": "7118", "maxSpeed": "60"}])
        assert r["total_km"] == 0.0
        assert r["max_top_speed"] is None

    def test_bool_values_are_skipped(self):
        r = stats.summarize([{"id": 1, "distance": True, "maxSpeed": True}])
        assert r["total_km"] == 0.0
        assert r["max_top_speed"] is None


class TestTripMonth:
    def test_iso_string(self):
        assert stats.trip_month("2026-04-16T06:47:18Z") == "2026-04"

    def test_iso_with_offset(self):
        assert stats.trip_month("2026-04-16T08:47:18+02:00") == "2026-04"

    def test_epoch_seconds(self):
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
