# GeoRide for Home Assistant

Unofficial Home Assistant integration for [GeoRide](https://georide.fr)
motorcycle GPS trackers. GeoRide is a French motorbike tracker with
anti-theft alarm, lean-angle measurement, and a hosted dashboard. This
integration brings every tracker linked to your GeoRide account into Home
Assistant as a device with live position, sensors and binary sensors, and
exposes a service to compute trip statistics over any date range.

> **Status:** functional. Live position, sensors, binary sensors, trip
> summary service. No real-time push yet (polling at 60s).

## Quick install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bartolije&repository=georide-ha&category=integration)

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=georide)

1. Click the first badge → it adds this repo to HACS as a custom repository.
2. In HACS, install **GeoRide**, then restart Home Assistant.
3. Click the second badge → it opens the config flow to enter your GeoRide
   credentials.

Both badges use the [My Home Assistant](https://my.home-assistant.io) redirect
service. Home Assistant 2021.3 or newer required.

## Manual install (no HACS)

Copy `custom_components/georide/` into your Home Assistant `config/custom_components/`
directory and restart. Then add the integration through *Settings → Devices &
Services → Add Integration → GeoRide*.

## Configuration

The integration is configured entirely through the UI. You will be asked for
your GeoRide account email and password. Only the resulting bearer token is
persisted — the password is never stored.

If the token is later rejected by GeoRide (subscription expired, account
locked, password changed), Home Assistant raises a reauth notification and
asks you to re-enter the password. The same flow is reachable manually via
*Settings → Devices & Services → GeoRide → Configure* (a fresh login also
mints a new token without recreating the entry).

## Supported devices

Any tracker visible in your GeoRide account: motorbike trackers (1st and
2nd generation), and any beacon you have paired with them is reported via
the `has_beacon` binary sensor.

## What this integration exposes

For each tracker on the account, one Home Assistant device is created with
the following entities:

| Platform | Entity | What it shows |
|---|---|---|
| `device_tracker` | (tracker name) | Live GPS position; renders on the Lovelace map card. |
| `sensor` | Odometer | Total kilometres ridden (cumulative). |
| `sensor` | Speed | Instant speed in km/h. |
| `sensor` | Battery | Moto battery as % (computed from external voltage). |
| `sensor` | Last seen | Timestamp of the latest GPS fix. |
| `sensor` | Altitude | Diagnostic, disabled by default. |
| `sensor` | External battery voltage | Diagnostic, raw V. |
| `sensor` | Internal battery voltage | Diagnostic, disabled by default. |
| `sensor` | Subscription expires | Diagnostic, disabled by default. |
| `binary_sensor` | Lock | `DeviceClass.LOCK` — on = unlocked, off = locked. |
| `binary_sensor` | Moving | `DeviceClass.MOVING`. |
| `binary_sensor` | Stolen | `DeviceClass.SAFETY` — on = reported stolen. |
| `binary_sensor` | Crashed | `DeviceClass.PROBLEM` — on = crash detected. |
| `binary_sensor` | Has beacon | Diagnostic, disabled by default. |

Trackers that disappear from your GeoRide account (sold, transferred) are
automatically removed from the Home Assistant device registry on the next
restart.

## Data updates

The integration polls GeoRide every 60 seconds. There is no real-time push
in this version; if you need event-driven automations (alarms, crashes),
poll latency may matter for you. A websocket-based real-time path is on the
roadmap.

## Use cases

- Notify when the bike is moved while you are away (binary_sensor moving).
- Alert immediately on a crash or stolen-status flag.
- Track odometer over months for maintenance reminders (every 6000 km, etc.).
- Compute monthly riding stats (see Services below).
- Display your bike on the household Lovelace map alongside family members.

## Services

### `georide.trip_summary`

Fetch trips over a date range and return aggregate stats. Service responses
require a script or automation with `response_variable:`.

Example script:

```yaml
script:
  georide_last_30_days:
    sequence:
      - service: georide.trip_summary
        data:
          start_date: "{{ (now() - timedelta(days=30)).date() }}"
          end_date: "{{ now().date() }}"
        response_variable: summary
      - service: notify.persistent_notification
        data:
          message: >
            {{ summary.aggregate.trips_count }} trips,
            {{ summary.aggregate.total_km }} km
            (avg {{ summary.aggregate.avg_km_per_trip }} km).
            Max top speed: {{ summary.aggregate.max_top_speed }} km/h.
```

Response shape:

```yaml
range:
  from: "2026-04-14T00:00:00Z"
  to:   "2026-05-14T23:59:59Z"
trackers:
  "12345":
    tracker_name: "Z900"
    summary:
      trips_count: 18
      total_km: 743.2
      avg_km_per_trip: 41.3
      km_per_month: { "2026-04": 312.5, "2026-05": 430.7 }
      avg_top_speed: 138.2
      max_top_speed: 184.0
      max_lean_angle: 47.3
aggregate:
  # same shape as `summary`, aggregated across every tracker
```

Pass `tracker_id` to restrict to one tracker; `include_trips: true` adds the
raw trip list so a Lovelace card can render them on a map.

## Examples

### Notify when the bike starts moving while you are away

```yaml
automation:
  - alias: GeoRide moved while away
    trigger:
      platform: state
      entity_id: binary_sensor.z900_moving
      to: "on"
    condition:
      condition: state
      entity_id: person.me
      state: not_home
    action:
      service: notify.mobile_app_my_phone
      data:
        title: Bike moving
        message: "Your bike just started moving. Check the map."
```

### Low-battery alert

```yaml
automation:
  - alias: GeoRide low battery
    trigger:
      platform: numeric_state
      entity_id: sensor.z900_battery
      below: 20
    action:
      service: notify.persistent_notification
      data:
        message: "Bike battery is at {{ states('sensor.z900_battery') }} %."
```

## Known limitations

- **No real-time push.** Polling 60s. Alarm events that happen between two
  polls may be missed or delayed.
- **Lock/unlock is read-only.** This version does not expose a switch to
  lock or unlock the tracker. Planned.
- **Battery percentage is approximated** from the external voltage with a
  linear 11.0 V → 0 %, 12.7 V → 100 % curve. Real LiPo discharge curves are
  non-linear; treat as an estimate.
- **No 2FA support.** If your GeoRide account uses 2FA, the config flow
  will fail. Planned.

## Troubleshooting

Enable debug logs:

```yaml
logger:
  default: info
  logs:
    custom_components.georide: debug
```

You will see, for each polling cycle, the keys returned by the API and any
error during refresh. If the integration is failing to set up, the most
common causes are an expired subscription (reauth notification) and an
expired token (auto-handled by the reauth flow).

The full payload returned by GeoRide for each tracker is available via
*Settings → Devices & Services → GeoRide → ⋮ → Download diagnostics*. Lat,
lon and the bearer token are redacted before download.

## Removal

To uninstall:

1. *Settings → Devices & Services → GeoRide → ⋮ → Delete*. The entry, all
   devices and all entities are removed from Home Assistant.
2. Optionally: in HACS, *Frontend → GeoRide → Remove* to uninstall the
   custom_components files.
3. The bearer token remains valid on GeoRide's side until it expires
   naturally. To revoke it sooner, change your GeoRide password.

## Services

### `georide.trip_summary`

Fetch trips over a date range and return aggregate stats. Service responses
require a script or automation with `response_variable:`.

Example script:

```yaml
script:
  georide_last_30_days:
    sequence:
      - service: georide.trip_summary
        data:
          start_date: "{{ (now() - timedelta(days=30)).date() }}"
          end_date: "{{ now().date() }}"
        response_variable: summary
      - service: notify.persistent_notification
        data:
          message: >
            {{ summary.aggregate.trips_count }} trips,
            {{ summary.aggregate.total_km }} km
            (avg {{ summary.aggregate.avg_km_per_trip }} km).
            Max top speed: {{ summary.aggregate.max_top_speed }} km/h.
```

Response shape:

```yaml
range:
  from: "2026-04-14T00:00:00Z"
  to:   "2026-05-14T23:59:59Z"
trackers:
  "12345":
    tracker_name: "Z900"
    summary:
      trips_count: 18
      total_km: 743.2
      avg_km_per_trip: 41.3
      km_per_month: { "2026-04": 312.5, "2026-05": 430.7 }
      avg_top_speed: 138.2
      max_top_speed: 184.0
      max_lean_angle: 47.3   # null if GeoRide does not return this field
aggregate:
  # same shape as `summary`, aggregated across every tracker
```

Pass `tracker_id` to restrict to one tracker; `include_trips: true` adds the
raw trip list so a Lovelace card can render them on a map.

## Roadmap

- [ ] API client (auth, tracker list, positions)
- [ ] DataUpdateCoordinator (polling + WebSocket events)
- [ ] `device_tracker` entity per GeoRide
- [ ] `sensor` entities: battery (internal/external), speed, odometer, fix time
- [ ] `binary_sensor`: lock state, stolen, crashed, moving
- [ ] Event firing for alarms (vibration, crash, power cut, exit zone, etc.)
- [ ] HACS validation + brand assets

## License

[MIT](LICENSE)
