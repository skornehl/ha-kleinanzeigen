"""Config flow: only the bridge URL - credentials live in the add-on."""
from __future__ import annotations

from typing import Any

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

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point the entry at another bridge - e.g. the add-on installed from
        skornehl/ha-addons, which has a different hostname. Entities and
        their history stay, unlike removing and re-adding the entry."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_BRIDGE_URL]
            if url != entry.unique_id:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
            client = BridgeClient(async_get_clientsession(self.hass), url)
            try:
                await client.health()
            except BridgeError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, unique_id=url, data_updates={CONF_BRIDGE_URL: url}
                )

        current = (user_input or entry.data).get(CONF_BRIDGE_URL, DEFAULT_BRIDGE_URL)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required(CONF_BRIDGE_URL, default=current): str}),
            description_placeholders={"default_url": DEFAULT_BRIDGE_URL},
            errors=errors,
        )
