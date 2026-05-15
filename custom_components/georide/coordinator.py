"""DataUpdateCoordinator for GeoRide trackers.

Polls /user/trackers every 60s, indexes the result by trackerId, and fires
Home Assistant events when state transitions are detected (lock toggle,
moving start/stop, alarm conditions). Events let users write event-driven
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

TrackersById = dict[int, dict[str, Any]]

# (payload-key, alarm-type) tuples — when the boolean flips False→True we
# fire georide_alarm_event with the alarm-type string.
_ALARM_FLAGS: tuple[tuple[str, str], ...] = (
    ("isStolen", "stolen"),
    ("isCrashed", "crashed"),
    ("hasTheftCaseOpened", "theft_case_opened"),
)


class GeoRideCoordinator(DataUpdateCoordinator[TrackersById]):
    """Polls /user/trackers and indexes the returned list by trackerId.

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

        await self._refresh_beacons(indexed)
        self._check_subscription_expiry(indexed)

        # `self.data` is the previous snapshot here (set by the base class
        # AFTER this method returns), so we can diff against it for free.
        if self.data is not None:
            self._fire_state_change_events(self.data, indexed)

        return indexed

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

    async def _refresh_beacons(self, trackers: TrackersById) -> None:
        """Fetch beacons for every tracker that reports hasBeacon=True.

        Per-tracker failures do not break the overall refresh; we keep the
        previous beacon snapshot for that tracker in that case.
        """
        new_beacons: dict[int, list[dict[str, Any]]] = {}
        for tid, tracker in trackers.items():
            if not tracker.get("hasBeacon"):
                new_beacons[tid] = []
                continue
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

            for key, alarm_type in _ALARM_FLAGS:
                if (
                    isinstance(prev.get(key), bool)
                    and isinstance(tracker.get(key), bool)
                    and not prev[key]
                    and tracker[key]
                ):
                    self.hass.bus.async_fire(
                        EVENT_ALARM, {**base, "type": alarm_type}
                    )
