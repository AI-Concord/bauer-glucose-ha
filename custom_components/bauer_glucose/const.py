"""Constants for the Bauer Glucose (LibreLinkUp) integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "bauer_glucose"
PLATFORMS = ["sensor", "binary_sensor"]

# --- Config entry keys ---
CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_REGION = "region"
CONF_PATIENT_ID = "patient_id"
CONF_PATIENT_NAME = "patient_name"

# --- Options keys (tunable after setup) ---
CONF_LOW_THRESHOLD = "low_threshold"
CONF_HIGH_THRESHOLD = "high_threshold"
CONF_URGENT_LOW_THRESHOLD = "urgent_low_threshold"
CONF_URGENT_HIGH_THRESHOLD = "urgent_high_threshold"
CONF_RAPID_CHANGE_RATE = "rapid_change_rate"  # mg/dL per minute
CONF_STALE_MINUTES = "stale_minutes"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_LOW_ALERT_REPEAT_MINUTES = "low_alert_repeat_minutes"
CONF_HIGH_ALERT_REPEAT_MINUTES = "high_alert_repeat_minutes"

# Defaults are ballpark figures for a diabetic cat and MUST be confirmed with
# a veterinarian before being relied on for dosing decisions. They exist so
# the integration is usable out of the box, not as medical guidance.
DEFAULT_LOW_THRESHOLD = 80  # mg/dL
DEFAULT_HIGH_THRESHOLD = 250  # mg/dL
DEFAULT_URGENT_LOW_THRESHOLD = 60  # mg/dL
DEFAULT_URGENT_HIGH_THRESHOLD = 350  # mg/dL
DEFAULT_RAPID_CHANGE_RATE = 4  # mg/dL per minute sustained
DEFAULT_STALE_MINUTES = 20  # no new reading in this long -> sensor data considered stale
DEFAULT_SCAN_INTERVAL = 60  # seconds; LibreLinkUp/sensor data itself only updates ~every 60s
DEFAULT_LOW_ALERT_REPEAT_MINUTES = 10  # how often to re-announce/re-fire while low/urgent-low persists
DEFAULT_HIGH_ALERT_REPEAT_MINUTES = 10  # same, while high/urgent-high persists

MIN_SCAN_INTERVAL = 60  # LibreLinkUp will start rejecting/throttling faster polling
MIN_ALERT_REPEAT_MINUTES = 1
MAX_ALERT_REPEAT_MINUTES = 60

SCAN_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

# LibreView regions -> API host. "US" (global default host, no prefix) kept first.
REGION_HOSTS = {
    "us": "api-us.libreview.io",
    "eu": "api-eu.libreview.io",
    "eu2": "api-eu2.libreview.io",
    "de": "api-de.libreview.io",
    "fr": "api-fr.libreview.io",
    "jp": "api-jp.libreview.io",
    "ap": "api-ap.libreview.io",
    "au": "api-au.libreview.io",
    "ae": "api-ae.libreview.io",
    "ca": "api-ca.libreview.io",
    "la": "api-la.libreview.io",
    "ru": "api.libreview.ru",
}
DEFAULT_REGION = "us"

# TrendArrow enum returned by LibreLinkUp for the most recent measurement.
TREND_ARROW_MAP = {
    1: "falling_quickly",
    2: "falling",
    3: "stable",
    4: "rising",
    5: "rising_quickly",
}

TREND_ARROW_ICON = {
    "falling_quickly": "mdi:arrow-down-bold",
    "falling": "mdi:arrow-bottom-right",
    "stable": "mdi:arrow-right",
    "rising": "mdi:arrow-top-right",
    "rising_quickly": "mdi:arrow-up-bold",
    "unknown": "mdi:help",
}

# Signal dispatched to entities when the coordinator has fresh data.
SIGNAL_UPDATE = f"{DOMAIN}_update"

EVENT_RAPID_CHANGE = f"{DOMAIN}_rapid_change"
EVENT_URGENT_RANGE = f"{DOMAIN}_urgent_range"
EVENT_DOSE_LOGGED = f"{DOMAIN}_dose_logged"

ATTR_GLUCOSE_MGDL = "glucose_mgdl"
ATTR_TREND = "trend"
ATTR_RATE_MGDL_MIN = "rate_mgdl_per_min"
ATTR_TIMESTAMP = "timestamp"
ATTR_DIRECTION = "direction"  # "low" or "high", used on rapid-change event

# --- Insulin dose logging ---
SERVICE_LOG_DOSE = "log_dose"
ATTR_INSULIN_TYPE = "insulin_type"
ATTR_UNITS = "units"
ATTR_NOTE = "note"
INSULIN_TYPE_LONG = "long"
INSULIN_TYPE_SHORT = "short"
INSULIN_TYPES = [INSULIN_TYPE_LONG, INSULIN_TYPE_SHORT]
MAX_STORED_DOSES = 500
