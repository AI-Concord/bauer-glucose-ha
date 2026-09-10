"""DataUpdateCoordinator for Bauer Glucose."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .alerts import GlucoseStatus, evaluate
from .api import GlucoseSnapshot, LibreLinkUpAuthError, LibreLinkUpClient, LibreLinkUpError
from .dose_store import DoseStore
from .const import (
    ATTR_DIRECTION,
    ATTR_GLUCOSE_MGDL,
    ATTR_RATE_MGDL_MIN,
    ATTR_TIMESTAMP,
    ATTR_TREND,
    CONF_DOSE_SNOOZE_MINUTES,
    CONF_EMAIL,
    CONF_HIGH_ALERT_REPEAT_MINUTES,
    CONF_LOW_ALERT_REPEAT_MINUTES,
    CONF_PASSWORD,
    CONF_PATIENT_ID,
    CONF_PATIENT_NAME,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    DEFAULT_DOSE_SNOOZE_MINUTES,
    DEFAULT_HIGH_ALERT_REPEAT_MINUTES,
    DEFAULT_LOW_ALERT_REPEAT_MINUTES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_RAPID_CHANGE,
    EVENT_URGENT_RANGE,
)

_LOGGER = logging.getLogger(__name__)


class BauerGlucoseCoordinator(DataUpdateCoordinator[GlucoseSnapshot]):
    """Polls LibreLinkUp for the configured patient and hands out snapshots."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self._entry = entry
        self._client = LibreLinkUpClient(
            session=async_get_clientsession(hass),
            email=entry.data[CONF_EMAIL],
            password=entry.data[CONF_PASSWORD],
            region=entry.data[CONF_REGION],
        )
        self._patient_id = entry.data[CONF_PATIENT_ID]
        self._patient_name = entry.data.get(CONF_PATIENT_NAME, "Bauer")
        self._logged_in = False

        self.dose_store = DoseStore(hass, entry.entry_id)
        self.status: GlucoseStatus | None = None
        self._last_rapid_direction: str | None = None
        self._last_range_state: str | None = None
        self._last_alert_fired_at: dict[str, datetime] = {}
        self._high_snooze_until: datetime | None = None

        scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )

    @property
    def client(self) -> LibreLinkUpClient:
        return self._client

    @property
    def high_snooze_until(self) -> datetime | None:
        return self._high_snooze_until

    def snooze_high_alerts(self) -> None:
        """Hold off repeat HIGH-direction announcements after a correction dose.

        Only ever suppresses *repeats* of an already-announced HIGH episode —
        never the first announcement, never anything on the LOW side (you
        don't dose insulin for a low), and never a fresh escalation (a new
        rapid-change or range episode is edge-triggered and bypasses this).
        """
        minutes = self._entry.options.get(CONF_DOSE_SNOOZE_MINUTES, DEFAULT_DOSE_SNOOZE_MINUTES)
        if minutes <= 0:
            self._high_snooze_until = None
            return
        self._high_snooze_until = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    def _is_high_snoozed(self, now: datetime) -> bool:
        return self._high_snooze_until is not None and now < self._high_snooze_until

    async def _async_update_data(self) -> GlucoseSnapshot:
        try:
            if not self._logged_in:
                await self._client.async_login()
                self._logged_in = True
            try:
                snapshot = await self._client.async_get_snapshot(self._patient_id)
            except LibreLinkUpAuthError:
                # Session expired mid-flight; re-login once and retry.
                await self._client.async_login()
                snapshot = await self._client.async_get_snapshot(self._patient_id)
        except LibreLinkUpAuthError as err:
            self._logged_in = False
            raise UpdateFailed(f"Authentication with LibreLinkUp failed: {err}") from err
        except (LibreLinkUpError, aiohttp.ClientError) as err:
            raise UpdateFailed(f"Error communicating with LibreLinkUp: {err}") from err

        self.status = evaluate(snapshot, dict(self._entry.options))
        self._fire_alert_events()
        return snapshot

    def _repeat_interval(self, direction: str | None) -> timedelta:
        """Low/high each get their own configurable re-announce cadence."""
        options = self._entry.options
        if direction == "low":
            minutes = options.get(CONF_LOW_ALERT_REPEAT_MINUTES, DEFAULT_LOW_ALERT_REPEAT_MINUTES)
        else:
            minutes = options.get(CONF_HIGH_ALERT_REPEAT_MINUTES, DEFAULT_HIGH_ALERT_REPEAT_MINUTES)
        return timedelta(minutes=minutes)

    def _should_fire(self, key: str, now: datetime, direction: str | None) -> bool:
        last = self._last_alert_fired_at.get(key)
        if last is None or (now - last) >= self._repeat_interval(direction):
            self._last_alert_fired_at[key] = now
            return True
        return False

    def _fire_alert_events(self) -> None:
        """Edge-triggered on entry, then repeated periodically while it persists.

        The repeat cadence is direction-specific (a separate slider each for
        "low" and "high" in the integration's Options), so a keyed
        last-fired timestamp is tracked per direction, not just per event
        type — otherwise switching direction mid-episode would inherit the
        wrong interval's clock.
        """
        status = self.status
        if status is None or status.timestamp is None:
            return
        now = status.timestamp

        if status.is_rapid_change:
            is_new = status.rapid_direction != self._last_rapid_direction
            fire_key = f"rapid_change_{status.rapid_direction}"
            snoozed = status.rapid_direction == "high" and not is_new and self._is_high_snoozed(now)
            if not snoozed and (is_new or self._should_fire(fire_key, now, status.rapid_direction)):
                self.hass.bus.async_fire(
                    EVENT_RAPID_CHANGE,
                    {
                        "patient_name": self._patient_name,
                        ATTR_DIRECTION: status.rapid_direction,
                        ATTR_GLUCOSE_MGDL: status.mgdl,
                        ATTR_RATE_MGDL_MIN: status.rate_mgdl_per_min,
                        ATTR_TREND: status.trend,
                        ATTR_TIMESTAMP: status.timestamp.isoformat(),
                        "is_new": is_new,
                    },
                )
        self._last_rapid_direction = status.rapid_direction if status.is_rapid_change else None

        urgent = status.range_state in ("urgent_low", "urgent_high")
        if urgent:
            urgent_direction = "low" if status.range_state == "urgent_low" else "high"
            is_new = status.range_state != self._last_range_state
            fire_key = f"urgent_range_{urgent_direction}"
            snoozed = urgent_direction == "high" and not is_new and self._is_high_snoozed(now)
            if not snoozed and (is_new or self._should_fire(fire_key, now, urgent_direction)):
                self.hass.bus.async_fire(
                    EVENT_URGENT_RANGE,
                    {
                        "patient_name": self._patient_name,
                        "range_state": status.range_state,
                        ATTR_DIRECTION: urgent_direction,
                        ATTR_GLUCOSE_MGDL: status.mgdl,
                        ATTR_TREND: status.trend,
                        ATTR_TIMESTAMP: status.timestamp.isoformat(),
                        "is_new": is_new,
                    },
                )
        self._last_range_state = status.range_state
