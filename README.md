# GeoRide for Home Assistant

Unofficial Home Assistant integration for [GeoRide](https://georide.fr) motorcycle GPS trackers.

> **Status:** work in progress. Login + tracker list + trip summary service. No entities yet.

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
