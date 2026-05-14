"""Live API tests against api.georide.com.

These tests are gated behind credentials. They will be SKIPPED automatically
if `GEORIDE_EMAIL` / `GEORIDE_PASSWORD` are not provided (env or
tests/secrets.local.env). When they run, they:

  - actually log in to the real account,
  - actually hit the GeoRide REST API,
  - print discovered payload keys so the integration can be typed safely.

Never print the token, password, or full payload bodies.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from georide.api import GeoRideApiClient


pytestmark = pytest.mark.live


async def test_login_returns_non_empty_token(
    aiohttp_session, georide_credentials
) -> None:
    email, password = georide_credentials
    client = GeoRideApiClient(aiohttp_session)
    token = await client.login(email, password)
    assert isinstance(token, str)
    assert len(token) > 16, "Token suspiciously short"
    # Do not print the token. Just confirm length and that the client cached it.
    assert client.token == token


async def test_get_trackers_returns_list(authed_client: GeoRideApiClient) -> None:
    trackers = await authed_client.get_trackers()
    assert isinstance(trackers, list)

    if not trackers:
        pytest.skip("Account has no trackers; remaining live tests need at least one")

    sample = trackers[0]
    assert isinstance(sample, dict)
    print(f"\n[discovered] tracker payload keys ({len(sample)}):")
    print(f"  {sorted(sample.keys())}")
    # Detect the id field name without asserting a specific one.
    id_field = next(
        (k for k in ("trackerId", "id", "tracker_id") if k in sample),
        None,
    )
    assert id_field is not None, (
        f"Could not find an id field in tracker payload. Keys: {sorted(sample)}"
    )


async def test_get_trips_last_30_days(authed_client: GeoRideApiClient) -> None:
    trackers = await authed_client.get_trackers()
    if not trackers:
        pytest.skip("Account has no trackers")
    tracker = trackers[0]
    tracker_id = tracker.get("trackerId") or tracker.get("id")
    assert tracker_id is not None

    end = date.today()
    start = end - timedelta(days=30)
    from_iso = f"{start.isoformat()}T00:00:00Z"
    to_iso = f"{end.isoformat()}T23:59:59Z"

    trips = await authed_client.get_trips(tracker_id, from_iso, to_iso)
    assert isinstance(trips, list)

    print(f"\n[discovered] {len(trips)} trip(s) in last 30 days for tracker {tracker_id}")
    if trips:
        sample = trips[0]
        assert isinstance(sample, dict)
        print(f"[discovered] trip payload keys ({len(sample)}):")
        print(f"  {sorted(sample.keys())}")
        # Print a tiny redacted preview so we can see value types.
        preview = {
            k: type(v).__name__ if not isinstance(v, (int, float, bool, str))
            else (v if not isinstance(v, str) or len(v) < 40 else f"{v[:37]}...")
            for k, v in sample.items()
        }
        print(f"[discovered] trip sample (types/short values):")
        print(f"  {preview}")
