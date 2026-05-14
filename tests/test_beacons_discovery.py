"""Live discovery: dump the beacons payload so we can design entities.

Run with: pytest tests/test_beacons_discovery.py -m live -s
"""
from __future__ import annotations

import pytest

from georide.api import GeoRideApiClient


pytestmark = pytest.mark.live


async def test_dump_beacons_schema(authed_client: GeoRideApiClient) -> None:
    trackers = await authed_client.get_trackers()
    if not trackers:
        pytest.skip("Account has no trackers")

    for tracker in trackers:
        tid = tracker.get("trackerId") or tracker.get("id")
        if tid is None:
            continue

        print(f"\n=== Tracker {tid} ({tracker.get('trackerName')}) ===")
        print(f"hasBeacon         = {tracker.get('hasBeacon')}")
        print(f"hasOutdatedBeacons= {tracker.get('hasOutdatedBeacons')}")
        print(f"bleScanDelay      = {tracker.get('bleScanDelay')}")
        print(f"bleSoftwareVersion= {tracker.get('bleSoftwareVersion')}")

        beacons = await authed_client.get_tracker_beacons(tid)
        print(f"Beacons returned  = {len(beacons)}")

        if not beacons:
            continue

        sample = beacons[0]
        print(f"Beacon payload keys ({len(sample)}): {sorted(sample.keys())}")
        # Preview values, redacting long strings.
        preview = {
            k: (
                type(v).__name__
                if not isinstance(v, (int, float, bool, str))
                else (v if not isinstance(v, str) or len(v) < 60 else f"{v[:57]}...")
            )
            for k, v in sample.items()
        }
        print(f"Beacon sample (types/short values):\n  {preview}")

        if len(beacons) > 1:
            print(f"\nFull list ({len(beacons)} beacons), types/names only:")
            for idx, b in enumerate(beacons):
                hint = {
                    k: b.get(k)
                    for k in ("name", "type", "kind", "category", "model")
                    if k in b
                }
                print(f"  [{idx}] {hint or b.get('id')}")
