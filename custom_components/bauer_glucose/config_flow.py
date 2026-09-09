"""Config flow for Bauer Glucose (LibreLinkUp)."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import LibreLinkUpAuthError, LibreLinkUpClient, LibreLinkUpError
from .const import (
    CONF_EMAIL,
    CONF_HIGH_ALERT_REPEAT_MINUTES,
    CONF_HIGH_THRESHOLD,
    CONF_LOW_ALERT_REPEAT_MINUTES,
    CONF_LOW_THRESHOLD,
    CONF_PASSWORD,
    CONF_PATIENT_ID,
    CONF_PATIENT_NAME,
    CONF_RAPID_CHANGE_RATE,
    CONF_REGION,
    CONF_SCAN_INTERVAL,
    CONF_STALE_MINUTES,
    CONF_URGENT_HIGH_THRESHOLD,
    CONF_URGENT_LOW_THRESHOLD,
    DEFAULT_HIGH_ALERT_REPEAT_MINUTES,
    DEFAULT_HIGH_THRESHOLD,
    DEFAULT_LOW_ALERT_REPEAT_MINUTES,
    DEFAULT_LOW_THRESHOLD,
    DEFAULT_RAPID_CHANGE_RATE,
    DEFAULT_REGION,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_STALE_MINUTES,
    DEFAULT_URGENT_HIGH_THRESHOLD,
    DEFAULT_URGENT_LOW_THRESHOLD,
    DOMAIN,
    MAX_ALERT_REPEAT_MINUTES,
    MIN_ALERT_REPEAT_MINUTES,
    MIN_SCAN_INTERVAL,
    REGION_HOSTS,
)

_LOGGER = logging.getLogger(__name__)


class BauerGlucoseConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._email: str | None = None
        self._password: str | None = None
        self._region: str = DEFAULT_REGION
        self._connections: list[dict[str, str]] = []

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]
            self._region = user_input[CONF_REGION]

            session = async_get_clientsession(self.hass)
            client = LibreLinkUpClient(session, self._email, self._password, self._region)
            try:
                await client.async_login()
                connections = await client.async_get_connections()
            except LibreLinkUpAuthError as err:
                _LOGGER.warning("LibreLinkUp auth failed: %s", err)
                errors["base"] = "invalid_auth"
            except (LibreLinkUpError, aiohttp.ClientError) as err:
                _LOGGER.warning("LibreLinkUp connection failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if not connections:
                    errors["base"] = "no_connections"
                else:
                    self._connections = [
                        {
                            "patient_id": c.patient_id,
                            "name": f"{c.first_name} {c.last_name}".strip() or c.patient_id,
                        }
                        for c in connections
                    ]
                    return await self.async_step_patient()

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_REGION, default=DEFAULT_REGION): vol.In(sorted(REGION_HOSTS)),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_patient(self, user_input: dict[str, Any] | None = None):
        if len(self._connections) == 1:
            user_input = {CONF_PATIENT_ID: self._connections[0]["patient_id"]}

        if user_input is not None:
            patient_id = user_input[CONF_PATIENT_ID]
            patient = next(c for c in self._connections if c["patient_id"] == patient_id)

            await self.async_set_unique_id(patient_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"{patient['name']} (LibreLinkUp)",
                data={
                    CONF_EMAIL: self._email,
                    CONF_PASSWORD: self._password,
                    CONF_REGION: self._region,
                    CONF_PATIENT_ID: patient_id,
                    CONF_PATIENT_NAME: patient["name"],
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_PATIENT_ID): vol.In(
                    {c["patient_id"]: c["name"] for c in self._connections}
                )
            }
        )
        return self.async_show_form(step_id="patient", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return BauerGlucoseOptionsFlow(config_entry)


class BauerGlucoseOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            if user_input[CONF_SCAN_INTERVAL] < MIN_SCAN_INTERVAL:
                user_input[CONF_SCAN_INTERVAL] = MIN_SCAN_INTERVAL
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_URGENT_LOW_THRESHOLD,
                    default=opts.get(CONF_URGENT_LOW_THRESHOLD, DEFAULT_URGENT_LOW_THRESHOLD),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_LOW_THRESHOLD, default=opts.get(CONF_LOW_THRESHOLD, DEFAULT_LOW_THRESHOLD)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_HIGH_THRESHOLD, default=opts.get(CONF_HIGH_THRESHOLD, DEFAULT_HIGH_THRESHOLD)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_URGENT_HIGH_THRESHOLD,
                    default=opts.get(CONF_URGENT_HIGH_THRESHOLD, DEFAULT_URGENT_HIGH_THRESHOLD),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_RAPID_CHANGE_RATE,
                    default=opts.get(CONF_RAPID_CHANGE_RATE, DEFAULT_RAPID_CHANGE_RATE),
                ): vol.Coerce(float),
                vol.Required(
                    CONF_STALE_MINUTES, default=opts.get(CONF_STALE_MINUTES, DEFAULT_STALE_MINUTES)
                ): vol.Coerce(int),
                vol.Required(
                    CONF_SCAN_INTERVAL, default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
                ): vol.Coerce(int),
                vol.Required(
                    CONF_LOW_ALERT_REPEAT_MINUTES,
                    default=opts.get(CONF_LOW_ALERT_REPEAT_MINUTES, DEFAULT_LOW_ALERT_REPEAT_MINUTES),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_ALERT_REPEAT_MINUTES,
                        max=MAX_ALERT_REPEAT_MINUTES,
                        step=1,
                        mode=selector.NumberSelectorMode.SLIDER,
                        unit_of_measurement="min",
                    )
                ),
                vol.Required(
                    CONF_HIGH_ALERT_REPEAT_MINUTES,
                    default=opts.get(CONF_HIGH_ALERT_REPEAT_MINUTES, DEFAULT_HIGH_ALERT_REPEAT_MINUTES),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_ALERT_REPEAT_MINUTES,
                        max=MAX_ALERT_REPEAT_MINUTES,
                        step=1,
                        mode=selector.NumberSelectorMode.SLIDER,
                        unit_of_measurement="min",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
