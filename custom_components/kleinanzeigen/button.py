"""Buttons: re-publish one ad / all ads, refresh, continue, cancel."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KleinanzeigenConfigEntry
from .api import BridgeError
from .entity import AdEntity, KleinanzeigenEntity, track_ads


async def async_setup_entry(
    hass: HomeAssistant, entry: KleinanzeigenConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            ActionButton(coordinator, "republish_all", "mdi:tag-arrow-up", lambda c: c.republish()),
            ActionButton(coordinator, "refresh", "mdi:refresh", lambda c: c.refresh()),
            ActionButton(coordinator, "continue", "mdi:play", lambda c: c.continue_job()),
            ActionButton(coordinator, "cancel", "mdi:stop", lambda c: c.cancel()),
        ]
    )
    entry.async_on_unload(
        track_ads(coordinator, async_add_entities, lambda title: [AdRepublishButton(coordinator, title)])
    )


async def _call(coordinator, coro) -> None:
    try:
        await coro
    except BridgeError as err:
        raise HomeAssistantError(str(err)) from err
    await coordinator.async_request_refresh()


class ActionButton(KleinanzeigenEntity, ButtonEntity):
    def __init__(self, coordinator, key: str, icon: str, action) -> None:
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._attr_icon = icon
        self._action = action

    async def async_press(self) -> None:
        await _call(self.coordinator, self._action(self.coordinator.client))


class AdRepublishButton(AdEntity, ButtonEntity):
    _attr_icon = "mdi:tag-arrow-up"

    def __init__(self, coordinator, title: str) -> None:
        super().__init__(coordinator, title, "republish")
        self._attr_name = f"{title} neu einstellen"

    async def async_press(self) -> None:
        ad = self.ad
        if ad is None:
            raise HomeAssistantError(f"„{self._title}“ ist nicht mehr online")
        await _call(self.coordinator, self.coordinator.client.republish([ad["id"]]))
