"""Tests for the GeoRide coordinator (update cycle, events, socket dispatch)."""
from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from datetime import datetime, timedelta, timezone  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from homeassistant.exceptions import ConfigEntryAuthFailed  # noqa: E402
from homeassistant.helpers import issue_registry as ir  # noqa: E402
from homeassistant.helpers.update_coordinator import UpdateFailed  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

from custom_components.georide.api import (  # noqa: E402
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
)
from custom_components.georide.const import (  # noqa: E402
    DOMAIN,
    EVENT_ALARM,
    EVENT_LOCK,
    EVENT_MOVING,
)
from custom_components.georide.coordinator import GeoRideCoordinator  # noqa: E402


def _make_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="bike@example.com",
        title="bike@example.com",
        data={"email": "bike@example.com", "token": "t"},
    )
    entry.add_to_hass(hass)
    return entry


def _client(
    *,
    trackers=None,
    beacons=None,
    trips=None,
    maintenance=None,
    trackers_raises=None,
):
    client = AsyncMock()
    if trackers_raises is not None:
        client.get_trackers = AsyncMock(side_effect=trackers_raises)
    else:
        client.get_trackers = AsyncMock(return_value=trackers or [])
    client.get_tracker_beacons = AsyncMock(return_value=beacons or [])
    client.get_trips = AsyncMock(return_value=trips or [])
    client.get_maintenance = AsyncMock(return_value=maintenance or [])
    return client


# ---------------------------------------------------------------------------
# Refresh cycle
# ---------------------------------------------------------------------------
class TestUpdateData:
    async def test_indexes_trackers_by_id(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1, "trackerName": "A"}])
        coord = GeoRideCoordinator(hass, entry, client)

        data = await coord._async_update_data()
        assert 1 in data
        assert data[1]["trackerName"] == "A"

    async def test_skips_tracker_without_id(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"foo": "bar"}, {"trackerId": 2}])
        coord = GeoRideCoordinator(hass, entry, client)

        data = await coord._async_update_data()
        assert list(data.keys()) == [2]

    async def test_auth_error_raises_config_entry_auth_failed(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers_raises=GeoRideAuthError("bad token"))
        coord = GeoRideCoordinator(hass, entry, client)

        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()

    async def test_connection_error_raises_update_failed(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers_raises=GeoRideConnectionError("dns"))
        coord = GeoRideCoordinator(hass, entry, client)

        with pytest.raises(UpdateFailed):
            await coord._async_update_data()


# ---------------------------------------------------------------------------
# Beacons + trips + maintenance refresh
# ---------------------------------------------------------------------------
class TestSecondaryRefresh:
    async def test_beacons_only_fetched_when_hasBeacon(self, hass):
        entry = _make_entry(hass)
        client = _client(
            trackers=[
                {"trackerId": 1, "hasBeacon": False},
                {"trackerId": 2, "hasBeacon": True},
            ],
            beacons=[{"id": 99, "name": "Badge"}],
        )
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()

        # Only tracker 2 should have triggered a fetch.
        assert client.get_tracker_beacons.call_count == 1
        called_with = client.get_tracker_beacons.call_args.args[0]
        assert called_with == 2
        assert coord.beacons[2] == [{"id": 99, "name": "Badge"}]
        assert coord.beacons[1] == []

    async def test_beacon_fetch_failure_keeps_previous_snapshot(self, hass):
        entry = _make_entry(hass)
        client = _client(
            trackers=[{"trackerId": 1, "hasBeacon": True}],
            beacons=[{"id": 99, "name": "Old"}],
        )
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()
        assert coord.beacons[1][0]["name"] == "Old"

        # Next refresh fails on beacons but trackers succeed.
        client.get_tracker_beacons.side_effect = GeoRideConnectionError("oops")
        await coord._async_update_data()
        assert coord.beacons[1][0]["name"] == "Old"  # unchanged

    async def test_last_trips_refresh_throttled(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}], trips=[{"id": 7, "endTime": "2026-04-16T07:00:00Z"}])
        coord = GeoRideCoordinator(hass, entry, client)

        await coord._async_update_data()
        await coord._async_update_data()
        # First refresh fetches; second within 5min skips.
        assert client.get_trips.call_count == 1
        assert coord.last_trips[1]["id"] == 7

    async def test_last_trips_picks_most_recent_by_endtime(self, hass):
        entry = _make_entry(hass)
        client = _client(
            trackers=[{"trackerId": 1}],
            trips=[
                {"id": 1, "endTime": "2026-04-15T10:00:00Z"},
                {"id": 9, "endTime": "2026-04-16T10:00:00Z"},
                {"id": 5, "endTime": "2026-04-15T20:00:00Z"},
            ],
        )
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()
        assert coord.last_trips[1]["id"] == 9

    async def test_maintenance_refresh_throttled(self, hass):
        entry = _make_entry(hass)
        client = _client(
            trackers=[{"trackerId": 1}],
            maintenance=[{"id": 100, "name": "Oil", "todo": 1000}],
        )
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()
        await coord._async_update_data()
        # 15min throttle: first hits, second skips.
        assert client.get_maintenance.call_count == 1
        assert coord.maintenance[1][0]["name"] == "Oil"


# ---------------------------------------------------------------------------
# Subscription expiry repair issues
# ---------------------------------------------------------------------------
class TestSubscriptionExpiry:
    async def test_raises_issue_when_expiring_soon(self, hass):
        entry = _make_entry(hass)
        soon = (datetime.now(tz=timezone.utc) + timedelta(days=3)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        client = _client(
            trackers=[{"trackerId": 1, "trackerName": "Bike", "expires": soon}]
        )
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()

        registry = ir.async_get(hass)
        issue = registry.async_get_issue(DOMAIN, "subscription_expiring_1")
        assert issue is not None
        assert issue.translation_placeholders["tracker_name"] == "Bike"

    async def test_clears_issue_when_subscription_far(self, hass):
        entry = _make_entry(hass)
        far = (datetime.now(tz=timezone.utc) + timedelta(days=60)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        client = _client(trackers=[{"trackerId": 1, "expires": far}])
        coord = GeoRideCoordinator(hass, entry, client)
        # Pre-populate an issue to verify it gets deleted.
        ir.async_create_issue(
            hass,
            DOMAIN,
            "subscription_expiring_1",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="subscription_expiring",
        )
        await coord._async_update_data()

        registry = ir.async_get(hass)
        assert registry.async_get_issue(DOMAIN, "subscription_expiring_1") is None

    async def test_no_issue_when_expires_field_missing(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()

        registry = ir.async_get(hass)
        assert registry.async_get_issue(DOMAIN, "subscription_expiring_1") is None

    async def test_handles_invalid_expires_string(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1, "expires": "garbage"}])
        coord = GeoRideCoordinator(hass, entry, client)
        # Must not crash.
        await coord._async_update_data()


# ---------------------------------------------------------------------------
# State-transition events
# ---------------------------------------------------------------------------
class TestStateChangeEvents:
    async def _setup_initial(self, hass, initial_tracker):
        entry = _make_entry(hass)
        client = _client(trackers=[initial_tracker])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()
        await coord._async_update_data()  # data is set after first; subsequent diff uses it
        return entry, client, coord

    async def test_lock_transition_fires_event(self, hass):
        events = []
        hass.bus.async_listen(EVENT_LOCK, lambda e: events.append(e))
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1, "isLocked": True}])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord.async_refresh()  # primes self.data

        # Now flip the lock.
        client.get_trackers = AsyncMock(return_value=[{"trackerId": 1, "isLocked": False}])
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert any(ev.data.get("is_locked") is False for ev in events)

    async def test_moving_transition_fires_event(self, hass):
        events = []
        hass.bus.async_listen(EVENT_MOVING, lambda e: events.append(e))
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1, "moving": False}])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord.async_refresh()

        client.get_trackers = AsyncMock(return_value=[{"trackerId": 1, "moving": True}])
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert any(ev.data.get("moving") is True for ev in events)

    async def test_alarm_transition_fires_event(self, hass):
        events = []
        hass.bus.async_listen(EVENT_ALARM, lambda e: events.append(e))
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1, "isStolen": False}])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord.async_refresh()

        client.get_trackers = AsyncMock(return_value=[{"trackerId": 1, "isStolen": True}])
        await coord.async_refresh()
        await hass.async_block_till_done()
        assert any(ev.data.get("type") == "stolen" for ev in events)


# ---------------------------------------------------------------------------
# Socket event routing
# ---------------------------------------------------------------------------
class TestSocketRouting:
    async def _coord(self, hass, trackers=None):
        entry = _make_entry(hass)
        client = _client(trackers=trackers or [{"trackerId": 1}])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord.async_refresh()
        return coord

    async def test_message_event_is_ignored(self, hass):
        coord = await self._coord(hass)
        await coord._handle_socket_event("message", "Welcome")
        # No exception, no state change.

    async def test_position_event_merges_into_tracker(self, hass):
        coord = await self._coord(hass)
        await coord._handle_socket_event(
            "position",
            {"trackerId": 1, "latitude": 45.5, "longitude": 4.5, "speed": 30},
        )
        assert coord.data[1]["latitude"] == 45.5
        assert coord.data[1]["speed"] == 30

    async def test_position_event_with_unknown_tracker_does_nothing(self, hass):
        coord = await self._coord(hass)
        before = dict(coord.data)
        await coord._handle_socket_event(
            "position",
            {"trackerId": 999, "latitude": 1.0},
        )
        assert coord.data == before

    async def test_lock_event_merges_islocked(self, hass):
        coord = await self._coord(hass)
        await coord._handle_socket_event(
            "lockedPosition",
            {"trackerId": 1, "isLocked": False},
        )
        assert coord.data[1]["isLocked"] is False

    async def test_alarm_event_fires_ha_event(self, hass):
        events = []
        hass.bus.async_listen(EVENT_ALARM, lambda e: events.append(e))
        coord = await self._coord(hass)
        await coord._handle_socket_event(
            "alarm",
            {"trackerId": 1, "type": "alarm_vibration"},
        )
        await hass.async_block_till_done()
        assert events and events[0].data["type"] == "vibration"
        assert events[0].data["source"] == "realtime"

    async def test_device_event_triggers_refresh(self, hass):
        coord = await self._coord(hass)
        with patch.object(coord, "async_request_refresh", new=AsyncMock()) as m:
            await coord._handle_socket_event("device", {})
            assert m.called

    async def test_refresh_tracker_instruction_triggers_refresh(self, hass):
        coord = await self._coord(hass)
        with patch.object(coord, "async_request_refresh", new=AsyncMock()) as m:
            await coord._handle_socket_event("refreshTrackersInstruction", {})
            assert m.called


# ---------------------------------------------------------------------------
# Socket start/stop lifecycle
# ---------------------------------------------------------------------------
class TestSocketLifecycle:
    async def test_start_socket_swallows_connect_errors(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}])
        coord = GeoRideCoordinator(hass, entry, client)

        with patch(
            "custom_components.georide.coordinator.GeoRideSocketClient"
        ) as mock_cls:
            instance = AsyncMock()
            instance.connect = AsyncMock(side_effect=Exception("dns"))
            mock_cls.return_value = instance
            await coord.async_start_socket("token")
            # No socket cached because connect failed.
            assert coord._socket is None

    async def test_start_socket_idempotent(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}])
        coord = GeoRideCoordinator(hass, entry, client)

        with patch(
            "custom_components.georide.coordinator.GeoRideSocketClient"
        ) as mock_cls:
            instance = AsyncMock()
            instance.connect = AsyncMock()
            mock_cls.return_value = instance
            await coord.async_start_socket("token")
            await coord.async_start_socket("token")  # second call no-ops
            assert mock_cls.call_count == 1

    async def test_stop_socket_clears_reference(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}])
        coord = GeoRideCoordinator(hass, entry, client)

        with patch(
            "custom_components.georide.coordinator.GeoRideSocketClient"
        ) as mock_cls:
            instance = AsyncMock()
            instance.connect = AsyncMock()
            instance.disconnect = AsyncMock()
            mock_cls.return_value = instance
            await coord.async_start_socket("token")
            await coord.async_stop_socket()
            assert coord._socket is None
