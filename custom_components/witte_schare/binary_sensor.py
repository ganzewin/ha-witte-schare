"""Binary sensors: is there activity now / soon."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_LOOKAHEAD, DEFAULT_LOOKAHEAD
from .coordinator import BookingCoordinator, WitteSchareConfigEntry
from .entity import WitteSchareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WitteSchareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    c = entry.runtime_data
    async_add_entities([ActivityNow(c), ActivityUpcoming(c)])


class ActivityNow(WitteSchareEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: BookingCoordinator) -> None:
        super().__init__(coordinator, "activity_now")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.active(dt_util.now()))


class ActivityUpcoming(WitteSchareEntity, BinarySensorEntity):
    """On when a booking runs now or starts within the lookahead window."""

    _attr_device_class = BinarySensorDeviceClass.OCCUPANCY

    def __init__(self, coordinator: BookingCoordinator) -> None:
        super().__init__(coordinator, "activity_upcoming")

    @property
    def _window(self) -> timedelta:
        opts = self.coordinator.config_entry.options
        return timedelta(minutes=int(opts.get(CONF_LOOKAHEAD, DEFAULT_LOOKAHEAD)))

    @property
    def is_on(self) -> bool:
        now = dt_util.now()
        return bool(self.coordinator.data.overlapping(now, now + self._window))

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        return {"minuten_vooruit": int(self._window.total_seconds() // 60)}
