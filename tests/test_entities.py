"""Entity-level tests for every platform.

Targets the lines that coordinator/services tests don't cover: entity
constructors (DeviceInfo, unique_id), value_fn dispatch in sensor and
binary_sensor descriptions, the device_tracker GPS properties, and the
lock / siren / switch action paths including their HomeAssistantError
mappings.
"""
from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from datetime import datetime, timezone  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402

from homeassistant.components.binary_sensor import BinarySensorDeviceClass  # noqa: E402
from homeassistant.components.lock import LockEntity  # noqa: E402
from homeassistant.components.sensor import SensorDeviceClass  # noqa: E402
from homeassistant.const import (  # noqa: E402
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfSpeed,
    UnitOfTime,
)
from homeassistant.exceptions import HomeAssistantError  # noqa: E402
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC  # noqa: E402

from custom_components.georide.api import (  # noqa: E402
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
)
from custom_components.georide.binary_sensor import (  # noqa: E402
    BEACON_BINARY_SENSORS,
    BINARY_SENSORS,
    GeoRideBeaconBinarySensor,
    GeoRideBinarySensor,
)
from custom_components.georide.const import DOMAIN  # noqa: E402
from custom_components.georide.device_tracker import GeoRideDeviceTracker  # noqa: E402
from custom_components.georide.lock import GeoRideLock  # noqa: E402
from custom_components.georide.sensor import (  # noqa: E402
    BEACON_SENSORS,
    LAST_TRIP_SENSORS,
    SENSORS,
    GeoRideBeaconSensor,
    GeoRideLastTripSensor,
    GeoRideMaintenanceSensor,
    GeoRideSensor,
)
from custom_components.georide.siren import GeoRideSiren  # noqa: E402
from custom_components.georide.switch import GeoRideEcoModeSwitch  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
TID = 999
TRACKER = {
    "trackerId": TID,
    "trackerName": "Test bike",
    "model": "georide-3s",
    "version": "3",
    "softwareVersion": "3",
    "latitude": 45.7,
    "longitude": 4.8,
    "altitude": 250,
    "speed": 42.0,
    "odometer": 34_298_150,
    "internalBatteryVoltage": 4.1,
    "externalBatteryVoltage": 13.0,
    "fixtime": "2026-05-13T12:00:00Z",
    "expires": "2027-05-13T00:00:00Z",
    "isLocked": True,
    "isStolen": False,
    "isCrashed": False,
    "moving": False,
    "hasBeacon": True,
    "isInEco": False,
    "canLock": True,
    "canUnlock": True,
}

BEACON = {
    "id": 747449,
    "name": "Badge de test",
    "macAddress": "AA:BB:CC:DD:EE:FF",
    "batteryLevel": 87,
    "lastBatteryLevelUpdate": "2026-05-10T08:00:00Z",
    "model": "gen-1",
    "isUpdated": True,
}

MAINT_DAYS = {
    "id": 42,
    "trackerId": TID,
    "name": "Pression du pneu avant",
    "todo": 359,
    "dateUnitType": "days",
}
MAINT_KM = {
    "id": 43,
    "trackerId": TID,
    "name": "Graissage de chaîne",
    "todo": 600_000,
    "dateUnitType": None,
}
MAINT_YEARS = {
    "id": 44,
    "trackerId": TID,
    "name": "Personnalise",
    "todo": 8760,  # hours = 1 year
    "dateUnitType": "years",
}
MAINT_BAD = {
    "id": 45,
    "trackerId": TID,
    "name": "Bad",
    "todo": "not-a-number",
    "dateUnitType": "days",
}


def _coordinator(
    *,
    trackers=None,
    beacons=None,
    maintenance=None,
    last_trips=None,
    client=None,
):
    coord = MagicMock()
    coord.data = {t["trackerId"]: t for t in (trackers or [TRACKER])}
    coord.beacons = beacons if beacons is not None else {}
    coord.maintenance = maintenance if maintenance is not None else {}
    coord.last_trips = last_trips if last_trips is not None else {}
    coord.client = client or AsyncMock()
    coord.async_request_refresh = AsyncMock()
    return coord


# ---------------------------------------------------------------------------
# Base GeoRideEntity / GeoRideBeaconEntity
# ---------------------------------------------------------------------------
class TestEntityBases:
    def test_tracker_entity_device_info(self):
        coord = _coordinator()
        sensor = GeoRideSensor(coord, TID, SENSORS[0])
        info = sensor._attr_device_info
        assert info is not None
        assert (DOMAIN, str(TID)) in info["identifiers"]
        assert info["name"] == "Test bike"
        assert info["manufacturer"] == "GeoRide"
        assert info["model"] == "georide-3s"

    def test_tracker_entity_fallback_name_when_no_trackerName(self):
        tracker_no_name = {"trackerId": TID, "model": "x"}
        coord = _coordinator(trackers=[tracker_no_name])
        sensor = GeoRideSensor(coord, TID, SENSORS[0])
        assert f"GeoRide {TID}" in (sensor._attr_device_info or {}).get("name", "")

    def test_tracker_unavailable_when_id_gone(self):
        coord = _coordinator(trackers=[TRACKER])
        sensor = GeoRideSensor(coord, TID, SENSORS[0])
        coord.data = {}  # tracker disappeared
        assert sensor.available is False

    def test_beacon_entity_device_info_includes_mac_connection(self):
        coord = _coordinator(beacons={TID: [BEACON]})
        sensor = GeoRideBeaconSensor(coord, TID, BEACON["id"], BEACON_SENSORS[0])
        info = sensor._attr_device_info
        assert info is not None
        assert (DOMAIN, f"beacon-{BEACON['id']}") in info["identifiers"]
        assert info["via_device"] == (DOMAIN, str(TID))
        # MAC normalised to lowercase per the integration's contract.
        assert (CONNECTION_NETWORK_MAC, BEACON["macAddress"].lower()) in info[
            "connections"
        ]

    def test_beacon_entity_no_mac_means_no_connections_key(self):
        no_mac = {**BEACON, "macAddress": None}
        coord = _coordinator(beacons={TID: [no_mac]})
        sensor = GeoRideBeaconSensor(coord, TID, no_mac["id"], BEACON_SENSORS[0])
        info = sensor._attr_device_info
        assert info is not None
        assert "connections" not in info

    def test_beacon_entity_fallback_name(self):
        anon = {"id": 1234, "macAddress": "11:22:33:44:55:66"}
        coord = _coordinator(beacons={TID: [anon]})
        sensor = GeoRideBeaconSensor(coord, TID, anon["id"], BEACON_SENSORS[0])
        info = sensor._attr_device_info
        assert info is not None
        assert "GeoRide beacon 1234" in info["name"]

    def test_beacon_unavailable_when_id_gone(self):
        coord = _coordinator(beacons={TID: [BEACON]})
        sensor = GeoRideBeaconSensor(coord, TID, BEACON["id"], BEACON_SENSORS[0])
        coord.beacons = {TID: []}
        assert sensor.available is False


# ---------------------------------------------------------------------------
# Tracker sensors
# ---------------------------------------------------------------------------
def _desc_by_key(descriptions, key):
    for d in descriptions:
        if d.key == key:
            return d
    raise KeyError(key)


class TestTrackerSensors:
    def test_odometer_meters_to_km(self):
        coord = _coordinator()
        s = GeoRideSensor(coord, TID, _desc_by_key(SENSORS, "odometer"))
        assert s.native_value == 34298.15

    def test_speed_knots_to_kmh(self):
        # Fixture has speed=42.0 knots. 42.0 × 1.852 = 77.78 km/h.
        coord = _coordinator()
        s = GeoRideSensor(coord, TID, _desc_by_key(SENSORS, "speed"))
        assert s.native_value == 77.78

    def test_battery_level_from_voltage(self):
        coord = _coordinator()
        s = GeoRideSensor(coord, TID, _desc_by_key(SENSORS, "battery_level"))
        assert s.native_value == 100  # 13 V clamps to full

    def test_last_seen_parses_iso(self):
        coord = _coordinator()
        s = GeoRideSensor(coord, TID, _desc_by_key(SENSORS, "last_seen"))
        ts = s.native_value
        assert isinstance(ts, datetime)
        assert ts == datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc)

    def test_altitude_passthrough(self):
        coord = _coordinator()
        s = GeoRideSensor(coord, TID, _desc_by_key(SENSORS, "altitude"))
        assert s.native_value == 250

    def test_voltages_passthrough(self):
        coord = _coordinator()
        ext = GeoRideSensor(coord, TID, _desc_by_key(SENSORS, "external_battery_voltage"))
        internal = GeoRideSensor(coord, TID, _desc_by_key(SENSORS, "internal_battery_voltage"))
        assert ext.native_value == 13.0
        assert internal.native_value == 4.1

    def test_subscription_expires_parses_iso(self):
        coord = _coordinator()
        s = GeoRideSensor(coord, TID, _desc_by_key(SENSORS, "subscription_expires"))
        assert isinstance(s.native_value, datetime)

    def test_missing_field_returns_none(self):
        coord = _coordinator(trackers=[{"trackerId": TID}])
        s = GeoRideSensor(coord, TID, _desc_by_key(SENSORS, "speed"))
        assert s.native_value is None

    def test_unique_id_includes_description_key(self):
        coord = _coordinator()
        s = GeoRideSensor(coord, TID, _desc_by_key(SENSORS, "odometer"))
        assert s.unique_id == f"{TID}-odometer"


# ---------------------------------------------------------------------------
# Last-trip sensors
# ---------------------------------------------------------------------------
class TestLastTripSensors:
    # Real payload captured from the GeoRide web app on 2026-05-16, with the
    # in-app values shown alongside (asserted below):
    #   distance 124089 m → 124 km
    #   duration 6412410 ms → ~1h47
    #   averageSpeed 37.62 knots → 70 km/h
    #   maxSpeed 100.5 knots → 186 km/h
    #   maxAngle 121.06 → 31° lean, right side
    TRIP = {
        "id": 7,
        "endTime": "2026-05-16T09:56:11.200Z",
        "distance": 124089,
        "duration": 6412410,
        "averageSpeed": 37.62,
        "maxSpeed": 100.5,
        "maxAngle": 121.06,
        "maxLeftAngle": 61.77,
        "maxRightAngle": 121.06,
        "averageAngle": 15.23,
    }

    def test_last_trip_distance_meters_to_km(self):
        coord = _coordinator(last_trips={TID: self.TRIP})
        s = GeoRideLastTripSensor(coord, TID, _desc_by_key(LAST_TRIP_SENSORS, "last_trip_distance"))
        assert s.native_value == 124.09  # app shows 124

    def test_last_trip_duration_ms_to_s(self):
        coord = _coordinator(last_trips={TID: self.TRIP})
        s = GeoRideLastTripSensor(coord, TID, _desc_by_key(LAST_TRIP_SENSORS, "last_trip_duration"))
        assert s.native_value == 6412

    def test_last_trip_duration_formatted_matches_app(self):
        # App displays "1:46h"; we show "1h 46min 52s" — same hours/minutes.
        coord = _coordinator(last_trips={TID: self.TRIP})
        s = GeoRideLastTripSensor(coord, TID, _desc_by_key(LAST_TRIP_SENSORS, "last_trip_duration"))
        assert s.extra_state_attributes == {
            "hours": 1,
            "minutes": 46,
            "seconds": 52,
            "formatted": "1h 46min 52s",
        }

    def test_last_trip_duration_formatted_short_trip(self):
        trip = {**self.TRIP, "duration": 125_000}  # 2min 05s
        coord = _coordinator(last_trips={TID: trip})
        s = GeoRideLastTripSensor(coord, TID, _desc_by_key(LAST_TRIP_SENSORS, "last_trip_duration"))
        assert s.extra_state_attributes == {
            "hours": 0,
            "minutes": 2,
            "seconds": 5,
            "formatted": "2min 05s",
        }

    def test_last_trip_avg_speed_knots_to_kmh_matches_app(self):
        # App shows 70 km/h. API field is 37.62 knots. 37.62 × 1.852 ≈ 69.67.
        coord = _coordinator(last_trips={TID: self.TRIP})
        avg = GeoRideLastTripSensor(coord, TID, _desc_by_key(LAST_TRIP_SENSORS, "last_trip_avg_speed"))
        assert avg.native_value == 69.67

    def test_last_trip_max_speed_knots_to_kmh_matches_app(self):
        # App shows 186 km/h. API field is 100.5 knots. 100.5 × 1.852 = 186.13.
        coord = _coordinator(last_trips={TID: self.TRIP})
        top = GeoRideLastTripSensor(coord, TID, _desc_by_key(LAST_TRIP_SENSORS, "last_trip_max_speed"))
        assert top.native_value == 186.13

    def test_last_trip_end_timestamp(self):
        coord = _coordinator(last_trips={TID: self.TRIP})
        s = GeoRideLastTripSensor(coord, TID, _desc_by_key(LAST_TRIP_SENSORS, "last_trip_end"))
        assert s.native_value == datetime(2026, 5, 16, 9, 56, 11, 200000, tzinfo=timezone.utc)

    def test_last_trip_lean_angle_matches_app(self):
        # App shows "31° à droite". API maxAngle 121.06 → |121.06 - 90| = 31.06°.
        coord = _coordinator(last_trips={TID: self.TRIP})
        desc = _desc_by_key(LAST_TRIP_SENSORS, "last_trip_max_lean_angle")
        s = GeoRideLastTripSensor(coord, TID, desc)
        assert s.native_value == 31.06
        # Enabled by default — users must see it without registry tweaking.
        assert desc.entity_registry_enabled_default is not False

    def test_last_trip_lean_angle_attrs(self):
        coord = _coordinator(last_trips={TID: self.TRIP})
        s = GeoRideLastTripSensor(coord, TID, _desc_by_key(LAST_TRIP_SENSORS, "last_trip_max_lean_angle"))
        assert s.extra_state_attributes == {
            "side": "right",
            "max_left": 28.23,
            "max_right": 31.06,
        }

    def test_last_trip_lean_angle_left_side(self):
        # Symmetric case: bigger left lean than right. maxAngle = maxLeftAngle.
        trip = {
            **self.TRIP,
            "maxAngle": 55.0,
            "maxLeftAngle": 55.0,
            "maxRightAngle": 110.0,
        }
        coord = _coordinator(last_trips={TID: trip})
        s = GeoRideLastTripSensor(coord, TID, _desc_by_key(LAST_TRIP_SENSORS, "last_trip_max_lean_angle"))
        assert s.native_value == 35.0
        assert (s.extra_state_attributes or {}).get("side") == "left"

    def test_last_trip_none_returns_none(self):
        coord = _coordinator(last_trips={TID: None})
        s = GeoRideLastTripSensor(coord, TID, _desc_by_key(LAST_TRIP_SENSORS, "last_trip_distance"))
        assert s.native_value is None


# ---------------------------------------------------------------------------
# Maintenance sensors
# ---------------------------------------------------------------------------
class TestMaintenanceSensors:
    def test_days_item_value_and_units(self):
        coord = _coordinator(maintenance={TID: [MAINT_DAYS]})
        s = GeoRideMaintenanceSensor(coord, TID, MAINT_DAYS["id"])
        assert s.native_value == 359
        assert s.native_unit_of_measurement == UnitOfTime.DAYS
        assert s.device_class == SensorDeviceClass.DURATION
        assert s.entity_category == EntityCategory.DIAGNOSTIC

    def test_distance_item_meters_to_km(self):
        coord = _coordinator(maintenance={TID: [MAINT_KM]})
        s = GeoRideMaintenanceSensor(coord, TID, MAINT_KM["id"])
        assert s.native_value == 600.0
        assert s.native_unit_of_measurement == UnitOfLength.KILOMETERS
        assert s.device_class == SensorDeviceClass.DISTANCE

    def test_years_item_hours_to_days(self):
        coord = _coordinator(maintenance={TID: [MAINT_YEARS]})
        s = GeoRideMaintenanceSensor(coord, TID, MAINT_YEARS["id"])
        # 8760 hours / 24 = 365 days
        assert s.native_value == 365.0
        assert s.native_unit_of_measurement == UnitOfTime.DAYS
        assert s.device_class == SensorDeviceClass.DURATION

    def test_non_numeric_todo_returns_none(self):
        coord = _coordinator(maintenance={TID: [MAINT_BAD]})
        s = GeoRideMaintenanceSensor(coord, TID, MAINT_BAD["id"])
        assert s.native_value is None

    def test_unknown_date_unit_returns_raw(self):
        odd = {**MAINT_DAYS, "dateUnitType": "weeks", "todo": 12}
        coord = _coordinator(maintenance={TID: [odd]})
        s = GeoRideMaintenanceSensor(coord, TID, odd["id"])
        assert s.native_value == 12

    def test_name_falls_back_when_missing(self):
        unnamed = {"id": 99, "todo": 100, "dateUnitType": "days"}
        coord = _coordinator(maintenance={TID: [unnamed]})
        s = GeoRideMaintenanceSensor(coord, TID, 99)
        assert s.name == "Maintenance 99"

    def test_unavailable_when_item_disappears(self):
        coord = _coordinator(maintenance={TID: [MAINT_DAYS]})
        s = GeoRideMaintenanceSensor(coord, TID, MAINT_DAYS["id"])
        coord.maintenance = {TID: []}
        assert s.available is False


# ---------------------------------------------------------------------------
# Beacon sensors
# ---------------------------------------------------------------------------
class TestBeaconSensors:
    def test_battery(self):
        coord = _coordinator(beacons={TID: [BEACON]})
        s = GeoRideBeaconSensor(coord, TID, BEACON["id"], _desc_by_key(BEACON_SENSORS, "battery"))
        assert s.native_value == 87

    def test_last_seen(self):
        coord = _coordinator(beacons={TID: [BEACON]})
        s = GeoRideBeaconSensor(coord, TID, BEACON["id"], _desc_by_key(BEACON_SENSORS, "last_seen"))
        assert s.native_value == datetime(2026, 5, 10, 8, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Tracker binary sensors
# ---------------------------------------------------------------------------
class TestTrackerBinarySensors:
    def test_moving_off(self):
        coord = _coordinator()
        s = GeoRideBinarySensor(coord, TID, _desc_by_key(BINARY_SENSORS, "moving"))
        assert s.is_on is False

    def test_moving_on(self):
        moving = {**TRACKER, "moving": True}
        coord = _coordinator(trackers=[moving])
        s = GeoRideBinarySensor(coord, TID, _desc_by_key(BINARY_SENSORS, "moving"))
        assert s.is_on is True

    def test_stolen_off(self):
        coord = _coordinator()
        s = GeoRideBinarySensor(coord, TID, _desc_by_key(BINARY_SENSORS, "stolen"))
        assert s.is_on is False

    def test_crashed_off(self):
        coord = _coordinator()
        s = GeoRideBinarySensor(coord, TID, _desc_by_key(BINARY_SENSORS, "crashed"))
        assert s.is_on is False

    def test_has_beacon_diagnostic(self):
        coord = _coordinator()
        desc = _desc_by_key(BINARY_SENSORS, "has_beacon")
        s = GeoRideBinarySensor(coord, TID, desc)
        assert s.is_on is True
        assert desc.entity_category == EntityCategory.DIAGNOSTIC
        assert desc.entity_registry_enabled_default is False

    def test_unique_id(self):
        coord = _coordinator()
        s = GeoRideBinarySensor(coord, TID, _desc_by_key(BINARY_SENSORS, "moving"))
        assert s.unique_id == f"{TID}-moving"

    def test_non_bool_value_returns_none(self):
        wrong = {"trackerId": TID, "moving": "yes"}  # string, not bool
        coord = _coordinator(trackers=[wrong])
        s = GeoRideBinarySensor(coord, TID, _desc_by_key(BINARY_SENSORS, "moving"))
        assert s.is_on is None


class TestBeaconBinarySensors:
    def test_firmware_update_off_when_uptodate(self):
        coord = _coordinator(beacons={TID: [BEACON]})  # isUpdated=True
        s = GeoRideBeaconBinarySensor(
            coord,
            TID,
            BEACON["id"],
            _desc_by_key(BEACON_BINARY_SENSORS, "firmware_update"),
        )
        assert s.is_on is False  # inverted: True isUpdated -> False = no update needed

    def test_firmware_update_on_when_outdated(self):
        outdated = {**BEACON, "isUpdated": False}
        coord = _coordinator(beacons={TID: [outdated]})
        s = GeoRideBeaconBinarySensor(
            coord,
            TID,
            outdated["id"],
            _desc_by_key(BEACON_BINARY_SENSORS, "firmware_update"),
        )
        assert s.is_on is True


# ---------------------------------------------------------------------------
# device_tracker
# ---------------------------------------------------------------------------
class TestDeviceTracker:
    def test_gps_source_and_position(self):
        coord = _coordinator()
        dt = GeoRideDeviceTracker(coord, TID)
        assert dt.source_type.name == "GPS" or str(dt.source_type) == "gps"
        assert dt.latitude == 45.7
        assert dt.longitude == 4.8
        assert dt.location_accuracy == 10
        assert dt.unique_id == str(TID)

    def test_missing_coordinates_returns_none(self):
        tracker = {"trackerId": TID, "trackerName": "X"}
        coord = _coordinator(trackers=[tracker])
        dt = GeoRideDeviceTracker(coord, TID)
        assert dt.latitude is None
        assert dt.longitude is None


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------
class TestLock:
    async def test_is_locked_true(self):
        coord = _coordinator()
        lock = GeoRideLock(coord, TID)
        assert lock.is_locked is True
        assert lock.unique_id == f"{TID}-lock"

    async def test_is_locked_none_when_no_data(self):
        tracker = {"trackerId": TID, "trackerName": "X"}
        coord = _coordinator(trackers=[tracker])
        lock = GeoRideLock(coord, TID)
        assert lock.is_locked is None

    async def test_async_lock_calls_client(self):
        coord = _coordinator()
        lock = GeoRideLock(coord, TID)
        await lock.async_lock()
        coord.client.lock_tracker.assert_awaited_once_with(TID)
        coord.async_request_refresh.assert_awaited_once()

    async def test_async_unlock_calls_client(self):
        coord = _coordinator()
        lock = GeoRideLock(coord, TID)
        await lock.async_unlock()
        coord.client.unlock_tracker.assert_awaited_once_with(TID)

    async def test_auth_error_raises_home_assistant_error(self):
        coord = _coordinator()
        coord.client.lock_tracker = AsyncMock(side_effect=GeoRideAuthError("bad"))
        lock = GeoRideLock(coord, TID)
        with pytest.raises(HomeAssistantError):
            await lock.async_lock()

    async def test_connection_error_raises_home_assistant_error(self):
        coord = _coordinator()
        coord.client.lock_tracker = AsyncMock(side_effect=GeoRideConnectionError("net"))
        lock = GeoRideLock(coord, TID)
        with pytest.raises(HomeAssistantError):
            await lock.async_lock()

    async def test_generic_api_error_raises(self):
        coord = _coordinator()
        coord.client.unlock_tracker = AsyncMock(side_effect=GeoRideError("weird"))
        lock = GeoRideLock(coord, TID)
        with pytest.raises(HomeAssistantError):
            await lock.async_unlock()


# ---------------------------------------------------------------------------
# Siren
# ---------------------------------------------------------------------------
class TestSiren:
    async def test_is_on_returns_none(self):
        coord = _coordinator()
        siren = GeoRideSiren(coord, TID)
        # GeoRide doesn't report siren state; we treat it as unknown.
        assert siren.is_on is None
        assert siren.unique_id == f"{TID}-siren"

    async def test_turn_on_calls_client(self):
        coord = _coordinator()
        siren = GeoRideSiren(coord, TID)
        await siren.async_turn_on()
        coord.client.siren_on.assert_awaited_once_with(TID)

    async def test_turn_off_calls_client(self):
        coord = _coordinator()
        siren = GeoRideSiren(coord, TID)
        await siren.async_turn_off()
        coord.client.siren_off.assert_awaited_once_with(TID)

    async def test_auth_error_maps_to_home_assistant_error(self):
        coord = _coordinator()
        coord.client.siren_on = AsyncMock(side_effect=GeoRideAuthError("bad"))
        siren = GeoRideSiren(coord, TID)
        with pytest.raises(HomeAssistantError):
            await siren.async_turn_on()

    async def test_connection_error_maps(self):
        coord = _coordinator()
        coord.client.siren_off = AsyncMock(side_effect=GeoRideConnectionError("net"))
        siren = GeoRideSiren(coord, TID)
        with pytest.raises(HomeAssistantError):
            await siren.async_turn_off()


# ---------------------------------------------------------------------------
# Switch (eco mode)
# ---------------------------------------------------------------------------
class TestEcoModeSwitch:
    async def test_is_on_follows_isInEco(self):
        coord = _coordinator()
        sw = GeoRideEcoModeSwitch(coord, TID)
        assert sw.is_on is False
        assert sw.unique_id == f"{TID}-eco_mode"

    async def test_is_on_true(self):
        eco = {**TRACKER, "isInEco": True}
        coord = _coordinator(trackers=[eco])
        sw = GeoRideEcoModeSwitch(coord, TID)
        assert sw.is_on is True

    async def test_is_on_none_when_missing(self):
        tracker = {"trackerId": TID, "trackerName": "X"}
        coord = _coordinator(trackers=[tracker])
        sw = GeoRideEcoModeSwitch(coord, TID)
        assert sw.is_on is None

    async def test_turn_on_calls_eco_mode_on(self):
        coord = _coordinator()
        sw = GeoRideEcoModeSwitch(coord, TID)
        await sw.async_turn_on()
        coord.client.eco_mode_on.assert_awaited_once_with(TID)
        coord.async_request_refresh.assert_awaited_once()

    async def test_turn_off_calls_eco_mode_off(self):
        coord = _coordinator()
        sw = GeoRideEcoModeSwitch(coord, TID)
        await sw.async_turn_off()
        coord.client.eco_mode_off.assert_awaited_once_with(TID)

    async def test_error_raises_home_assistant_error(self):
        coord = _coordinator()
        coord.client.eco_mode_on = AsyncMock(side_effect=GeoRideError("weird"))
        sw = GeoRideEcoModeSwitch(coord, TID)
        with pytest.raises(HomeAssistantError):
            await sw.async_turn_on()


# ---------------------------------------------------------------------------
# async_setup_entry for every platform — exercises the `_async_add_new`
# closures and the coordinator listener registration code.
# ---------------------------------------------------------------------------
from custom_components.georide import (  # noqa: E402
    binary_sensor as bs_module,
    device_tracker as dt_module,
    lock as lock_module,
    sensor as sensor_module,
    siren as siren_module,
    switch as switch_module,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402


async def _entry_with_coord(hass, **coord_overrides):
    coord = _coordinator(**coord_overrides)
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.runtime_data = coord
    return entry, coord


class TestSetupEntry:
    async def test_sensor_setup_creates_entities(self, hass):
        entry, coord = await _entry_with_coord(
            hass,
            beacons={TID: [BEACON]},
            maintenance={TID: [MAINT_DAYS, MAINT_KM]},
            last_trips={TID: {"id": 7}},
        )
        added: list = []
        await sensor_module.async_setup_entry(hass, entry, lambda items: added.extend(items))
        # 8 tracker sensors + 6 last_trip + 2 maintenance + 2 beacon = 18 expected.
        assert len(added) == len(SENSORS) + len(LAST_TRIP_SENSORS) + 2 + len(BEACON_SENSORS)

    async def test_sensor_setup_skips_beacon_without_int_id(self, hass):
        entry, coord = await _entry_with_coord(
            hass, beacons={TID: [{"id": "not-int"}]}
        )
        added: list = []
        await sensor_module.async_setup_entry(hass, entry, lambda items: added.extend(items))
        # Beacon skipped, only tracker sensors.
        assert all(not isinstance(s, GeoRideBeaconSensor) for s in added)

    async def test_sensor_listener_is_idempotent(self, hass):
        entry, coord = await _entry_with_coord(hass)
        added: list = []
        await sensor_module.async_setup_entry(hass, entry, lambda items: added.extend(items))
        first_count = len(added)
        # Simulate coordinator notifying again — no new entities should appear.
        coord.async_add_listener.call_args[0][0]()  # invoke the registered callback
        assert len(added) == first_count

    async def test_binary_sensor_setup_creates_entities(self, hass):
        entry, _ = await _entry_with_coord(
            hass, beacons={TID: [BEACON]}
        )
        added: list = []
        await bs_module.async_setup_entry(hass, entry, lambda items: added.extend(items))
        # 4 tracker binary sensors + 1 beacon binary sensor = 5
        assert len(added) == len(BINARY_SENSORS) + len(BEACON_BINARY_SENSORS)

    async def test_binary_sensor_skips_beacon_without_int_id(self, hass):
        entry, _ = await _entry_with_coord(hass, beacons={TID: [{"id": "x"}]})
        added: list = []
        await bs_module.async_setup_entry(hass, entry, lambda items: added.extend(items))
        assert all(not isinstance(b, GeoRideBeaconBinarySensor) for b in added)

    async def test_device_tracker_setup_creates_one_per_moto(self, hass):
        entry, _ = await _entry_with_coord(hass)
        added: list = []
        await dt_module.async_setup_entry(hass, entry, lambda items: added.extend(items))
        assert len(added) == 1
        assert isinstance(added[0], GeoRideDeviceTracker)

    async def test_lock_setup_skips_when_can_lock_and_unlock_false(self, hass):
        no_ctrl = {**TRACKER, "canLock": False, "canUnlock": False}
        entry, _ = await _entry_with_coord(hass, trackers=[no_ctrl])
        added: list = []
        await lock_module.async_setup_entry(hass, entry, lambda items: added.extend(items))
        assert added == []

    async def test_lock_setup_creates_when_canLock(self, hass):
        entry, _ = await _entry_with_coord(hass)
        added: list = []
        await lock_module.async_setup_entry(hass, entry, lambda items: added.extend(items))
        assert len(added) == 1

    async def test_siren_setup_creates_one(self, hass):
        entry, _ = await _entry_with_coord(hass)
        added: list = []
        await siren_module.async_setup_entry(hass, entry, lambda items: added.extend(items))
        assert len(added) == 1

    async def test_switch_setup_creates_eco_mode(self, hass):
        entry, _ = await _entry_with_coord(hass)
        added: list = []
        await switch_module.async_setup_entry(hass, entry, lambda items: added.extend(items))
        assert len(added) == 1
        assert isinstance(added[0], GeoRideEcoModeSwitch)
