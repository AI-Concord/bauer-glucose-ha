/**
 * Bauer Glucose Card
 *
 * A Lovelace tile for a `bauer_glucose` sensor entity: big current-value
 * readout colored by range severity, trend arrow, and an inline history
 * graph rendered from the sensor's `history` attribute.
 *
 * YAML config:
 *   type: custom:bauer-glucose-card
 *   entity: sensor.bauers_glucose_monitor_glucose
 *   name: Bauer                 # optional, defaults to entity friendly name
 *   hours: 3                    # optional, how much history to graph (default 3)
 *   urgent_low: 60               # optional coloring overrides; falls back to
 *   low: 80                      # entity attributes / integration defaults
 *   high: 250
 *   urgent_high: 350
 */

const DEFAULT_THRESHOLDS = { urgent_low: 60, low: 80, high: 250, urgent_high: 350 };

const COLORS = {
  urgent_low: "#c0392b",
  low: "#d68910",
  in_range: "#2f9e5e",
  high: "#d68910",
  urgent_high: "#c0392b",
  unknown: "#8a8f98",
};

function rangeColor(rangeState) {
  return COLORS[rangeState] || COLORS.unknown;
}

function trendGlyph(trend) {
  switch (trend) {
    case "falling_quickly":
      return "↓↓";
    case "falling":
      return "↘";
    case "stable":
      return "→";
    case "rising":
      return "↗";
    case "rising_quickly":
      return "↑↑";
    default:
      return "?";
  }
}

function relativeTime(isoString) {
  if (!isoString) return "no data";
  const ts = new Date(isoString).getTime();
  const diffMin = Math.round((Date.now() - ts) / 60000);
  if (diffMin <= 0) return "just now";
  if (diffMin === 1) return "1 min ago";
  if (diffMin < 60) return `${diffMin} min ago`;
  const hrs = Math.floor(diffMin / 60);
  return `${hrs}h ${diffMin % 60}m ago`;
}

class BauerGlucoseCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) {
      throw new Error("bauer-glucose-card: `entity` is required");
    }
    this._config = config;
    this._thresholds = { ...DEFAULT_THRESHOLDS, ...config };
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this._build();
    }
  }

  set hass(hass) {
    this._hass = hass;
    const stateObj = hass.states[this._config.entity];
    if (!stateObj) {
      this._renderMissing();
      return;
    }
    this._render(stateObj);
  }

  getCardSize() {
    return 4;
  }

  static getStubConfig(hass) {
    const glucoseEntity = Object.keys(hass.states).find((e) =>
      e.startsWith("sensor.") && hass.states[e].attributes?.range_state !== undefined
    );
    return { type: "custom:bauer-glucose-card", entity: glucoseEntity || "sensor.bauer_glucose" };
  }

  _build() {
    const style = document.createElement("style");
    style.textContent = `
      :host { display: block; }
      ha-card {
        padding: 16px;
        cursor: pointer;
        overflow: hidden;
      }
      .header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        margin-bottom: 4px;
      }
      .name { font-size: 0.95rem; font-weight: 600; color: var(--primary-text-color); }
      .updated { font-size: 0.75rem; color: var(--secondary-text-color); }
      .readout { display: flex; align-items: baseline; gap: 10px; margin: 4px 0 10px; }
      .value { font-size: 2.6rem; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; }
      .unit { font-size: 0.95rem; color: var(--secondary-text-color); }
      .trend { font-size: 1.6rem; margin-left: auto; }
      .badges { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
      .badge {
        font-size: 0.7rem; font-weight: 700; letter-spacing: 0.03em; text-transform: uppercase;
        padding: 2px 8px; border-radius: 10px; color: white;
      }
      canvas { display: block; width: 100%; height: 90px; }
      .empty { color: var(--secondary-text-color); font-size: 0.85rem; padding: 8px 0; }
    `;
    this._card = document.createElement("ha-card");
    this._card.innerHTML = `
      <div class="header">
        <span class="name"></span>
        <span class="updated"></span>
      </div>
      <div class="badges"></div>
      <div class="readout">
        <span class="value">--</span>
        <span class="unit">mg/dL</span>
        <span class="trend"></span>
      </div>
      <canvas></canvas>
    `;
    this._card.addEventListener("click", () => this._openMoreInfo());
    this.shadowRoot.append(style, this._card);
  }

  _openMoreInfo() {
    if (!this._config?.entity) return;
    const event = new Event("hass-more-info", { bubbles: true, composed: true });
    event.detail = { entityId: this._config.entity };
    this.dispatchEvent(event);
  }

  _renderMissing() {
    this._card.querySelector(".name").textContent = this._config.entity;
    this._card.querySelector(".value").textContent = "--";
    this._card.querySelector(".empty")?.remove();
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Entity not found";
    this._card.appendChild(empty);
  }

  _render(stateObj) {
    const attrs = stateObj.attributes || {};
    const name = this._config.name || attrs.friendly_name || this._config.entity;
    const rangeState = attrs.range_state || "unknown";
    const trend = attrs.trend || "unknown";
    const isStale = !!attrs.is_stale;
    const isRapid = !!attrs.is_rapid_change;
    const value = stateObj.state;
    const color = rangeColor(rangeState);

    this._card.style.setProperty("--card-accent", color);
    this._card.querySelector(".name").textContent = name;
    this._card.querySelector(".updated").textContent = relativeTime(attrs.timestamp);

    const valueEl = this._card.querySelector(".value");
    valueEl.textContent = value === "unknown" || value === "unavailable" ? "--" : value;
    valueEl.style.color = color;

    this._card.querySelector(".trend").textContent = trendGlyph(trend);

    const badges = this._card.querySelector(".badges");
    badges.innerHTML = "";
    if (rangeState === "urgent_low" || rangeState === "urgent_high") {
      badges.appendChild(this._badge("Check insulin now", "#c0392b"));
    } else if (rangeState === "low" || rangeState === "high") {
      badges.appendChild(this._badge(rangeState === "low" ? "Low" : "High", "#d68910"));
    }
    if (isRapid) {
      const dir = attrs.direction === "low" ? "Dropping fast" : "Rising fast";
      badges.appendChild(this._badge(dir, "#a04ec9"));
    }
    if (isStale) {
      badges.appendChild(this._badge("No recent data", "#6b7280"));
    }

    this._drawGraph(attrs.history || []);
  }

  _badge(text, bg) {
    const el = document.createElement("span");
    el.className = "badge";
    el.style.background = bg;
    el.textContent = text;
    return el;
  }

  _drawGraph(history) {
    const canvas = this._card.querySelector("canvas");
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(rect.width, 200);
    const height = 90;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    if (!history.length) return;

    const hours = this._config.hours || 3;
    const cutoff = Date.now() - hours * 3600 * 1000;
    const points = history
      .map((p) => ({ t: new Date(p.t).getTime(), v: p.mgdl }))
      .filter((p) => p.t >= cutoff)
      .sort((a, b) => a.t - b.t);
    if (points.length < 2) return;

    const values = points.map((p) => p.v);
    const th = this._thresholds;
    const minV = Math.min(...values, th.urgent_low) - 10;
    const maxV = Math.max(...values, th.urgent_high) + 10;
    const minT = points[0].t;
    const maxT = points[points.length - 1].t;

    const x = (t) => ((t - minT) / Math.max(maxT - minT, 1)) * (width - 4) + 2;
    const y = (v) => height - ((v - minV) / Math.max(maxV - minV, 1)) * (height - 8) - 4;

    // Target-range band
    ctx.fillStyle = "rgba(47, 158, 94, 0.12)";
    ctx.fillRect(0, y(th.high), width, y(th.low) - y(th.high));

    // Line
    ctx.beginPath();
    points.forEach((p, i) => {
      const px = x(p.t);
      const py = y(p.v);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    });
    ctx.strokeStyle = "var(--card-accent, #2f9e5e)";
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.stroke();

    // Latest point marker
    const last = points[points.length - 1];
    ctx.beginPath();
    ctx.arc(x(last.t), y(last.v), 3.5, 0, Math.PI * 2);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.fill();
  }
}

customElements.define("bauer-glucose-card", BauerGlucoseCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "bauer-glucose-card",
  name: "Bauer Glucose Card",
  description: "Current CGM reading, trend, and history graph for Bauer's glucose sensor.",
});
