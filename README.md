<p align="center">
  <img src="logo.png" alt="GeoRide" width="380">
</p>

# GeoRide for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![release](https://img.shields.io/github/v/release/bartolije/georide-ha)](https://github.com/bartolije/georide-ha/releases)
[![ci](https://github.com/bartolije/georide-ha/actions/workflows/ci.yml/badge.svg)](https://github.com/bartolije/georide-ha/actions)

Unofficial Home Assistant integration for [GeoRide](https://georide.fr)
motorcycle GPS trackers. Brings every tracker on your account into
Home Assistant as a device with live position, lock control, alarm
events, last-trip stats and per-item maintenance counters. Realtime
socket.io stream for instant push, REST polling as fallback.

---

## 🇫🇷 En français — démarrage rapide

GeoRide est un traceur GPS antivol français pour moto, avec verrouillage
à distance, alerte vibration, détection de chute et angle de gite. Cette
intégration **non-officielle** branche ton compte GeoRide à Home
Assistant pour que ta moto y apparaisse comme un appareil avec :

- 📍 sa **position en direct** sur la carte
- 🔒 un bouton **verrouiller / déverrouiller** à distance
- 🚨 une **sirène** déclenchable + des événements HA quand l'alarme se
  déclenche (vibration, choc, sortie de zone…)
- 🔋 sa **batterie en %**, sa **vitesse**, son **compteur kilométrique**,
  son **dernier trajet** (distance, durée, vitesse max, angle max)
- 🛠️ un **capteur diagnostique par item de maintenance** que tu as
  configuré dans l'app GeoRide (vidange, chaîne, pneus…)
- 🏷️ tes **badges Bluetooth** apparaissent comme appareils séparés avec
  leur batterie

### Installation en 3 étapes

1. Dans HACS, ajoute ce dépôt en *custom repository* (badge bleu plus
   bas, ou *HACS → Integrations → ⋮ → Custom repositories →*
   `https://github.com/bartolije/georide-ha`).
2. Installe **GeoRide** depuis HACS, puis redémarre Home Assistant.
3. *Réglages → Appareils & Services → Ajouter une intégration →
   GeoRide*. Tu saisis ton email et ton mot de passe GeoRide une seule
   fois ; seul un jeton est conservé ensuite (pas le mot de passe).

L'interface est traduite en **français, allemand, espagnol, italien et
néerlandais** : si Home Assistant est configuré dans une de ces
langues, les entités, erreurs et services s'affichent traduits. Les
traductions DE / ES / IT / NL sont *initiales et perfectibles* —
contributions natives bienvenues via pull request.

---

## Quick install

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bartolije&repository=georide-ha&category=integration)

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=georide)

1. First badge adds this repo to HACS as a custom repository.
2. Install **GeoRide** in HACS, restart Home Assistant.
3. Second badge opens the config flow.

Both badges use the [My Home Assistant](https://my.home-assistant.io)
redirect. Home Assistant 2024.11 or newer required.

### Manual install (no HACS)

Copy `custom_components/georide/` into your Home Assistant
`config/custom_components/` directory and restart. Then add the
integration through *Settings → Devices & Services → Add Integration →
GeoRide*.

## Configuration

The integration is configured through the UI. You will be asked for
your GeoRide account email and password. Only the resulting bearer
token is persisted — the password is never stored.

If the token is later rejected by GeoRide (subscription expired,
account locked, password changed), Home Assistant raises a reauth
notification. The same flow is reachable manually via *Settings →
Devices & Services → GeoRide → Configure* (a fresh login mints a new
token without recreating the entry).

## What this integration exposes

For each tracker on the account, one Home Assistant device is created
with the following entities.

| Platform | Entity | What it shows |
|---|---|---|
| `device_tracker` | (tracker name) | Live GPS position; renders on the Lovelace map. |
| `lock` | (tracker name) | Lock / unlock the GeoRide remotely. Follows `isLocked`. |
| `siren` | Siren | Trigger or stop the sonor alarm. Write-only. |
| `switch` | Eco mode | Toggle eco mode (slower fixes, longer battery). |
| `sensor` | Odometer | Cumulative kilometres ridden. |
| `sensor` | Speed | Instant speed (km/h). |
| `sensor` | Battery | Moto battery % computed from external voltage. |
| `sensor` | Last seen | Timestamp of the latest GPS fix. |
| `sensor` | Last trip end / distance / duration / avg speed / top speed | Stats of the most recent ride (refreshed every 5 min). |
| `sensor` | Last trip max lean angle | Disabled by default. |
| `sensor` | Altitude | Diagnostic, disabled by default. |
| `sensor` | External / internal battery voltage | Diagnostic. |
| `sensor` | Subscription expires | Diagnostic, disabled by default. |
| `sensor` | (per maintenance item) | One diagnostic sensor per item you configured in the GeoRide app. Auto-detects km vs days. |
| `binary_sensor` | Moving | `DeviceClass.MOVING`. |
| `binary_sensor` | Stolen | `DeviceClass.SAFETY` — on = reported stolen. |
| `binary_sensor` | Crashed | `DeviceClass.PROBLEM` — on = crash detected. |
| `binary_sensor` | Has beacon | Diagnostic, disabled by default. |

Trackers and beacons that disappear from your GeoRide account are
removed from Home Assistant on the next restart. New ones appear
automatically within ~60 seconds.

### Beacons

Every Bluetooth beacon paired with a tracker (key fob, top-case
sensor, TPMS, …) shows up as a separate device nested under its
tracker via `via_device`.

| Platform | Entity | What it shows |
|---|---|---|
| `sensor` | Battery | Beacon battery in %. |
| `sensor` | Last battery report | Timestamp of the last battery-level update. |
| `binary_sensor` | Firmware update available | `DeviceClass.UPDATE`. |

Beacon model (e.g. `gen-1`) is shown on the device card; the MAC
address is attached as a HA connection.

## Data updates

Two channels in parallel:

- **Realtime socket.io** (`socket.georide.com`) — position, lock state
  and alarms pushed within seconds. Reconnections handled
  automatically.
- **REST polling every 60 s** (`api.georide.com`) — source of truth.
  Keeps entities fresh even if the realtime socket is down. Trips
  refreshed every 5 min, maintenance items every 15 min.

If the realtime socket fails, the integration logs a warning and keeps
running on polling alone.

## Services

### `georide.trip_summary`

Fetch trips over a date range and return aggregate stats. Service
responses require a script or automation with `response_variable:`.

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

Pass `tracker_id` to restrict to one tracker; `include_trips: true`
adds the raw trip list so a Lovelace card can render them on a map.

## Events

The coordinator fires Home Assistant events on state transitions and
on realtime alarms. Useful for event-driven automations.

| Event | `event_data` keys | Fired when |
|---|---|---|
| `georide_lock_event` | `device_id`, `tracker_id`, `tracker_name`, `is_locked` | `isLocked` flips. |
| `georide_moving_event` | `device_id`, `tracker_id`, `tracker_name`, `moving` | `moving` flips. |
| `georide_alarm_event` | `device_id`, `tracker_id`, `tracker_name`, `type`, optionally `source` and `raw` | Stolen / crashed / theft case opened via polling, plus the granular realtime types (`vibration`, `exitZone`, `crashParking`, `powerCut`, `magnetOn`, `batteryWarning`, …). |

## Automation examples

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

### Push notification on every alarm

```yaml
automation:
  - alias: GeoRide alarm
    trigger:
      platform: event
      event_type: georide_alarm_event
    action:
      service: notify.mobile_app_my_phone
      data:
        title: "GeoRide alarm: {{ trigger.event.data.type }}"
        message: "{{ trigger.event.data.tracker_name }} triggered."
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

## Lovelace card

A single-file custom card lives in `lovelace/georide-card.js`. It
bundles the map, lock toggle, battery, speed, odometer, last-seen and
last trip stats into one compact widget per tracker. Optional bike
photo as a banner backdrop.

### Install

1. Copy `lovelace/georide-card.js` into your Home Assistant
   `<config>/www/` folder.
2. *Settings → Dashboards → ⋮ → Resources → Add resource* — URL
   `/local/georide-card.js`, type *JavaScript module*.
3. In a dashboard edit mode, *Add card → GeoRide bike*.

```yaml
type: custom:georide-card
device_id: <pick from card editor>
image: /local/zx10r.jpg   # optional — drop a bike photo in /config/www/
```

GeoRide's API doesn't expose a bike photo, so the `image:` field lets
you bring your own. Without it, the card falls back to a text header.

## Known limitations

- **Battery percentage is approximated** from external voltage with a
  linear 11.0 V → 0 %, 12.7 V → 100 % curve. Real lead-acid discharge
  curves are non-linear; treat as an estimate.
- **Siren state is write-only.** GeoRide's API does not report siren
  state back; the integration shows it as unknown.
- **2FA accounts not supported yet.** If your GeoRide account uses
  2FA, the config flow will fail.
- **Custom integration**: not in core HA. Updates ship through HACS.

## Troubleshooting

Enable debug logs to see what the integration is fetching:

```yaml
logger:
  default: info
  logs:
    custom_components.georide: debug
```

For a full snapshot, *Settings → Devices & Services → GeoRide → ⋮ →
Download diagnostics*. The bearer token, lat/lon and email are
redacted automatically.

If the integration shows as red after install: most often a stale
token. Re-authenticate via the prompt or *Configure → enter password*.

## Removal

1. *Settings → Devices & Services → GeoRide → ⋮ → Delete*. Every
   device, entity and the entry itself are removed.
2. In HACS, *Frontend → GeoRide → Remove* to uninstall the
   `custom_components` files.
3. The bearer token stays valid on GeoRide's side until it expires
   naturally. To revoke it sooner, change your GeoRide password.

## Quality scale

This integration declares the
[Home Assistant Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
in [`custom_components/georide/quality_scale.yaml`](custom_components/georide/quality_scale.yaml):

- 🥉 Bronze — **18 / 18** rules
- 🥈 Silver — **10 / 10** rules
- 🥇 Gold — **19 / 21** rules (2 marked `exempt`)
- 🏆 Platinum — **3 / 3** rules

Backed by mypy `--strict`, 350+ tests at 97 % coverage and a CI
workflow that runs both on every push.

## License

[MIT](LICENSE)
