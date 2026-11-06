"""DataUpdateCoordinator for GeoRide trackers.

Polls the GeoRide v2 API every 60s (see `GeoRideApiClient.get_trackers`),
indexes the result by trackerId, and fires Home Assistant events when state
transitions are detected (lock toggle, moving start/stop) and for each new
tracker event (vibration, movement, …). The v2 API has no realtime socket,
so alarms arrive with the polling delay. Events let users write event-driven
automations without polling entities themselves.

Also raises a repair issue when a tracker's subscription is about to expire.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import (
    GeoRideApiClient,
    GeoRideAuthError,
    GeoRideConnectionError,
    GeoRideError,
)
from .const import (
    DOMAIN,
    EVENT_ALARM,
    EVENT_LOCK,
    EVENT_MOVING,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=60)
SUBSCRIPTION_WARNING_WINDOW = timedelta(days=7)

# How often we re-fetch the per-tracker trip list to refresh the
# `last_trip_*` sensors. Polling the trackers is cheap, but trip lists
# can hold dozens of items per tracker; capping at 5 minutes is a polite
# trade-off — fresh enough for "last trip" semantics, light on the API.
LAST_TRIPS_REFRESH = timedelta(minutes=5)
LAST_TRIPS_LOOKBACK = timedelta(days=2)
# Until a trip is known for a tracker, look back far enough to find the latest
# ride after a long break (winter storage, HA restart); afterwards the short
# window above only has to catch new trips.
LAST_TRIPS_INITIAL_LOOKBACK = timedelta(days=365)

# Maintenance items and beacons change rarely (user edits them in the GeoRide
# app). 15 minutes is a polite interval that still picks up changes promptly.
MAINTENANCE_REFRESH = timedelta(minutes=15)

TrackersById = dict[int, dict[str, Any]]


class GeoRideCoordinator(DataUpdateCoordinator[TrackersById]):
    """Polls the trackers and indexes the returned list by trackerId.

    Also fetches each tracker's beacons (key fob, top-case, TPMS, anything
    paired to the tracker) and stores them on `self.beacons`, keyed by
    tracker_id. Beacons are not part of `data` because they share a
    different lifecycle (rarely change) and we don't want them to break
    the typed `data` shape consumed by other modules.
    """

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: GeoRideApiClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.title}",
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.beacons: dict[int, list[dict[str, Any]]] = {}
        self.last_trips: dict[int, dict[str, Any] | None] = {}
        self.maintenance: dict[int, list[dict[str, Any]]] = {}
        self._last_trips_fetched_at: datetime | None = None
        self._maintenance_fetched_at: datetime | None = None
        # Newest tracker event already seen, per tracker (ISO 8601, sortable).
        self._last_event_at: dict[int, str] = {}

    async def _async_update_data(self) -> TrackersById:
        try:
            trackers = await self.client.get_trackers()
        except GeoRideAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (GeoRideConnectionError, GeoRideError) as err:
            raise UpdateFailed(str(err)) from err

        indexed: TrackersById = {}
        for tracker in trackers:
            tid = tracker.get("trackerId") or tracker.get("id")
            if tid is None:
                _LOGGER.warning(
                    "Skipping tracker without trackerId; keys=%s",
                    sorted(tracker.keys()),
                )
                continue
            indexed[int(tid)] = tracker

        await self._maybe_refresh_maintenance(indexed)
        for tid, tracker in indexed.items():
            tracker["hasBeacon"] = bool(self.beacons.get(tid))
        await self._maybe_refresh_last_trips(indexed)
        await self._poll_events(indexed)
        self._check_subscription_expiry(indexed)

        # `self.data` is the previous snapshot here (set by the base class
        # AFTER this method returns), so we can diff against it for free.
        if self.data is not None:
            self._fire_state_change_events(self.data, indexed)

        return indexed

    async def _maybe_refresh_last_trips(self, trackers: TrackersById) -> None:
        """Refresh last_trips at most every LAST_TRIPS_REFRESH window.

        Stores `self.last_trips[tracker_id]` = most recent trip dict (by
        `endTime`). The last trip stays in place when the short window comes
        back empty: an empty window only means no new ride, and dropping the
        trip there made every last-trip sensor go unknown two days after a
        ride. None means no trip in the initial year-long lookback. A failed
        fetch keeps the previous snapshot so the sensors don't flash unknown.
        """
        now = datetime.now(tz=timezone.utc)
        if (
            self._last_trips_fetched_at is not None
            and now - self._last_trips_fetched_at < LAST_TRIPS_REFRESH
        ):
            return

        to_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        for tid in trackers:
            known = self.last_trips.get(tid) is not None
            lookback = LAST_TRIPS_LOOKBACK if known else LAST_TRIPS_INITIAL_LOOKBACK
            from_iso = (now - lookback).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                trips = await self.client.get_trips(tid, from_iso, to_iso)
            except (GeoRideAuthError, GeoRideConnectionError, GeoRideError) as err:
                _LOGGER.debug(
                    "Last-trip fetch failed for tracker %s: %s — keeping previous",
                    tid,
                    err,
                )
                continue
            if trips:
                trips.sort(key=lambda t: t.get("endTime") or "", reverse=True)
                latest = trips[0]
                try:
                    latest = await self.client.add_trip_metrics(tid, latest)
                except GeoRideError as err:
                    _LOGGER.debug("Trip metrics fetch failed for %s: %s", tid, err)
                self.last_trips[tid] = latest
            elif not known:
                self.last_trips[tid] = None
        self._last_trips_fetched_at = now

    async def _maybe_refresh_maintenance(self, trackers: TrackersById) -> None:
        """Fetch maintenance items and beacons at most every MAINTENANCE_REFRESH.

        Stores `self.maintenance[tracker_id]` as returned by
        `client.get_maintenance`. Per-tracker failures keep the previous
        snapshot so entities don't flash unknown on a transient error.
        """
        now = datetime.now(tz=timezone.utc)
        if (
            self._maintenance_fetched_at is not None
            and now - self._maintenance_fetched_at < MAINTENANCE_REFRESH
        ):
            return

        for tid in trackers:
            try:
                items = await self.client.get_maintenance(tid)
            except (GeoRideAuthError, GeoRideConnectionError, GeoRideError) as err:
                _LOGGER.debug(
                    "Maintenance fetch failed for tracker %s: %s — keeping previous",
                    tid,
                    err,
                )
                continue
            self.maintenance[tid] = items
        await self._refresh_beacons(trackers)
        self._maintenance_fetched_at = now

    def _check_subscription_expiry(self, trackers: TrackersById) -> None:
        """Raise / clear a repair issue when a subscription is about to expire.

        Triggered when GeoRide's `expires` field puts the subscription end
        date within `SUBSCRIPTION_WARNING_WINDOW`. The issue clears itself
        when the field is renewed or the tracker disappears.
        """
        now = datetime.now(tz=timezone.utc)
        for tid, tracker in trackers.items():
            issue_id = f"subscription_expiring_{tid}"
            expires_raw = tracker.get("expires")
            if not isinstance(expires_raw, str):
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                continue
            try:
                expires = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
            except ValueError:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                continue

            if now < expires < now + SUBSCRIPTION_WARNING_WINDOW:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="subscription_expiring",
                    translation_placeholders={
                        "tracker_name": str(tracker.get("trackerName") or tid),
                        "expires": expires.strftime("%Y-%m-%d"),
                    },
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    async def _poll_events(self, trackers: TrackersById) -> None:
        """Fire `georide_alarm_event` for each tracker event newer than the last poll.

        The first poll only records where we are, so a restart doesn't replay
        old alarms. Types are the v2 kinds without the `event/` prefix, e.g.
        `vibration/detected`, `movement/detected`, `power/restored`.
        """
        for tid, tracker in trackers.items():
            try:
                events = await self.client.get_events(tid)
            except GeoRideError as err:
                _LOGGER.debug("Events fetch failed for tracker %s: %s", tid, err)
                continue
            stamps = [e["occurredAt"] for e in events if isinstance(e.get("occurredAt"), str)]
            if not stamps:
                continue
            last = self._last_event_at.get(tid)
            self._last_event_at[tid] = max(stamps + ([last] if last else []))
            if last is None:
                continue
            new = [e for e in events if isinstance(e.get("occurredAt"), str) and e["occurredAt"] > last]
            if not new:
                continue
            device = dr.async_get(self.hass).async_get_device(
                identifiers={(DOMAIN, str(tid))}
            )
            for event in sorted(new, key=lambda e: str(e["occurredAt"])):
                self.hass.bus.async_fire(
                    EVENT_ALARM,
                    {
                        "device_id": device.id if device else None,
                        "tracker_id": tid,
                        "tracker_name": tracker.get("trackerName"),
                        "type": str(event.get("kind") or "unknown").removeprefix("event/"),
                        "occurred_at": event["occurredAt"],
                        "source": "events",
                    },
                )

    async def _refresh_beacons(self, trackers: TrackersById) -> None:
        """Fetch the beacons paired with every tracker.

        Per-tracker failures do not break the overall refresh; we keep the
        previous beacon snapshot for that tracker in that case.
        """
        new_beacons: dict[int, list[dict[str, Any]]] = {}
        for tid in trackers:
            try:
                new_beacons[tid] = await self.client.get_tracker_beacons(tid)
            except (GeoRideAuthError, GeoRideConnectionError, GeoRideError) as err:
                _LOGGER.warning(
                    "GeoRide beacons fetch failed for tracker %s: %s — keeping last snapshot",
                    tid,
                    err,
                )
                new_beacons[tid] = self.beacons.get(tid, [])
        self.beacons = new_beacons

    def _fire_state_change_events(
        self, previous: TrackersById, current: TrackersById
    ) -> None:
        """Diff snapshots and fire events for tracked transitions."""
        device_registry = dr.async_get(self.hass)
        for tid, tracker in current.items():
            prev = previous.get(tid)
            if prev is None:
                continue  # newly-added tracker; skip transitions

            device = device_registry.async_get_device(
                identifiers={(DOMAIN, str(tid))}
            )
            base = {
                "device_id": device.id if device else None,
                "tracker_id": tid,
                "tracker_name": tracker.get("trackerName"),
            }

            if isinstance(prev.get("isLocked"), bool) and isinstance(
                tracker.get("isLocked"), bool
            ) and prev["isLocked"] != tracker["isLocked"]:
                self.hass.bus.async_fire(
                    EVENT_LOCK, {**base, "is_locked": tracker["isLocked"]}
                )

            if isinstance(prev.get("moving"), bool) and isinstance(
                tracker.get("moving"), bool
            ) and prev["moving"] != tracker["moving"]:
                self.hass.bus.async_fire(
                    EVENT_MOVING, {**base, "moving": tracker["moving"]}
                )
