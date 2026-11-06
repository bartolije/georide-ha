"""Tests for the GeoRide coordinator (update cycle, secondary refreshes, events)."""
from __future__ import annotations

import pytest

pytest.importorskip("pytest_homeassistant")

from datetime import datetime, timedelta, timezone  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from homeassistant.exceptions import ConfigEntryAuthFailed  # noqa: E402
from homeassistant.helpers import issue_registry as ir  # noqa: E402
from homeassistant.helpers.update_coordinator import UpdateFailed  # noqa: E402
from pytest_homeassistant.common import MockConfigEntry  # noqa: E402

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
from custom_components.georide.coordinator import (  # noqa: E402
    LAST_TRIPS_INITIAL_LOOKBACK,
    LAST_TRIPS_LOOKBACK,
    GeoRideCoordinator,
)


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
    events=None,
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
    client.get_events = AsyncMock(return_value=events or [])
    client.add_trip_metrics = AsyncMock(side_effect=lambda tid, trip: trip)
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
    async def test_beacons_fetched_for_every_tracker(self, hass):
        entry = _make_entry(hass)
        client = _client(
            trackers=[{"trackerId": 1}, {"trackerId": 2}],
            beacons=[{"id": "beacon_99", "name": "Badge"}],
        )
        coord = GeoRideCoordinator(hass, entry, client)
        data = await coord._async_update_data()

        assert client.get_tracker_beacons.call_count == 2
        assert coord.beacons[2] == [{"id": "beacon_99", "name": "Badge"}]
        assert data[1]["hasBeacon"] is True

    async def test_beacons_refreshed_with_maintenance_cadence(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()
        data = await coord._async_update_data()
        assert client.get_tracker_beacons.call_count == 1
        assert data[1]["hasBeacon"] is False

    async def test_beacon_fetch_failure_keeps_previous_snapshot(self, hass):
        entry = _make_entry(hass)
        client = _client(
            trackers=[{"trackerId": 1}],
            beacons=[{"id": "beacon_99", "name": "Old"}],
        )
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()
        assert coord.beacons[1][0]["name"] == "Old"

        # Next refresh fails on beacons but trackers succeed.
        client.get_tracker_beacons.side_effect = GeoRideConnectionError("oops")
        coord._maintenance_fetched_at = None
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

    async def test_first_trip_lookup_reaches_a_year_back(self, hass):
        """After a restart the last ride can be months old (winter storage)."""
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}], trips=[{"id": 3, "endTime": "2026-03-01T10:00:00Z"}])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()

        from_iso, to_iso = client.get_trips.call_args.args[1:3]
        span = datetime.fromisoformat(to_iso.replace("Z", "+00:00")) - datetime.fromisoformat(
            from_iso.replace("Z", "+00:00")
        )
        assert span == LAST_TRIPS_INITIAL_LOOKBACK
        assert coord.last_trips[1]["id"] == 3

    async def test_last_trip_kept_when_short_window_is_empty(self, hass):
        """No ride in the last two days must not blank the last-trip sensors."""
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}], trips=[{"id": 3, "endTime": "2026-03-01T10:00:00Z"}])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()

        client.get_trips.return_value = []
        coord._last_trips_fetched_at = None  # skip the 5 min throttle
        await coord._async_update_data()

        from_iso, to_iso = client.get_trips.call_args.args[1:3]
        span = datetime.fromisoformat(to_iso.replace("Z", "+00:00")) - datetime.fromisoformat(
            from_iso.replace("Z", "+00:00")
        )
        assert span == LAST_TRIPS_LOOKBACK
        assert coord.last_trips[1]["id"] == 3

    async def test_new_trip_replaces_the_kept_one(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}], trips=[{"id": 3, "endTime": "2026-03-01T10:00:00Z"}])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()

        client.get_trips.return_value = [{"id": 4, "endTime": "2026-10-11T10:00:00Z"}]
        coord._last_trips_fetched_at = None
        await coord._async_update_data()
        assert coord.last_trips[1]["id"] == 4

    async def test_no_trip_in_a_year_is_none(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}], trips=[])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()
        assert coord.last_trips[1] is None

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
# Token renewal
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


# ---------------------------------------------------------------------------
# Tracker events (v2 replacement for the realtime socket alarms)
# ---------------------------------------------------------------------------
class TestTrackerEvents:
    async def test_first_poll_only_records_position(self, hass):
        events = []
        hass.bus.async_listen(EVENT_ALARM, lambda e: events.append(e))
        entry = _make_entry(hass)
        client = _client(
            trackers=[{"trackerId": 1, "trackerName": "ZX"}],
            events=[{"kind": "event/vibration/detected", "occurredAt": "2026-11-01T15:02:46.000Z"}],
        )
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()
        await hass.async_block_till_done()
        assert events == []

    async def test_new_events_fired_oldest_first(self, hass):
        events = []
        hass.bus.async_listen(EVENT_ALARM, lambda e: events.append(e))
        entry = _make_entry(hass)
        old = {"kind": "event/vibration/detected", "occurredAt": "2026-11-01T15:02:46.000Z"}
        client = _client(trackers=[{"trackerId": 1, "trackerName": "ZX"}], events=[old])
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()

        client.get_events = AsyncMock(return_value=[
            {"kind": "event/movement/detected", "occurredAt": "2026-11-06T18:00:02.000Z"},
            {"kind": "event/vibration/detected", "occurredAt": "2026-11-06T18:00:01.000Z"},
            old,
        ])
        await coord._async_update_data()
        await coord._async_update_data()  # same list again: nothing new
        await hass.async_block_till_done()
        assert [e.data["type"] for e in events] == ["vibration/detected", "movement/detected"]
        assert events[0].data["tracker_name"] == "ZX"
        assert events[0].data["source"] == "events"

    async def test_event_fetch_failure_is_ignored(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}])
        client.get_events = AsyncMock(side_effect=GeoRideConnectionError("down"))
        coord = GeoRideCoordinator(hass, entry, client)
        assert 1 in await coord._async_update_data()


class TestLastTripMetrics:
    async def test_latest_trip_gets_metrics(self, hass):
        entry = _make_entry(hass)
        client = _client(
            trackers=[{"trackerId": 1}],
            trips=[{"id": "trip_1", "endTime": "2026-09-13T17:32:41Z"}],
        )
        client.add_trip_metrics = AsyncMock(
            side_effect=lambda tid, trip: {**trip, "averageSpeed": 61}
        )
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()
        assert coord.last_trips[1]["averageSpeed"] == 61

    async def test_metrics_failure_keeps_trip(self, hass):
        entry = _make_entry(hass)
        client = _client(trackers=[{"trackerId": 1}], trips=[{"id": "trip_1"}])
        client.add_trip_metrics = AsyncMock(side_effect=GeoRideError("404"))
        coord = GeoRideCoordinator(hass, entry, client)
        await coord._async_update_data()
        assert coord.last_trips[1] == {"id": "trip_1"}


class TestStaleMaintenanceCleanup:
    async def test_v1_maintenance_entities_removed_v2_kept(self, hass):
        from homeassistant.helpers import entity_registry as er

        from custom_components.georide import _cleanup_stale_maintenance

        entry = _make_entry(hass)
        registry = er.async_get(hass)
        old = registry.async_get_or_create("sensor", DOMAIN, "1-maintenance-42", config_entry=entry)
        new = registry.async_get_or_create("sensor", DOMAIN, "1-maintenance-maintenance_a", config_entry=entry)
        other = registry.async_get_or_create("sensor", DOMAIN, "2-maintenance-7", config_entry=entry)
        odometer = registry.async_get_or_create("sensor", DOMAIN, "1-odometer", config_entry=entry)

        coord = MagicMock(maintenance={1: [{"id": "maintenance_a"}]})
        _cleanup_stale_maintenance(hass, entry, coord)

        assert registry.async_get(old.entity_id) is None
        assert registry.async_get(new.entity_id) is not None
        # Tracker 2's maintenance wasn't fetched: left alone.
        assert registry.async_get(other.entity_id) is not None
        assert registry.async_get(odometer.entity_id) is not None
