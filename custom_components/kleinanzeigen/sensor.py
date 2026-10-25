"""Sensors: one per ad, plus job status and the 30-day publication count."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KleinanzeigenConfigEntry
from .entity import AdEntity, KleinanzeigenEntity, track_ads

JOB_STATES = ["idle", "running", "waiting_for_user", "success", "error"]
AD_STATES = {"active": "aktiv", "paused": "reserviert", "reserved": "reserviert", "inactive": "inaktiv"}


async def async_setup_entry(
    hass: HomeAssistant, entry: KleinanzeigenConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([JobSensor(coordinator), QuotaSensor(coordinator)])
    entry.async_on_unload(
        track_ads(coordinator, async_add_entities, lambda title: [AdSensor(coordinator, title)])
    )


class JobSensor(KleinanzeigenEntity, SensorEntity):
    _attr_translation_key = "job"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = JOB_STATES
    _attr_icon = "mdi:robot"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "job")

    @property
    def native_value(self) -> str:
        status = self.coordinator.data.get("job", {}).get("status", "idle")
        return status if status in JOB_STATES else "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        job = self.coordinator.data.get("job", {})
        return {
            "action": job.get("action"),
            "step": job.get("step"),
            "message": job.get("message"),
            "started": job.get("started"),
            "finished": job.get("finished"),
            "log": (job.get("log") or [])[-15:],
            "ads_updated": self.coordinator.data.get("ads_updated"),
        }


class QuotaSensor(KleinanzeigenEntity, SensorEntity):
    """Kleinanzeigen counts every (re-)publication against the free quota
    (50 new ads per 30 days for private users)."""

    _attr_translation_key = "quota"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "Anzeigen"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "quota_30d")

    @property
    def native_value(self) -> int:
        return int(self.coordinator.data.get("republished_30d", 0))


class AdSensor(AdEntity, SensorEntity):
    _attr_icon = "mdi:tag-text"

    def __init__(self, coordinator, title: str) -> None:
        super().__init__(coordinator, title, "status")
        self._attr_name = title

    @property
    def native_value(self) -> str | None:
        ad = self.ad
        if ad is None:
            return None
        return AD_STATES.get(ad.get("status"), ad.get("status"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ad = self.ad or {}
        return {
            "anzeigen_id": ad.get("id"),
            "url": ad.get("url"),
            "laeuft_ab": ad.get("expires"),
            "zuletzt_neu_eingestellt": ad.get("last_republished"),
            "naechstes_mal_ab": ad.get("next_allowed"),
            "neu_einstellen_erlaubt": ad.get("republish_allowed"),
        }
