"""Smoke tests for the TypedDict payloads in `models.py`.

TypedDicts are checked statically by mypy — at runtime they are just
class definitions, so this file's job is mostly to import the module
(executes every field declaration) and assert basic shape compatibility
to ensure refactors don't accidentally drop a field.
"""
from __future__ import annotations

import sys

import pytest

# `models.py` imports `typing.NotRequired` which only exists from
# Python 3.11 onwards. The lightweight .venv (py3.9) used for live API
# tests can't import it, so we skip the whole module there.
if sys.version_info < (3, 11):
    pytest.skip("models requires Python 3.11+", allow_module_level=True)

from custom_components.georide import models  # noqa: E402


class TestTypedDictsExist:
    def test_tracker_payload_importable(self):
        assert models.TrackerPayload.__name__ == "TrackerPayload"

    def test_trip_payload_importable(self):
        assert models.TripPayload.__name__ == "TripPayload"

    def test_beacon_payload_importable(self):
        assert models.BeaconPayload.__name__ == "BeaconPayload"

    def test_maintenance_payload_importable(self):
        assert models.MaintenancePayload.__name__ == "MaintenancePayload"


class TestTotalFalse:
    """All four TypedDicts are total=False so every field is optional.

    `total=False` means `__total__` is False on the class — easier than
    listing every field as NotRequired manually. Verifying this here
    pins the contract: callers can always pass partial dicts to the API
    surface and the integration's defensive parsing handles the rest.
    """

    def test_tracker_total_false(self):
        assert models.TrackerPayload.__total__ is False

    def test_trip_total_false(self):
        assert models.TripPayload.__total__ is False

    def test_beacon_total_false(self):
        assert models.BeaconPayload.__total__ is False

    def test_maintenance_total_false(self):
        assert models.MaintenancePayload.__total__ is False


class TestKeyFieldsPresent:
    """Sanity-check that the keys the integration code actually reads are
    still declared. If someone removes one of these, mypy won't catch it
    (the dicts are total=False and indexed by `dict.get(...)`) — but a
    refactor would silently break runtime behaviour."""

    def test_tracker_contains_core_keys(self):
        ann = models.TrackerPayload.__annotations__
        for key in (
            "trackerId",
            "trackerName",
            "latitude",
            "longitude",
            "odometer",
            "speed",
            "isLocked",
            "isStolen",
            "isCrashed",
            "moving",
            "expires",
            "externalBatteryVoltage",
            "fixtime",
            "hasBeacon",
            "isInEco",
        ):
            assert key in ann, key

    def test_trip_contains_core_keys(self):
        ann = models.TripPayload.__annotations__
        for key in (
            "id",
            "trackerId",
            "startTime",
            "endTime",
            "distance",
            "duration",
            "averageSpeed",
            "maxSpeed",
            "maxAngle",
        ):
            assert key in ann, key

    def test_beacon_contains_core_keys(self):
        ann = models.BeaconPayload.__annotations__
        for key in (
            "id",
            "name",
            "macAddress",
            "batteryLevel",
            "lastBatteryLevelUpdate",
            "model",
            "isUpdated",
        ):
            assert key in ann, key

    def test_maintenance_contains_core_keys(self):
        ann = models.MaintenancePayload.__annotations__
        for key in (
            "id",
            "trackerId",
            "name",
            "todo",
            "everyMaintenance",
            "dateUnitType",
        ):
            assert key in ann, key
