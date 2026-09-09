"""DataUpdateCoordinator for Bauer Glucose."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .alerts import RANGE_IN_RANGE, RANGE_UNKNOWN, GlucoseStatus, evaluate
from .api import GlucoseSnapshot, LibreLinkUpAuthError, LibreLinkUpClient, LibreLinkUpError
from .const import (
    ATTR_DIRECTION,
    ATTR_GLUCOSE_MGDL,
    ATTR_RATE_MGDL_MIN,
    ATTR_TIMESTAMP,
    ATTR_TREND,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_PATIENT_ID,
    CONF_PATIENT_NAME,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_RAPID_CHANGE,
    EVENT_URGENT_RANGE,
)

_LOGGER = logging.getLogger(__name__)

# While an urgent condition (rapid change or urgent-range) persists, re-fire
# the event this often so automations can re-announce "still needs checking"
# rather than announcing once and going silent.
ALERT_REPEAT_INTERVAL = timedelta(minutes=10)


class BauerGlucoseCoordinator(DataUpdateCoordinator[GlucoseSnapshot]):
    """Polls LibreLinkUp for the configured patient and hands out snapshots."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        self._entry = entry
        self._client = LibreLinkUpClient(
            session=hass.helpers.aiohttp_client.async_get_clientsession(),
            email=entry.data[CONF_EMAIL],
            password=entry.data[CONF_PASSWORD],
            region=entry.data[CONF_REGION],
        )
        self._patient_id = entry.data[CONF_PATIENT_ID]
        self._patient_name = entry.data.get(CONF_PATIENT_NAME, "Bauer")
        self._logged_in = False

        self.status: GlucoseStatus | None = None
        self._last_rapid_direction: str | None = None
        self._last_range_state: str | None = None
        self._last_alert_fired_at: dict[str, datetime] = {}

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

    def _should_fire(self, key: str, now: datetime) -> bool:
        last = self._last_alert_fired_at.get(key)
        if last is None or (now - last) >= ALERT_REPEAT_INTERVAL:
            self._last_alert_fired_at[key] = now
            return True
        return False

    def _fire_alert_events(self) -> None:
        """Edge-triggered on entry, then repeated periodically while it persists."""
        status = self.status
        if status is None or status.timestamp is None:
            return
        now = status.timestamp

        if status.is_rapid_change:
            is_new = status.rapid_direction != self._last_rapid_direction
            if is_new or self._should_fire("rapid_change", now):
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
            is_new = status.range_state != self._last_range_state
            if is_new or self._should_fire("urgent_range", now):
                self.hass.bus.async_fire(
                    EVENT_URGENT_RANGE,
                    {
                        "patient_name": self._patient_name,
                        "range_state": status.range_state,
                        ATTR_DIRECTION: "low" if status.range_state == "urgent_low" else "high",
                        ATTR_GLUCOSE_MGDL: status.mgdl,
                        ATTR_TREND: status.trend,
                        ATTR_TIMESTAMP: status.timestamp.isoformat(),
                        "is_new": is_new,
                    },
                )
        self._last_range_state = status.range_state
