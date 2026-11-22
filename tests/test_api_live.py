"""Live API tests against api-v2.georide.com.

These tests are gated behind a session. They will be SKIPPED automatically
if `GEORIDE_SESSION` is not provided (env or tests/secrets.local.env).
When they run, they:

  - use the real account's session cookie (read-only calls),
  - actually hit the GeoRide REST API,
  - print discovered payload keys so the integration can be typed safely.

Never print the session cookie or full payload bodies.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from georide_ha.api import GeoRideApiClient


pytestmark = pytest.mark.live

# Read-only canary: every read the integration relies on must still answer in the
# shape the entities expect. Prints nothing personal (CI logs are public).


async def test_every_read_of_the_poll_still_works(authed_client: GeoRideApiClient, caplog) -> None:
    trackers = await authed_client.get_trackers()
    if not trackers:
        pytest.skip("Account has no trackers")
    # A route GeoRide removed is logged as "optional data unavailable".
    assert "optional data unavailable" not in caplog.text
    assert not authed_client._skipped
    for tracker in trackers:
        assert isinstance(tracker["trackerId"], int)
        for key in ("trackerName", "odometer", "fixtime", "online", "vehicleId", "georideTrackerId"):
            assert tracker[key] is not None, key
        assert isinstance(tracker["capabilities"], list)


async def test_secondary_reads_keep_their_shape(authed_client: GeoRideApiClient) -> None:
    trackers = await authed_client.get_trackers()
    if not trackers:
        pytest.skip("Account has no trackers")
    tid = trackers[0]["trackerId"]

    trip = await authed_client.get_last_trip(tid)
    if trip is not None:
        assert {"id", "startTime", "endTime", "distance", "duration", "maxSpeed"} <= set(trip)
        with_metrics = await authed_client.add_trip_metrics(tid, trip)
        assert {"averageSpeed", "maxLeftAngle", "maxRightAngle"} <= set(with_metrics)

    end = date.today()
    trips = await authed_client.get_trips(tid, f"{(end - timedelta(days=30)).isoformat()}T00:00:00Z", f"{end.isoformat()}T23:59:59Z")
    assert isinstance(trips, list)

    for item in await authed_client.get_maintenance(tid):
        assert {"id", "name", "todo", "dateUnitType"} <= set(item)
    for beacon in await authed_client.get_tracker_beacons(tid):
        assert {"id", "name"} <= set(beacon)
    for event in await authed_client.get_events(tid):
        assert {"kind", "occurredAt"} <= set(event)
    assert await authed_client.get_session_expiry()
