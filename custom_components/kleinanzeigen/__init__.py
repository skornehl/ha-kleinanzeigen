"""Kleinanzeigen: re-publish your own kleinanzeigen.de ads from Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import KleinanzeigenCoordinator

PLATFORMS = [Platform.BUTTON, Platform.SENSOR]

type KleinanzeigenConfigEntry = ConfigEntry[KleinanzeigenCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: KleinanzeigenConfigEntry) -> bool:
    coordinator = KleinanzeigenCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KleinanzeigenConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
