"""Base entity."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN
from .coordinator import BookingCoordinator


class WitteSchareEntity(CoordinatorEntity[BookingCoordinator]):
    """Entity on the 'Afhangbord' service device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BookingCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Afhangbord",
            manufacturer="KNLTB.Club",
            model="Afhangbord",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
            + "/afhangbord-overzicht",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Bookings start on the quarter hour; re-evaluate then instead of
        # waiting up to five minutes for the next fetch.
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._handle_tick, minute=[0, 15, 30, 45], second=2
            )
        )

    @callback
    def _handle_tick(self, _now) -> None:
        self.async_write_ha_state()
