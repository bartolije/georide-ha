"""Unit tests for the pure helpers."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.georide import helpers


class TestMetersToKm:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (34_298_150, 34298.15),  # real ZX-10R odometer (m)
            (1500, 1.5),
            (1001, 1.0),
            (1000, 1000.0),  # threshold is strict >, so 1000 stays
            (500, 500.0),
            (0, 0.0),
            (0.0, 0.0),
        ],
    )
    def test_numeric(self, raw, expected):
        assert helpers.meters_to_km(raw) == expected

    @pytest.mark.parametrize("raw", [None, "1500", True, False, [1500], {}])
    def test_non_numeric_returns_none(self, raw):
        assert helpers.meters_to_km(raw) is None


class TestVoltageToBatteryPct:
    @pytest.mark.parametrize(
        "v,expected",
        [
            (11.0, 0),
            (12.7, 100),
            (11.85, 50),
            (10.5, 0),
            (13.5, 100),
            (13, 100),
        ],
    )
    def test_curve(self, v, expected):
        assert helpers.voltage_to_battery_pct(v) == expected

    @pytest.mark.parametrize("v", [None, "12.5", True, [12.5]])
    def test_non_numeric_returns_none(self, v):
        assert helpers.voltage_to_battery_pct(v) is None

    def test_custom_curve(self):
        assert helpers.voltage_to_battery_pct(2.0, empty_v=1.0, full_v=3.0) == 50

    def test_zero_span_returns_none(self):
        # Edge case: empty_v == full_v would divide by zero; guard returns None.
        assert helpers.voltage_to_battery_pct(12.0, empty_v=12.0, full_v=12.0) is None


class TestParseTimestamp:
    def test_iso_with_z(self):
        ts = helpers.parse_timestamp("2026-04-16T06:47:18.600Z")
        assert ts == datetime(2026, 4, 16, 6, 47, 18, 600_000, tzinfo=timezone.utc)

    def test_iso_with_offset(self):
        ts = helpers.parse_timestamp("2026-04-16T08:47:18.600+02:00")
        assert ts is not None
        assert ts.utcoffset().total_seconds() == 7200

    def test_epoch_seconds(self):
        ts = helpers.parse_timestamp(1_700_000_000)
        assert ts == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)

    def test_epoch_milliseconds(self):
        ts = helpers.parse_timestamp(1_700_000_000_000)
        assert ts == datetime.fromtimestamp(1_700_000_000, tz=timezone.utc)

    @pytest.mark.parametrize(
        "value",
        [None, "not-a-date", "", True, False, [2026], {}],
    )
    def test_unparseable_returns_none(self, value):
        assert helpers.parse_timestamp(value) is None


class TestNumber:
    @pytest.mark.parametrize("v", [0, 1, -1, 1.5, 0.0, 13])
    def test_returns_numeric(self, v):
        assert helpers.number(v) == v

    @pytest.mark.parametrize("v", [None, "1", True, False, [1], {}])
    def test_non_numeric_returns_none(self, v):
        assert helpers.number(v) is None
