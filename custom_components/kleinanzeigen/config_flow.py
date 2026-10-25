"""Config flow: only the bridge URL - credentials live in the add-on."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import BridgeClient, BridgeError
from .const import CONF_BRIDGE_URL, DEFAULT_BRIDGE_URL, DOMAIN


class KleinanzeigenConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, str] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_BRIDGE_URL])
            self._abort_if_unique_id_configured()
            client = BridgeClient(async_get_clientsession(self.hass), user_input[CONF_BRIDGE_URL])
            try:
                await client.health()
            except BridgeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="Kleinanzeigen", data=user_input)
        schema = vol.Schema({vol.Required(CONF_BRIDGE_URL, default=DEFAULT_BRIDGE_URL): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
