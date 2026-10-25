"""Coordinator: polls the bridge's cached status."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BridgeClient, BridgeError
from .const import CONF_BRIDGE_URL, DOMAIN, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)


class KleinanzeigenCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.client = BridgeClient(async_get_clientsession(hass), entry.data[CONF_BRIDGE_URL])
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Kleinanzeigen",
            manufacturer="kleinanzeigen.de",
            model="kleinanzeigen-bot Bridge",
            configuration_url="https://www.kleinanzeigen.de/m-meine-anzeigen.html",
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.status()
        except BridgeError as err:
            raise UpdateFailed(str(err)) from err

    def ad_by_title(self, title: str) -> dict[str, Any] | None:
        for ad in (self.data or {}).get("ads", []):
            if ad["title"] == title:
                return ad
        return None
