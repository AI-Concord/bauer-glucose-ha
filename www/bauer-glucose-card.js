/**
 * Bauer Glucose Card
 *
 * A Lovelace tile for a `bauer_glucose` sensor entity: big current-value
 * readout colored by range severity, trend arrow, an inline history graph
 * with insulin-dose markers, and quick buttons to log a new dose.
 *
 * YAML config:
 *   type: custom:bauer-glucose-card
 *   entity: sensor.bauers_glucose_monitor_glucose
 *   dose_entity: sensor.bauers_glucose_monitor_last_insulin_dose  # optional,
 *                                                                  # guessed from `entity` if omitted
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

const DOSE_COLORS = { long: "#3b82f6", short: "#f97316" };
const DOSE_LABEL = { long: "L", short: "S" };

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

const MIN_GAP_MS = 10 * 60 * 1000;

// Typical spacing between consecutive readings (median), so the gap threshold
// adapts to whatever resolution the API returns.
function medianSpacingMs(times) {
  const deltas = [];
  for (let i = 1; i < times.length; i++) deltas.push(times[i] - times[i - 1]);
  if (!deltas.length) return 0;
  deltas.sort((a, b) => a - b);
  return deltas[Math.floor(deltas.length / 2)];
}

// Split time-sorted points into runs with no missing-reading gap inside them,
// so a missed stretch is drawn as a break rather than a straight/flat line.
function splitSegments(points, gapMs) {
  const segments = [];
  let current = [];
  points.forEach((p, i) => {
    if (i > 0 && p.t - points[i - 1].t > gapMs) {
      segments.push(current);
      current = [];
    }
    current.push(p);
  });
  if (current.length) segments.push(current);
  return segments;
}

function guessDoseEntity(glucoseEntity) {
  if (!glucoseEntity) return null;
  if (glucoseEntity.includes("_glucose")) {
    return glucoseEntity.replace(/_glucose(?!_rate)/, "_last_insulin_dose");
  }
  return null;
}

class BauerGlucoseCard extends HTMLElement {
  setConfig(config) {
    if (!config.entity) {
      throw new Error("bauer-glucose-card: `entity` is required");
    }
    this._config = config;
    this._thresholds = { ...DEFAULT_THRESHOLDS, ...config };
    this._doseEntityId = config.dose_entity || guessDoseEntity(config.entity);
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
    return 5;
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
      canvas { display: block; width: 100%; height: 110px; }
      .legend { display: flex; gap: 14px; font-size: 0.7rem; color: var(--secondary-text-color); margin: 2px 0 10px; }
      .legend span { display: inline-flex; align-items: center; gap: 4px; }
      .swatch { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
      .empty { color: var(--secondary-text-color); font-size: 0.85rem; padding: 8px 0; }
      .dose-log {
        display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
        border-top: 1px solid var(--divider-color, #e0e0e0);
        padding-top: 10px; cursor: default;
      }
      .dose-log input {
        width: 56px; font-size: 0.9rem; padding: 4px 6px;
        border: 1px solid var(--divider-color, #ccc); border-radius: 6px;
        background: var(--card-background-color, #fff); color: var(--primary-text-color);
      }
      .dose-log button {
        font-size: 0.78rem; font-weight: 600; border: none; border-radius: 14px;
        padding: 6px 12px; cursor: pointer; color: white;
      }
      .dose-log button.long { background: ${DOSE_COLORS.long}; }
      .dose-log button.short { background: ${DOSE_COLORS.short}; }
      .dose-log button:active { filter: brightness(0.9); }
      .dose-log button:disabled { opacity: 0.6; cursor: default; }
      .dose-status {
        flex-basis: 100%; font-size: 0.8rem; min-height: 1.2em;
        color: var(--secondary-text-color);
      }
      .dose-status.ok { color: #2f9e5e; font-weight: 700; }
      .dose-status.error { color: #c0392b; font-weight: 700; }
      .dose-status.pending { font-style: italic; }
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
      <div class="legend">
        <span><i class="swatch" style="background:${DOSE_COLORS.long}"></i>Long-acting</span>
        <span><i class="swatch" style="background:${DOSE_COLORS.short}"></i>Short-acting</span>
      </div>
      <div class="dose-log">
        <input type="number" class="dose-units" step="0.25" min="0" value="0.5" inputmode="decimal" />
        <button class="long">+ Long</button>
        <button class="short">+ Short</button>
        <span class="dose-status"></span>
      </div>
    `;
    this._card.addEventListener("click", () => this._openMoreInfo());

    const doseLog = this._card.querySelector(".dose-log");
    doseLog.addEventListener("click", (e) => e.stopPropagation());
    this._card.querySelector("button.long").addEventListener("click", () => this._logDose("long"));
    this._card.querySelector("button.short").addEventListener("click", () => this._logDose("short"));

    this.shadowRoot.append(style, this._card);
  }

  _openMoreInfo() {
    if (!this._config?.entity) return;
    const event = new Event("hass-more-info", { bubbles: true, composed: true });
    event.detail = { entityId: this._config.entity };
    this.dispatchEvent(event);
  }

  // Transient message (pending/confirmation/error) shown in the dose row;
  // once it expires the row falls back to the persistent "last dose" line.
  _flashDoseStatus(text, kind, ms) {
    this._doseFlash = { text, kind, until: ms ? Date.now() + ms : Infinity };
    this._renderDoseStatus();
    clearTimeout(this._doseFlashTimer);
    if (ms) {
      this._doseFlashTimer = setTimeout(() => {
        this._doseFlash = null;
        this._renderDoseStatus();
      }, ms);
    }
  }

  _renderDoseStatus() {
    const statusEl = this._card.querySelector(".dose-status");
    const flash = this._doseFlash;
    if (flash && Date.now() < flash.until) {
      statusEl.textContent = flash.text;
      statusEl.className = `dose-status ${flash.kind}`;
      return;
    }
    const doseState = this._doseEntityId ? this._hass?.states[this._doseEntityId] : null;
    const attrs = doseState?.attributes || {};
    const hasDose = doseState && doseState.state !== "unknown" && doseState.state !== "unavailable";
    statusEl.className = "dose-status";
    if (!hasDose) {
      statusEl.textContent = "No insulin logged yet";
      return;
    }
    const dose = [`${doseState.state}u`, attrs.insulin_type && `${attrs.insulin_type}-acting`].filter(Boolean).join(" ");
    statusEl.textContent = `Last dose: ${dose} · ${relativeTime(attrs.timestamp)}`;
  }

  async _logDose(insulinType) {
    if (!this._doseEntityId || !this._hass.states[this._doseEntityId]) {
      this._flashDoseStatus("No dose sensor configured", "error", 6000);
      return;
    }
    const unitsInput = this._card.querySelector(".dose-units");
    const units = parseFloat(unitsInput.value);
    if (!Number.isFinite(units) || units <= 0) {
      this._flashDoseStatus("Enter units first", "error", 4000);
      return;
    }
    const buttons = this._card.querySelectorAll(".dose-log button");
    buttons.forEach((b) => (b.disabled = true));
    this._flashDoseStatus(`Logging ${units}u ${insulinType}…`, "pending", 0);
    try {
      await this._hass.callService("bauer_glucose", "log_dose", {
        entity_id: this._doseEntityId,
        insulin_type: insulinType,
        units,
      });
      const at = new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      this._flashDoseStatus(`✓ Logged ${units}u ${insulinType}-acting at ${at}`, "ok", 8000);
    } catch (err) {
      this._flashDoseStatus(`✗ Failed to log dose: ${err?.message || "unknown error"}`, "error", 10000);
    } finally {
      buttons.forEach((b) => (b.disabled = false));
    }
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
    const isStale = !!attrs.is_stale;
    // A stale reading is "no reading": don't color it or raise range/rapid
    // badges off an old value.
    const rangeState = isStale ? "unknown" : attrs.range_state || "unknown";
    const trend = isStale ? "unknown" : attrs.trend || "unknown";
    const isRapid = !isStale && !!attrs.is_rapid_change;
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
      badges.appendChild(this._badge("No reading available", "#6b7280"));
    }

    const doseState = this._doseEntityId ? this._hass.states[this._doseEntityId] : null;
    const doses = doseState?.attributes?.doses || [];

    this._renderDoseStatus();
    this._drawGraph(attrs.history || [], doses, color);
  }

  _badge(text, bg) {
    const el = document.createElement("span");
    el.className = "badge";
    el.style.background = bg;
    el.textContent = text;
    return el;
  }

  _drawGraph(history, doses, accent) {
    const canvas = this._card.querySelector("canvas");
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const width = Math.max(rect.width, 200);
    const height = 110;
    const topMargin = 16; // room for dose labels above the line
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    if (!history.length) return;

    const hours = this._config.hours || 3;
    const now = Date.now();
    const cutoff = now - hours * 3600 * 1000;
    const points = history
      .map((p) => ({ t: new Date(p.t).getTime(), v: p.mgdl }))
      .filter((p) => p.t >= cutoff)
      .sort((a, b) => a.t - b.t);
    if (points.length < 2) return;

    const values = points.map((p) => p.v);
    const th = this._thresholds;
    const minV = Math.min(...values, th.urgent_low) - 10;
    const maxV = Math.max(...values, th.urgent_high) + 10;
    // The time axis runs to "now" (not the last reading), so missing recent
    // data shows as empty space and doses logged since the last reading still
    // land on the graph.
    const minT = cutoff;
    const maxT = now;
    const gapMs = Math.max(2.5 * medianSpacingMs(points.map((p) => p.t)), MIN_GAP_MS);

    const x = (t) => ((t - minT) / Math.max(maxT - minT, 1)) * (width - 4) + 2;
    const y = (v) =>
      topMargin + (height - topMargin) - ((v - minV) / Math.max(maxV - minV, 1)) * (height - topMargin - 8) - 4;

    // Target-range band
    ctx.fillStyle = "rgba(47, 158, 94, 0.12)";
    ctx.fillRect(0, y(th.high), width, y(th.low) - y(th.high));

    // Insulin dose markers, within the same time window
    const doseMarkers = (doses || [])
      .map((d) => ({ t: new Date(d.t).getTime(), type: d.type, units: d.units }))
      .filter((d) => d.t >= minT && d.t <= maxT);
    doseMarkers.forEach((d) => {
      const px = x(d.t);
      const markerColor = DOSE_COLORS[d.type] || "#999";
      ctx.beginPath();
      ctx.setLineDash([3, 2]);
      ctx.strokeStyle = markerColor;
      ctx.lineWidth = 1.5;
      ctx.moveTo(px, topMargin);
      ctx.lineTo(px, height - 2);
      ctx.stroke();
      ctx.setLineDash([]);

      ctx.fillStyle = markerColor;
      ctx.font = "9px sans-serif";
      ctx.textAlign = "center";
      const label = `${DOSE_LABEL[d.type] || "?"}${d.units}`;
      ctx.fillText(label, px, topMargin - 4);
    });

    // Shade stretches with no reading (between readings, and up to now)
    ctx.fillStyle = "rgba(128, 128, 128, 0.15)";
    for (let i = 1; i < points.length; i++) {
      if (points[i].t - points[i - 1].t > gapMs) {
        ctx.fillRect(x(points[i - 1].t), topMargin, x(points[i].t) - x(points[i - 1].t), height - topMargin);
      }
    }
    const last = points[points.length - 1];
    const trailingGap = now - last.t > gapMs;
    if (trailingGap) {
      ctx.fillRect(x(last.t), topMargin, x(now) - x(last.t), height - topMargin);
      ctx.fillStyle = "#6b7280";
      ctx.font = "10px sans-serif";
      ctx.textAlign = "right";
      ctx.fillText("no reading", width - 6, topMargin + (height - topMargin) / 2);
    }

    // Glucose line, broken wherever readings are missing
    const lineColor = accent || COLORS.in_range;
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    splitSegments(points, gapMs).forEach((segment) => {
      if (segment.length === 1) {
        ctx.beginPath();
        ctx.arc(x(segment[0].t), y(segment[0].v), 2, 0, Math.PI * 2);
        ctx.fillStyle = lineColor;
        ctx.fill();
        return;
      }
      ctx.beginPath();
      segment.forEach((p, i) => {
        if (i === 0) ctx.moveTo(x(p.t), y(p.v));
        else ctx.lineTo(x(p.t), y(p.v));
      });
      ctx.stroke();
    });

    // Latest reading marker
    ctx.beginPath();
    ctx.arc(x(last.t), y(last.v), 3.5, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.fill();
  }
}

customElements.define("bauer-glucose-card", BauerGlucoseCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "bauer-glucose-card",
  name: "Bauer Glucose Card",
  description: "Current CGM reading, trend, dose-correlated history graph, and quick dose logging.",
});
