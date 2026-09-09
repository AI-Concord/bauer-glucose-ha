"""Binary sensors for Bauer Glucose (LibreLinkUp)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PATIENT_ID, DOMAIN
from .coordinator import BauerGlucoseCoordinator
from .sensor import _device_info


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: BauerGlucoseCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            RapidChangeBinarySensor(coordinator, entry),
            OutOfRangeBinarySensor(coordinator, entry),
            UrgentRangeBinarySensor(coordinator, entry),
            StaleReadingBinarySensor(coordinator, entry),
        ]
    )


class _BaseBinarySensor(CoordinatorEntity[BauerGlucoseCoordinator], BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: BauerGlucoseCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.data[CONF_PATIENT_ID]}_{key}"
        self._attr_device_info = _device_info(entry)


class RapidChangeBinarySensor(_BaseBinarySensor):
    """On while glucose is changing faster than the configured rate threshold."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "rapid_change"
    _attr_icon = "mdi:speedometer-slow"

    def __init__(self, coordinator: BauerGlucoseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "rapid_change")

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.status
        return status.is_rapid_change if status else None

    @property
    def extra_state_attributes(self) -> dict:
        status = self.coordinator.status
        if not status:
            return {}
        return {"direction": status.rapid_direction, "rate_mgdl_per_min": status.rate_mgdl_per_min}


class OutOfRangeBinarySensor(_BaseBinarySensor):
    """On whenever glucose is outside the low/high target band (any severity)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "out_of_range"
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator: BauerGlucoseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "out_of_range")

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.status
        if not status:
            return None
        return status.range_state not in ("in_range", "unknown")

    @property
    def extra_state_attributes(self) -> dict:
        status = self.coordinator.status
        return {"range_state": status.range_state} if status else {}


class UrgentRangeBinarySensor(_BaseBinarySensor):
    """On only for urgent-low / urgent-high — the 'check insulin now' condition."""

    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_translation_key = "urgent_range"
    _attr_icon = "mdi:alert-decagram"

    def __init__(self, coordinator: BauerGlucoseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "urgent_range")

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.status
        if not status:
            return None
        return status.range_state in ("urgent_low", "urgent_high")

    @property
    def extra_state_attributes(self) -> dict:
        status = self.coordinator.status
        return {"range_state": status.range_state} if status else {}


class StaleReadingBinarySensor(_BaseBinarySensor):
    """On when no fresh reading has arrived recently (sensor fell off / app not syncing)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_translation_key = "stale_reading"
    _attr_icon = "mdi:wifi-off"
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: BauerGlucoseCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "stale_reading")

    @property
    def is_on(self) -> bool | None:
        status = self.coordinator.status
        return status.is_stale if status else None
