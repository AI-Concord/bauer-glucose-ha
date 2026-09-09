"""Bauer Glucose (LibreLinkUp) integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_INSULIN_TYPE,
    ATTR_NOTE,
    ATTR_UNITS,
    DOMAIN,
    INSULIN_TYPES,
    PLATFORMS,
    SERVICE_LOG_DOSE,
)
from .coordinator import BauerGlucoseCoordinator

LOG_DOSE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): vol.All(cv.ensure_list, [cv.entity_id]),
        vol.Required(ATTR_INSULIN_TYPE): vol.In(INSULIN_TYPES),
        vol.Required(ATTR_UNITS): vol.Coerce(float),
        vol.Optional(ATTR_NOTE): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = BauerGlucoseCoordinator(hass, entry)
    await coordinator.dose_store.async_load()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_LOG_DOSE):
        return

    async def _async_handle_log_dose(call: ServiceCall) -> None:
        ent_reg = er.async_get(hass)
        entry_ids: set[str] = set()
        for entity_id in call.data["entity_id"]:
            entity = ent_reg.async_get(entity_id)
            if entity and entity.config_entry_id:
                entry_ids.add(entity.config_entry_id)

        if not entry_ids:
            raise ServiceValidationError(
                "No Bauer Glucose entity found in the service target"
            )

        for entry_id in entry_ids:
            coordinator: BauerGlucoseCoordinator | None = hass.data.get(DOMAIN, {}).get(entry_id)
            if coordinator is None:
                continue
            await coordinator.dose_store.async_add_dose(
                insulin_type=call.data[ATTR_INSULIN_TYPE],
                units=call.data[ATTR_UNITS],
                note=call.data.get(ATTR_NOTE),
            )
            coordinator.async_update_listeners()

    hass.services.async_register(
        DOMAIN, SERVICE_LOG_DOSE, _async_handle_log_dose, schema=LOG_DOSE_SCHEMA
    )
