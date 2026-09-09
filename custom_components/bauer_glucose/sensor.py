"""Sensors for Bauer Glucose (LibreLinkUp)."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DIRECTION,
    ATTR_RATE_MGDL_MIN,
    ATTR_TIMESTAMP,
    ATTR_TREND,
    CONF_PATIENT_ID,
    CONF_PATIENT_NAME,
    DOMAIN,
    TREND_ARROW_ICON,
)
from .coordinator import BauerGlucoseCoordinator

MAX_HISTORY_POINTS = 288  # ~24h at one reading per 5 minutes


MAX_DOSE_POINTS = 100


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: BauerGlucoseCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            GlucoseSensor(coordinator, entry),
            GlucoseRateSensor(coordinator, entry),
            LastInsulinDoseSensor(coordinator, entry),
        ]
    )


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    name = entry.data.get(CONF_PATIENT_NAME, "Bauer")
    return DeviceInfo(
        identifiers={(DOMAIN, entry.data[CONF_PATIENT_ID])},
        name=f"{name}'s Glucose Monitor",
        manufacturer="Abbott (LibreLinkUp, unofficial)",
        model="FreeStyle Libre",
    )


class GlucoseSensor(CoordinatorEntity[BauerGlucoseCoordinator], SensorEntity):
    """Current glucose reading, mg/dL, with trend/rate/history as attributes."""

    _attr_native_unit_of_measurement = "mg/dL"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_translation_key = "glucose"

    def __init__(self, coordinator: BauerGlucoseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.data[CONF_PATIENT_ID]}_glucose"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        status = self.coordinator.status
        return status.mgdl if status else None

    @property
    def icon(self) -> str:
        status = self.coordinator.status
        trend = status.trend if status else "unknown"
        return TREND_ARROW_ICON.get(trend, TREND_ARROW_ICON["unknown"])

    @property
    def available(self) -> bool:
        status = self.coordinator.status
        return super().available and status is not None and status.mgdl is not None

    @property
    def extra_state_attributes(self) -> dict:
        status = self.coordinator.status
        snapshot = self.coordinator.data
        if status is None:
            return {}

        history = sorted(snapshot.history, key=lambda r: r.timestamp)[-MAX_HISTORY_POINTS:]

        return {
            ATTR_TREND: status.trend,
            ATTR_RATE_MGDL_MIN: round(status.rate_mgdl_per_min, 2) if status.rate_mgdl_per_min is not None else None,
            ATTR_TIMESTAMP: status.timestamp.isoformat() if status.timestamp else None,
            "range_state": status.range_state,
            "is_stale": status.is_stale,
            "is_rapid_change": status.is_rapid_change,
            ATTR_DIRECTION: status.rapid_direction,
            "history": [
                {"t": r.timestamp.isoformat(), "mgdl": r.mgdl} for r in history
            ],
        }


class GlucoseRateSensor(CoordinatorEntity[BauerGlucoseCoordinator], SensorEntity):
    """Rate of change, mg/dL per minute. Diagnostic entity used by graphs/automations."""

    _attr_native_unit_of_measurement = "mg/dL/min"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "glucose_rate"
    _attr_icon = "mdi:chart-line-variant"

    def __init__(self, coordinator: BauerGlucoseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_PATIENT_ID]}_glucose_rate"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        status = self.coordinator.status
        if status is None or status.rate_mgdl_per_min is None:
            return None
        return round(status.rate_mgdl_per_min, 2)


class LastInsulinDoseSensor(CoordinatorEntity[BauerGlucoseCoordinator], SensorEntity):
    """Last logged insulin dose, with the recent dose log as an attribute.

    Updated by the ``bauer_glucose.log_dose`` service rather than the
    glucose poll, via ``coordinator.async_update_listeners()`` — so this
    entity reflects a new dose immediately, not on the next ~60s poll.
    """

    _attr_native_unit_of_measurement = "U"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True
    _attr_translation_key = "last_insulin_dose"
    _attr_icon = "mdi:needle"

    def __init__(self, coordinator: BauerGlucoseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_PATIENT_ID]}_last_insulin_dose"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> float | None:
        last = self.coordinator.dose_store.last_dose
        return last.units if last else None

    @property
    def extra_state_attributes(self) -> dict:
        last = self.coordinator.dose_store.last_dose
        recent = sorted(self.coordinator.dose_store.doses, key=lambda d: d.timestamp)[-MAX_DOSE_POINTS:]
        return {
            "insulin_type": last.insulin_type if last else None,
            "note": last.note if last else None,
            ATTR_TIMESTAMP: last.timestamp.isoformat() if last else None,
            "doses": [
                {"t": d.timestamp.isoformat(), "type": d.insulin_type, "units": d.units, "note": d.note}
                for d in recent
            ],
        }
