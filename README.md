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
