/**
 * GeoRide bike card — single-file Lovelace custom card.
 *
 * Bundles the entities that this integration creates for one tracker
 * (device_tracker, lock, battery sensor, speed, odometer, last_seen, last
 * trip stats and the eco-mode switch) into one compact card.
 *
 * Install:
 *   1. Copy this file to `<config>/www/georide-card.js`
 *   2. Add a Lovelace resource:
 *        url: /local/georide-card.js
 *        type: module
 *   3. Use in any dashboard:
 *        type: custom:georide-card
 *        device_id: <id of the GeoRide tracker device in HA>
 *
 * The card discovers its entities by walking hass.entities for the given
 * device_id, so it works regardless of the entity_id slugs HA picks for
 * the user's bike name.
 */

import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.4.0/lit-element.js?module";

const VERSION = "0.1.0";

/* eslint-disable no-console */
console.info(
  `%c GEORIDE-CARD %c v${VERSION} `,
  "color: white; background: #ff8c00; font-weight: 700;",
  "color: #ff8c00; background: white; font-weight: 700;"
);

class GeoRideCard extends LitElement {
  static get properties() {
    return {
      hass: { attribute: false },
      _config: { state: true },
    };
  }

  static get styles() {
    return css`
      ha-card {
        padding: 0;
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }
      .banner {
        height: 160px;
        background-size: cover;
        background-position: center;
        background-color: var(--card-background-color);
        position: relative;
      }
      .banner::after {
        content: "";
        position: absolute;
        inset: 0;
        background: linear-gradient(
          to bottom,
          transparent 50%,
          rgba(0, 0, 0, 0.45)
        );
      }
      .banner-title {
        position: absolute;
        bottom: 8px;
        left: 12px;
        right: 12px;
        color: white;
        font-size: 1.2rem;
        font-weight: 700;
        text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
        display: flex;
        align-items: center;
        gap: 6px;
        z-index: 1;
      }
      .body {
        padding: 12px;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .name {
        font-size: 1.1rem;
        font-weight: 600;
      }
      .actions {
        display: flex;
        gap: 4px;
      }
      .actions ha-icon-button {
        --mdc-icon-button-size: 36px;
        --mdc-icon-size: 22px;
      }
      .map {
        border-radius: 8px;
        overflow: hidden;
        height: 220px;
        background: var(--card-background-color);
      }
      ha-map {
        height: 100%;
      }
      .stats {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
        gap: 8px;
        margin-top: 4px;
      }
      .stat {
        display: flex;
        flex-direction: column;
        align-items: center;
        text-align: center;
        padding: 6px 4px;
        background: var(--ha-card-background, var(--card-background-color));
        border-radius: 8px;
        border: 1px solid var(--divider-color);
      }
      .stat .label {
        font-size: 0.7rem;
        color: var(--secondary-text-color);
        text-transform: uppercase;
        letter-spacing: 0.04em;
      }
      .stat .value {
        font-weight: 600;
        margin-top: 2px;
      }
      .trip {
        font-size: 0.85rem;
        color: var(--secondary-text-color);
        border-top: 1px solid var(--divider-color);
        padding-top: 6px;
      }
      .trip strong {
        color: var(--primary-text-color);
      }
      .pill {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        background: var(--state-icon-color, var(--primary-color));
        color: white;
        font-size: 0.7rem;
        margin-left: 6px;
      }
      .pill.locked {
        background: var(--state-binary_sensor-safety-off-color, #45a843);
      }
      .pill.unlocked {
        background: var(--warning-color, #f4b400);
      }
      .pill.alarm {
        background: var(--error-color, #e74c3c);
      }
    `;
  }

  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    if (!config.device_id)
      throw new Error("`device_id` is required. Pick your GeoRide device in the card editor.");
    this._config = config;
  }

  getCardSize() {
    return 5;
  }

  /**
   * Build a map of "purpose -> entity_id" by walking the entity registry
   * for the configured device_id. Purposes are detected from the
   * unique_id suffix the integration writes (e.g. "<id>-odometer",
   * "<id>-lock", "<id>-eco_mode"). Falls back to the entity_id when the
   * unique_id is unavailable.
   */
  _entities() {
    if (!this.hass || !this._config) return {};
    const want = this._config.device_id;
    const found = {};
    const entries = this.hass.entities || {};
    for (const entityId of Object.keys(entries)) {
      const entry = entries[entityId];
      if (entry.device_id !== want) continue;
      const slug = (entry.unique_id || entityId).toLowerCase();
      if (entityId.startsWith("device_tracker.")) found.tracker = entityId;
      else if (entityId.startsWith("lock.")) found.lock = entityId;
      else if (entityId.startsWith("siren.")) found.siren = entityId;
      else if (entityId.startsWith("switch.") && slug.endsWith("eco_mode")) found.eco = entityId;
      else if (slug.endsWith("battery_level")) found.battery = entityId;
      else if (slug.endsWith("battery") && !slug.includes("voltage")) found.battery = found.battery || entityId;
      else if (slug.endsWith("speed") && !slug.includes("last_trip")) found.speed = entityId;
      else if (slug.endsWith("odometer")) found.odometer = entityId;
      else if (slug.endsWith("last_seen")) found.lastSeen = entityId;
      else if (slug.endsWith("last_trip_distance")) found.tripDistance = entityId;
      else if (slug.endsWith("last_trip_duration")) found.tripDuration = entityId;
      else if (slug.endsWith("last_trip_max_speed")) found.tripMaxSpeed = entityId;
      else if (slug.endsWith("last_trip_end")) found.tripEnd = entityId;
      else if (slug.endsWith("moving")) found.moving = entityId;
      else if (slug.endsWith("stolen")) found.stolen = entityId;
      else if (slug.endsWith("crashed")) found.crashed = entityId;
    }
    return found;
  }

  _stateOf(entityId) {
    if (!entityId) return null;
    return this.hass?.states?.[entityId] || null;
  }

  _format(entityId, fallback = "—") {
    const s = this._stateOf(entityId);
    if (!s || s.state === "unknown" || s.state === "unavailable") return fallback;
    const unit = s.attributes?.unit_of_measurement;
    return unit ? `${s.state} ${unit}` : s.state;
  }

  _formatRelative(entityId) {
    const s = this._stateOf(entityId);
    if (!s || s.state === "unknown" || s.state === "unavailable") return "—";
    const t = new Date(s.state).getTime();
    if (Number.isNaN(t)) return s.state;
    const diffSec = (Date.now() - t) / 1000;
    if (diffSec < 60) return `${Math.round(diffSec)}s`;
    if (diffSec < 3600) return `${Math.round(diffSec / 60)} min`;
    if (diffSec < 86400) return `${Math.round(diffSec / 3600)} h`;
    return `${Math.round(diffSec / 86400)} j`;
  }

  _deviceName() {
    const want = this._config.device_id;
    const devices = this.hass?.devices || {};
    return devices[want]?.name_by_user || devices[want]?.name || "GeoRide";
  }

  _toggleLock() {
    const e = this._entities();
    if (!e.lock) return;
    const s = this._stateOf(e.lock);
    const service = s?.state === "locked" ? "unlock" : "lock";
    this.hass.callService("lock", service, { entity_id: e.lock });
  }

  _triggerSiren() {
    const e = this._entities();
    if (!e.siren) return;
    if (!confirm("Déclencher l'alarme sonore ?")) return;
    this.hass.callService("siren", "turn_on", { entity_id: e.siren });
  }

  render() {
    if (!this.hass || !this._config) return html``;

    const e = this._entities();
    const tracker = this._stateOf(e.tracker);
    const lock = this._stateOf(e.lock);
    const stolen = this._stateOf(e.stolen)?.state === "on";
    const crashed = this._stateOf(e.crashed)?.state === "on";
    const moving = this._stateOf(e.moving)?.state === "on";

    let pill = null;
    if (crashed) pill = html`<span class="pill alarm">CRASH</span>`;
    else if (stolen) pill = html`<span class="pill alarm">STOLEN</span>`;
    else if (moving) pill = html`<span class="pill unlocked">EN ROUTE</span>`;
    else if (lock?.state === "locked") pill = html`<span class="pill locked">VERROUILLÉ</span>`;
    else if (lock?.state === "unlocked") pill = html`<span class="pill unlocked">DÉVERROUILLÉ</span>`;

    const image = this._config.image;
    return html`
      <ha-card>
        ${image
          ? html`<div class="banner" style="background-image: url('${image}')">
              <div class="banner-title">${this._deviceName()}${pill}</div>
            </div>`
          : ""}
        <div class="body">
          ${image
            ? ""
            : html`<div class="header">
                <span class="name">${this._deviceName()}${pill}</span>
                <div class="actions">
                  ${e.lock
                    ? html`<ha-icon-button @click=${this._toggleLock} title="Toggle lock">
                        <ha-icon icon="${lock?.state === "locked" ? "mdi:lock" : "mdi:lock-open"}"></ha-icon>
                      </ha-icon-button>`
                    : ""}
                  ${e.siren
                    ? html`<ha-icon-button @click=${this._triggerSiren} title="Trigger siren">
                        <ha-icon icon="mdi:alarm-light"></ha-icon>
                      </ha-icon-button>`
                    : ""}
                </div>
              </div>`}
          ${image
            ? html`<div class="header">
                <span></span>
                <div class="actions">
                  ${e.lock
                    ? html`<ha-icon-button @click=${this._toggleLock} title="Toggle lock">
                        <ha-icon icon="${lock?.state === "locked" ? "mdi:lock" : "mdi:lock-open"}"></ha-icon>
                      </ha-icon-button>`
                    : ""}
                  ${e.siren
                    ? html`<ha-icon-button @click=${this._triggerSiren} title="Trigger siren">
                        <ha-icon icon="mdi:alarm-light"></ha-icon>
                      </ha-icon-button>`
                    : ""}
                </div>
              </div>`}

          ${e.tracker && tracker?.attributes?.latitude
            ? html`<div class="map">
                <ha-map
                  .hass=${this.hass}
                  .entities=${[e.tracker]}
                  zoom="15"
                  autoFit
                ></ha-map>
              </div>`
            : ""}

          <div class="stats">
          <div class="stat">
            <span class="label">Batterie</span>
            <span class="value">${this._format(e.battery)}</span>
          </div>
          <div class="stat">
            <span class="label">Vitesse</span>
            <span class="value">${this._format(e.speed, "0 km/h")}</span>
          </div>
          <div class="stat">
            <span class="label">Compteur</span>
            <span class="value">${this._format(e.odometer)}</span>
          </div>
          <div class="stat">
            <span class="label">Vue il y a</span>
            <span class="value">${this._formatRelative(e.lastSeen)}</span>
          </div>
        </div>

          ${e.tripDistance
            ? html`<div class="trip">
                Dernier trajet :
                <strong>${this._format(e.tripDistance)}</strong>
                ·
                <strong>${this._format(e.tripDuration)}</strong>
                ·
                max <strong>${this._format(e.tripMaxSpeed)}</strong>
                <br />
                <span>fin ${this._formatRelative(e.tripEnd)}</span>
              </div>`
            : ""}
        </div>
      </ha-card>
    `;
  }

  static getConfigElement() {
    return document.createElement("hui-generic-entity-row");
  }

  static getStubConfig(hass) {
    const devices = Object.values(hass?.devices || {}).filter(
      (d) => (d.manufacturer || "").toLowerCase() === "georide"
    );
    return {
      type: "custom:georide-card",
      device_id: devices[0]?.id || "",
    };
  }
}

customElements.define("georide-card", GeoRideCard);

// Register so Lovelace's card picker shows it.
window.customCards = window.customCards || [];
window.customCards.push({
  type: "georide-card",
  name: "GeoRide bike",
  description: "Compact card for a GeoRide tracker (map, lock, battery, last trip).",
});
