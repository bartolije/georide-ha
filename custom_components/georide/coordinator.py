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
from homeassistant.const import CONF_TOKEN
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
    CONF_TOKEN_CREATED_AT,
    DOMAIN,
    EVENT_ALARM,
    EVENT_LOCK,
    EVENT_MOVING,
)
from .socket_client import GeoRideSocketClient

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(seconds=60)
SUBSCRIPTION_WARNING_WINDOW = timedelta(days=7)

# How often we re-fetch the per-tracker trip list to refresh the
# `last_trip_*` sensors. Polling /user/trackers is cheap, but trip lists
# can hold dozens of items per tracker; capping at 5 minutes is a polite
# trade-off — fresh enough for "last trip" semantics, light on the API.
LAST_TRIPS_REFRESH = timedelta(minutes=5)
LAST_TRIPS_LOOKBACK = timedelta(days=2)

# Maintenance items change rarely (user edits them in the GeoRide app).
# 15 minutes is a polite interval that still picks up changes promptly.
MAINTENANCE_REFRESH = timedelta(minutes=15)

# GeoRide tokens expire 30 days after being minted. Renewing weekly via
# /user/new-token keeps a wide safety margin: users only ever see a reauth
# prompt if HA stays offline for more than ~3 weeks straight.
TOKEN_RENEWAL_INTERVAL = timedelta(days=7)
# On renewal failure, wait this long before the next attempt so a flaky
# endpoint doesn't produce a warning every 60 s update cycle.
TOKEN_RENEWAL_RETRY = timedelta(hours=1)

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
        self.last_trips: dict[int, dict[str, Any] | None] = {}
        self.maintenance: dict[int, list[dict[str, Any]]] = {}
        self._last_trips_fetched_at: datetime | None = None
        self._maintenance_fetched_at: datetime | None = None
        self._token_renewal_attempted_at: datetime | None = None
        self._socket: GeoRideSocketClient | None = None

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

        await self._maybe_renew_token()
        await self._refresh_beacons(indexed)
        await self._maybe_refresh_last_trips(indexed)
        await self._maybe_refresh_maintenance(indexed)
        self._check_subscription_expiry(indexed)

        # `self.data` is the previous snapshot here (set by the base class
        # AFTER this method returns), so we can diff against it for free.
        if self.data is not None:
            self._fire_state_change_events(self.data, indexed)

        return indexed

    async def _maybe_renew_token(self) -> None:
        """Renew the bearer token before its 30-day expiry.

        Runs after a successful /user/trackers fetch, so the current token
        is known-good. When the token is older than TOKEN_RENEWAL_INTERVAL
        (or its mint date is unknown — entries created before this feature),
        a fresh token is fetched via /user/new-token, persisted on the
        config entry together with its mint date, and handed to the realtime
        socket for its next reconnection. Failures are logged and retried
        after TOKEN_RENEWAL_RETRY; a genuinely dead token surfaces through
        the normal polling path as ConfigEntryAuthFailed anyway.
        """
        now = datetime.now(tz=timezone.utc)

        created = self._token_created_at()
        if created is not None and now - created < TOKEN_RENEWAL_INTERVAL:
            return
        if (
            self._token_renewal_attempted_at is not None
            and now - self._token_renewal_attempted_at < TOKEN_RENEWAL_RETRY
        ):
            return

        self._token_renewal_attempted_at = now
        try:
            token = await self.client.renew_token()
        except GeoRideError as err:
            _LOGGER.warning(
                "GeoRide token renewal failed: %s — retrying in %s",
                err,
                TOKEN_RENEWAL_RETRY,
            )
            return

        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={
                **self.config_entry.data,
                CONF_TOKEN: token,
                CONF_TOKEN_CREATED_AT: now.isoformat(),
            },
        )
        if self._socket is not None:
            self._socket.update_token(token)
        _LOGGER.debug(
            "GeoRide token renewed; next renewal in %s", TOKEN_RENEWAL_INTERVAL
        )

    def _token_created_at(self) -> datetime | None:
        """Mint date of the stored token, or None when unknown/unparseable."""
        raw = self.config_entry.data.get(CONF_TOKEN_CREATED_AT)
        if not isinstance(raw, str):
            return None
        try:
            created = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if created.tzinfo is None:
            return None
        return created

    async def _maybe_refresh_last_trips(self, trackers: TrackersById) -> None:
        """Refresh last_trips at most every LAST_TRIPS_REFRESH window.

        Stores `self.last_trips[tracker_id]` = most recent trip dict (by
        `endTime`) or None when the lookback window has no trips. A failed
        fetch keeps the previous snapshot so the sensors don't flash unknown.
        """
        now = datetime.now(tz=timezone.utc)
        if (
            self._last_trips_fetched_at is not None
            and now - self._last_trips_fetched_at < LAST_TRIPS_REFRESH
        ):
            return

        from_iso = (now - LAST_TRIPS_LOOKBACK).strftime("%Y-%m-%dT%H:%M:%SZ")
        to_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        for tid in trackers:
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
                self.last_trips[tid] = trips[0]
            else:
                self.last_trips[tid] = None
        self._last_trips_fetched_at = now

    async def _maybe_refresh_maintenance(self, trackers: TrackersById) -> None:
        """Fetch maintenance items at most every MAINTENANCE_REFRESH window.

        Stores `self.maintenance[tracker_id]` as the raw list returned by
        /tracker/{id}/maintenance. Per-tracker failures keep the previous
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

    async def async_start_socket(self, token: str) -> None:
        """Open the realtime socket (best-effort).

        Failures don't break setup — the integration falls back to REST
        polling. Reconnects are handled by the underlying socket.io client.
        """
        if self._socket is not None:
            return
        socket = GeoRideSocketClient(token, self._handle_socket_event)
        try:
            await socket.connect()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "GeoRide realtime socket connect failed (%s) — falling back "
                "to %s polling",
                err,
                UPDATE_INTERVAL,
            )
            return
        self._socket = socket

    async def async_stop_socket(self) -> None:
        if self._socket is None:
            return
        try:
            await self._socket.disconnect()
        finally:
            self._socket = None

    async def _handle_socket_event(self, event: str, payload: Any) -> None:
        """Route a socket.io event to a coordinator-side reaction.

        - `position` / `lockedPosition`: merge into the cached tracker dict
          and notify listeners (no extra REST call).
        - `alarm`: fire `georide_alarm_event` with the granular `type`.
        - `device` / `refreshTrackersInstruction`: trigger a full REST
          refresh because the tracker list may have changed.
        - `message`: welcome/info, log only.
        """
        if event in ("message",):
            return
        if event == "position":
            self._apply_socket_position(payload)
        elif event == "lockedPosition":
            self._apply_socket_lock(payload)
        elif event == "alarm":
            self._fire_alarm_from_socket(payload)
        elif event in ("device", "refreshTrackersInstruction"):
            await self.async_request_refresh()

    def _apply_socket_position(self, payload: Any) -> None:
        if not isinstance(payload, dict) or self.data is None:
            return
        tid = self._tracker_id_from_payload(payload)
        if tid is None or tid not in self.data:
            return
        tracker = self.data[tid]
        for key in (
            "latitude",
            "longitude",
            "altitude",
            "speed",
            "moving",
            "fixtime",
            "odometer",
            "positionId",
        ):
            if key in payload:
                tracker[key] = payload[key]
        self.async_set_updated_data(self.data)

    def _apply_socket_lock(self, payload: Any) -> None:
        if not isinstance(payload, dict) or self.data is None:
            return
        tid = self._tracker_id_from_payload(payload)
        if tid is None or tid not in self.data:
            return
        tracker = self.data[tid]
        for key in (
            "isLocked",
            "lockedLatitude",
            "lockedLongitude",
            "lockedPositionId",
            "manualLock",
        ):
            if key in payload:
                tracker[key] = payload[key]
        self.async_set_updated_data(self.data)

    def _fire_alarm_from_socket(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        tid = self._tracker_id_from_payload(payload)
        alarm_type = payload.get("type") or payload.get("alarm") or "unknown"
        # Strip an "alarm_" prefix if GeoRide sends "alarm_vibration" etc.
        alarm_type = str(alarm_type).removeprefix("alarm_")
        device_id: str | None = None
        tracker_name: str | None = None
        if isinstance(tid, int):
            device_registry = dr.async_get(self.hass)
            device = device_registry.async_get_device(
                identifiers={(DOMAIN, str(tid))}
            )
            device_id = device.id if device else None
            if self.data and tid in self.data:
                tracker_name = self.data[tid].get("trackerName")
        self.hass.bus.async_fire(
            EVENT_ALARM,
            {
                "device_id": device_id,
                "tracker_id": tid,
                "tracker_name": tracker_name,
                "type": alarm_type,
                "source": "realtime",
                "raw": payload,
            },
        )

    @staticmethod
    def _tracker_id_from_payload(payload: dict[str, Any]) -> int | None:
        raw = payload.get("trackerId") or payload.get("id")
        try:
            return int(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

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
