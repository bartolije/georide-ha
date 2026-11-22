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
from homeassistant.helpers import entity_registry as er
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
    CONF_LEGACY,
    DOMAIN,
    EVENT_ALARM,
    EVENT_LOCK,
    EVENT_MOVING,
    LEGACY_DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=60)
SUBSCRIPTION_WARNING_WINDOW = timedelta(days=7)

# How often the `last_trip_*` sensors look for a newer trip (one call per tracker).
LAST_TRIPS_REFRESH = timedelta(minutes=5)

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
        # Trackers whose beacon fetch is failing: logged once, not every refresh.
        self._failing: set[tuple[str, int]] = set()
        self._uid_bases: dict[int, str] = {}

    async def _async_update_data(self) -> TrackersById:
        try:
            trackers = await self.client.get_trackers()
        except GeoRideAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except (GeoRideConnectionError, GeoRideError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        indexed: TrackersById = {}
        for tracker in trackers:
            tid = tracker.get("trackerId")
            if tid is None:
                # Seen on no model so far; said once, not every minute.
                self._report("tracker id", 0, GeoRideError(f"no realtimeId for {tracker.get('trackerName')}"))
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

        Stores `self.last_trips[tracker_id]` = the most recent trip, with its
        metrics (fetched once per trip), or None when the vehicle has no trip.
        A failed fetch keeps the previous snapshot so the sensors don't flash
        unknown.
        """
        now = datetime.now(tz=timezone.utc)
        if (
            self._last_trips_fetched_at is not None
            and now - self._last_trips_fetched_at < LAST_TRIPS_REFRESH
        ):
            return

        for tid in trackers:
            try:
                latest = await self.client.get_last_trip(tid)
            except GeoRideError as err:
                self._report("last trip", tid, err)
                continue
            self._report("last trip", tid)
            known = self.last_trips.get(tid)
            if latest is not None and known is not None and known.get("id") == latest.get("id"):
                continue  # same trip: its metrics are already there
            if latest is not None:
                try:
                    latest = await self.client.add_trip_metrics(tid, latest)
                except GeoRideError as err:
                    _LOGGER.debug("Trip metrics fetch failed for %s: %s", tid, err)
            self.last_trips[tid] = latest
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
            except GeoRideError as err:
                self._report("maintenance", tid, err)
                continue
            self._report("maintenance", tid)
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

            # Kept once the date has passed: the tracker stops working then.
            if expires < now + SUBSCRIPTION_WARNING_WINDOW:
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
        """Fire `georide_ha_alarm_event` for each tracker event newer than the last poll.

        The first poll only records where we are, so a restart doesn't replay
        old alarms. Types are the v2 kinds without the `event/` prefix, e.g.
        `vibration/detected`, `movement/detected`, `power/restored`.
        """
        for tid, tracker in trackers.items():
            try:
                events = await self.client.get_events(tid)
            except GeoRideError as err:
                self._report("events (alarms)", tid, err)
                continue
            self._report("events (alarms)", tid)
            stamps = [e["occurredAt"] for e in events if isinstance(e.get("occurredAt"), str)]
            if not stamps:
                # Still "seen": the tracker's very first event must fire, not be the baseline.
                self._last_event_at.setdefault(tid, "")
                continue
            last = self._last_event_at.get(tid)
            self._last_event_at[tid] = max(stamps + ([last] if last else []))
            if last is None:
                continue
            new = [e for e in events if isinstance(e.get("occurredAt"), str) and e["occurredAt"] > last]
            if not new:
                continue
            device = dr.async_get(self.hass).async_get_device_by_identifier(
                (DOMAIN, str(tid)), self.config_entry.entry_id
            )
            for event in sorted(new, key=lambda e: str(e["occurredAt"])):
                self._fire(
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
            except GeoRideError as err:
                self._report("beacons", tid, err)
                new_beacons[tid] = self.beacons.get(tid, [])
                continue
            self._report("beacons", tid)
        self.beacons = new_beacons

    def uid_base(self, tid: int) -> str:
        """Prefix of this tracker's entity unique ids.

        `tid`, unless the same vehicle (shared between two GeoRide accounts) is
        already in another entry of this Home Assistant: unique ids must differ,
        so this entry then uses `tid@entry_id`. Decided once and kept, since the
        registry remembers which entry registered first.
        """
        if tid not in self._uid_bases:
            registry = er.async_get(self.hass)
            entry_id = self.config_entry.entry_id
            suffixed = f"{tid}@{entry_id}"
            plain = registry.async_get_entity_id("device_tracker", DOMAIN, str(tid))
            taken = plain is not None and registry.entities[plain].config_entry_id != entry_id
            already = registry.async_get_entity_id("device_tracker", DOMAIN, suffixed)
            self._uid_bases[tid] = suffixed if taken or already else str(tid)
        return self._uid_bases[tid]

    def _report(self, what: str, tid: int, err: Exception | None = None) -> None:
        """Log a secondary fetch that starts failing (once) and when it works again.

        The previous values are kept meanwhile; without this a dead alarm feed
        would only show at debug level.
        """
        key = (what, tid)
        if err is not None and key not in self._failing:
            self._failing.add(key)
            _LOGGER.warning("GeoRide %s fetch failed for tracker %s: %s — keeping previous", what, tid, err)
        elif err is None and key in self._failing:
            self._failing.discard(key)
            _LOGGER.info("GeoRide %s fetch works again for tracker %s", what, tid)

    def _fire(self, event: str, data: dict[str, Any]) -> None:
        _LOGGER.debug("Firing %s %s", event, {k: v for k, v in data.items() if k != "device_id"})
        self.hass.bus.async_fire(event, data)
        if self.config_entry.data.get(CONF_LEGACY):
            # Taken over from the 0.17 domain: its users' automations keep working.
            self.hass.bus.async_fire(event.replace(DOMAIN, LEGACY_DOMAIN, 1), data)

    def _fire_state_change_events(
        self, previous: TrackersById, current: TrackersById
    ) -> None:
        """Diff snapshots and fire events for tracked transitions."""
        device_registry = dr.async_get(self.hass)
        for tid, tracker in current.items():
            prev = previous.get(tid)
            if prev is None:
                continue  # newly-added tracker; skip transitions

            device = device_registry.async_get_device_by_identifier(
                (DOMAIN, str(tid)), self.config_entry.entry_id
            )
            base = {
                "device_id": device.id if device else None,
                "tracker_id": tid,
                "tracker_name": tracker.get("trackerName"),
            }

            if isinstance(prev.get("isLocked"), bool) and isinstance(
                tracker.get("isLocked"), bool
            ) and prev["isLocked"] != tracker["isLocked"]:
                self._fire(
                    EVENT_LOCK, {**base, "is_locked": tracker["isLocked"]}
                )

            if isinstance(prev.get("moving"), bool) and isinstance(
                tracker.get("moving"), bool
            ) and prev["moving"] != tracker["moving"]:
                self._fire(
                    EVENT_MOVING, {**base, "moving": tracker["moving"]}
                )
