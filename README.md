# GeoRide for Home Assistant

Unofficial Home Assistant integration for [GeoRide](https://georide.fr) motorcycle GPS trackers.

> **Status:** work in progress. Skeleton only. Not functional yet.

## Installation

### HACS (custom repository)

1. In HACS, go to *Integrations* → ⋮ → *Custom repositories*.
2. Add `https://github.com/bartolije/georide-ha` with category *Integration*.
3. Install **GeoRide**.
4. Restart Home Assistant.
5. Add the integration: *Settings → Devices & Services → Add Integration → GeoRide*.

### Manual

Copy `custom_components/georide/` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

The integration is configured through the UI. You will be asked for your GeoRide account email and password.

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
