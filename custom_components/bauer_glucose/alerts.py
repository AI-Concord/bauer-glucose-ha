"""Pure logic for turning a glucose snapshot into an alert-relevant status.

Kept separate from the coordinator/entities so the thresholds and rate math
can be unit tested without touching Home Assistant or the network.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .api import GlucoseSnapshot
from .const import (
    CONF_HIGH_THRESHOLD,
    CONF_LOW_THRESHOLD,
    CONF_RAPID_CHANGE_RATE,
    CONF_STALE_MINUTES,
    CONF_URGENT_HIGH_THRESHOLD,
    CONF_URGENT_LOW_THRESHOLD,
    DEFAULT_HIGH_THRESHOLD,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_RAPID_CHANGE_RATE,
    DEFAULT_STALE_MINUTES,
    DEFAULT_URGENT_HIGH_THRESHOLD,
    DEFAULT_URGENT_LOW_THRESHOLD,
)

RANGE_URGENT_LOW = "urgent_low"
RANGE_LOW = "low"
RANGE_IN_RANGE = "in_range"
RANGE_HIGH = "high"
RANGE_URGENT_HIGH = "urgent_high"
RANGE_UNKNOWN = "unknown"


@dataclass
class GlucoseStatus:
    mgdl: float | None
    trend: str
    timestamp: datetime | None
    rate_mgdl_per_min: float | None
    is_stale: bool
    is_rapid_change: bool
    rapid_direction: str | None  # "low" or "high"
    range_state: str


def _thresholds(options: dict) -> dict[str, float]:
    return {
        "low": options.get(CONF_LOW_THRESHOLD, DEFAULT_LOW_THRESHOLD),
        "high": options.get(CONF_HIGH_THRESHOLD, DEFAULT_HIGH_THRESHOLD),
        "urgent_low": options.get(CONF_URGENT_LOW_THRESHOLD, DEFAULT_URGENT_LOW_THRESHOLD),
        "urgent_high": options.get(CONF_URGENT_HIGH_THRESHOLD, DEFAULT_URGENT_HIGH_THRESHOLD),
        "rapid_rate": options.get(CONF_RAPID_CHANGE_RATE, DEFAULT_RAPID_CHANGE_RATE),
        "stale_minutes": options.get(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES),
    }


def _compute_rate(snapshot: GlucoseSnapshot) -> float | None:
    """mg/dL per minute, from the two most recent readings."""
    points = sorted(snapshot.history, key=lambda r: r.timestamp)
    if snapshot.current is not None:
        points = [p for p in points if p.timestamp != snapshot.current.timestamp]
        points.append(snapshot.current)
    if len(points) < 2:
        return None
    newer, older = points[-1], points[-2]
    delta_minutes = (newer.timestamp - older.timestamp).total_seconds() / 60
    if delta_minutes <= 0:
        return None
    return (newer.mgdl - older.mgdl) / delta_minutes


def _range_state(mgdl: float, thresholds: dict[str, float]) -> str:
    if mgdl <= thresholds["urgent_low"]:
        return RANGE_URGENT_LOW
    if mgdl <= thresholds["low"]:
        return RANGE_LOW
    if mgdl >= thresholds["urgent_high"]:
        return RANGE_URGENT_HIGH
    if mgdl >= thresholds["high"]:
        return RANGE_HIGH
    return RANGE_IN_RANGE


def evaluate(snapshot: GlucoseSnapshot, options: dict, now: datetime | None = None) -> GlucoseStatus:
    now = now or datetime.now(timezone.utc)
    thresholds = _thresholds(options)

    if snapshot.current is None:
        return GlucoseStatus(
            mgdl=None,
            trend="unknown",
            timestamp=None,
            rate_mgdl_per_min=None,
            is_stale=True,
            is_rapid_change=False,
            rapid_direction=None,
            range_state=RANGE_UNKNOWN,
        )

    age_minutes = (now - snapshot.current.timestamp).total_seconds() / 60
    is_stale = age_minutes > thresholds["stale_minutes"]

    rate = _compute_rate(snapshot)
    is_rapid = rate is not None and abs(rate) >= thresholds["rapid_rate"]
    direction = None
    if is_rapid:
        direction = "low" if rate < 0 else "high"

    return GlucoseStatus(
        mgdl=snapshot.current.mgdl,
        trend=snapshot.current.trend,
        timestamp=snapshot.current.timestamp,
        rate_mgdl_per_min=rate,
        is_stale=is_stale,
        is_rapid_change=is_rapid,
        rapid_direction=direction,
        range_state=_range_state(snapshot.current.mgdl, thresholds),
    )
