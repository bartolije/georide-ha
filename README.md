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
events, last-trip stats and per-item maintenance counters. Talks to the
GeoRide v2 API (`api-v2.georide.com`, the one the app uses since 5.5),
polled every 60 s.

---

## 🇫🇷 En français — démarrage rapide

GeoRide est un traceur GPS antivol français pour moto, avec verrouillage
à distance, alerte vibration, détection de chute et angle de gite. Cette
intégration **non-officielle** branche ton compte GeoRide à Home
Assistant pour que ta moto y apparaisse comme un appareil avec :

- 📍 sa **position en direct** sur la carte
- 🔒 un bouton **verrouiller / déverrouiller** à distance (GeoRide 1 ; le
  GeoRide 3 se verrouille seul avec le badge ou le téléphone)
- 🚨 la **sirène Live Alarm** déclenchable + des événements HA quand
  l'alarme se déclenche (vibration, mouvement…), avec 1 min de délai
- 🔋 sa **batterie en %**, son **compteur kilométrique**,
  son **dernier trajet** (distance, durée, vitesse max, angle max à gauche et à droite)
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
   fois ; seul un jeton est conservé ensuite (pas le mot de passe), et
   il est renouvelé automatiquement chaque semaine — pas de
   ré-authentification mensuelle.

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

The integration is configured through the UI. Like the GeoRide app,
it logs in without a password: enter your account email, GeoRide
emails you a one-time code, type it in. Only the resulting session is
persisted.

GeoRide sessions last 90 days. When one expires (or after upgrading
from a version that used the old API, whose token the v2 API rejects),
Home Assistant raises a reauth notification: confirm, and type the new
code GeoRide emails you. The same flow is reachable manually via
*Settings → Devices & Services → GeoRide → Configure*, without
recreating the entry.

## What this integration exposes

For each tracker on the account, one Home Assistant device is created
with the following entities.

| Platform | Entity | What it shows |
|---|---|---|
| `device_tracker` | (tracker name) | Live GPS position; renders on the Lovelace map. |
| `lock` | (tracker name) | Manual lock of GeoRide 1 trackers only (GeoRide 3 locks itself with the badge / phone, so no entity). |
| `siren` | Siren | Rings the Live Alarm for the duration set in the app. Created only when the tracker has a Live Alarm. Turn-on only. |
| `switch` | Eco mode | Toggle eco mode ("bike without battery" in the app). Applied at the tracker's next connection, which can take hours while it sleeps. |
| `sensor` | Odometer | Cumulative kilometres ridden. |
| `sensor` | Speed | Unavailable: the v2 API no longer reports instant speed. |
| `sensor` | Battery | Moto battery % computed from external voltage. |
| `sensor` | Last seen | Timestamp of the latest GPS fix. |
| `sensor` | Last trip end / distance / duration / avg speed / top speed | Stats of the most recent ride (refreshed every 5 min). The last ride stays displayed until a new one is recorded, even after a long break or a restart (up to one year back). |
| `sensor` | Last trip max lean angle | Disabled by default. Lean from vertical in degrees; attributes `max_left`, `max_right` and `side`. |
| `sensor` | Altitude | Diagnostic, disabled by default. Unavailable with the v2 API. |
| `sensor` | External / internal battery voltage | Diagnostic. Internal voltage is unavailable with the v2 API (it reports a percentage). |
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

REST polling every 60 s against `api-v2.georide.com` (vehicle,
tracker, battery, mode, subscription and the latest tracker events).
Trips are refreshed every 5 min, maintenance items and badges every
15 min. The v2 API has no realtime channel (the GeoRide app no longer
opens the old socket.io stream), so alarms reach Home Assistant within
about a minute. "Moving" is inferred from the age of the last GPS fix
(under 5 min).

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
      avg_top_speed: 138.2        # km/h
      max_top_speed: 184.0        # km/h
      max_lean_angle: 47.3        # degrees from vertical, either side
      max_left_lean_angle: 47.3
      max_right_lean_angle: 44.1
aggregate:
  # same shape as `summary`, aggregated across every tracker
```

Pass `tracker_id` to restrict to one tracker; `include_trips: true`
adds the raw trip list so a Lovelace card can render them on a map.

## Events

The coordinator fires Home Assistant events on state transitions and
on new tracker events. Useful for event-driven automations.

| Event | `event_data` keys | Fired when |
|---|---|---|
| `georide_lock_event` | `device_id`, `tracker_id`, `tracker_name`, `is_locked` | `isLocked` flips. |
| `georide_moving_event` | `device_id`, `tracker_id`, `tracker_name`, `moving` | `moving` flips. |
| `georide_alarm_event` | `device_id`, `tracker_id`, `tracker_name`, `type`, `occurred_at`, `source` | Each new tracker event, `type` being the GeoRide kind without its `event/` prefix: `vibration/detected`, `movement/detected`, `displacement/detected`, `power/restored`, … (types changed with the v2 API). |

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
- **No instant speed, altitude, stolen or crashed flag** with the v2
  API: those entities stay unavailable.
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
Download diagnostics*. The session, lat/lon and email are
redacted automatically.

If the integration shows as red after install: most often an expired
session. Re-authenticate via the prompt or *Configure* (a new code is
emailed).

## Removal

1. *Settings → Devices & Services → GeoRide → ⋮ → Delete*. Every
   device, entity and the entry itself are removed.
2. In HACS, *Frontend → GeoRide → Remove* to uninstall the
   `custom_components` files.
3. The session stays valid on GeoRide's side until it expires
   (90 days).

## Quality scale

This integration declares the
[Home Assistant Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
in [`custom_components/georide/quality_scale.yaml`](custom_components/georide/quality_scale.yaml):

- 🥉 Bronze — **18 / 18** rules
- 🥈 Silver — **10 / 10** rules
- 🥇 Gold — **19 / 21** rules (2 marked `exempt`)
- 🏆 Platinum — **3 / 3** rules

Backed by mypy `--strict`, 276 tests at 96 % coverage and a CI
workflow that runs both on every push.

## License

[MIT](LICENSE)
