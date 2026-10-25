"""Shared helpers for the per-ad entities."""
from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .coordinator import KleinanzeigenCoordinator


class KleinanzeigenEntity(CoordinatorEntity[KleinanzeigenCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: KleinanzeigenCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{key}"
        self._attr_device_info = coordinator.device_info


class AdEntity(KleinanzeigenEntity):
    """Bound to an ad by its *title*: the ad ID changes with every
    re-publication, the title stays."""

    def __init__(self, coordinator: KleinanzeigenCoordinator, title: str, kind: str) -> None:
        super().__init__(coordinator, f"ad_{slugify(title)}_{kind}")
        self._title = title

    @property
    def ad(self) -> dict | None:
        return self.coordinator.ad_by_title(self._title)

    @property
    def available(self) -> bool:
        return super().available and self.ad is not None


def track_ads(
    coordinator: KleinanzeigenCoordinator,
    async_add_entities: AddEntitiesCallback,
    factory: Callable[[str], list[Entity]],
) -> Callable[[], None]:
    """Add entities for every ad title that shows up, now and later."""
    known: set[str] = set()

    @callback
    def _check() -> None:
        new = []
        for ad in (coordinator.data or {}).get("ads", []):
            if ad["title"] not in known:
                known.add(ad["title"])
                new.extend(factory(ad["title"]))
        if new:
            async_add_entities(new)

    _check()
    return coordinator.async_add_listener(_check)
