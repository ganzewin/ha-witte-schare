"""Sensors for the court booking board."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_LOOKAHEAD, DEFAULT_LOOKAHEAD
from .coordinator import BookingCoordinator, WitteSchareConfigEntry
from .entity import WitteSchareEntity
from .parser import Booking, merge_activity


def _courts(bookings: list[Booking]) -> list[str]:
    return sorted({b.court for b in bookings}, key=lambda c: (c.lower().startswith("padel"), len(c), c))


def _now_attrs(bookings: list[Booking]) -> dict[str, Any]:
    return {
        "banen": _courts(bookings),
        "soorten": sorted({b.kind for b in bookings}),
        "spelers": sum(b.players or 0 for b in bookings),
    }


def _lookahead(c: BookingCoordinator) -> timedelta:
    return timedelta(minutes=int(c.config_entry.options.get(CONF_LOOKAHEAD, DEFAULT_LOOKAHEAD)))


def _current_block_end(c: BookingCoordinator, now: datetime) -> datetime | None:
    for start, end, _ in merge_activity(c.data.all()):
        if start <= now < end:
            return end
    return None


def _next_start(c: BookingCoordinator, now: datetime) -> datetime | None:
    for start, _, _ in merge_activity(c.data.all()):
        if start > now:
            return start
    return None


@dataclass(frozen=True, kw_only=True)
class BoardSensorDescription(SensorEntityDescription):
    value_fn: Callable[[BookingCoordinator, datetime], Any]
    attrs_fn: Callable[[BookingCoordinator, datetime], dict[str, Any]] | None = None


def _today(c: BookingCoordinator) -> list[Booking]:
    return c.data.on(c.today())


SENSORS: tuple[BoardSensorDescription, ...] = (
    BoardSensorDescription(
        key="courts_in_use",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="banen",
        value_fn=lambda c, now: len(_courts(c.data.active(now))),
        attrs_fn=lambda c, now: _now_attrs(c.data.active(now)),
    ),
    BoardSensorDescription(
        key="tennis_courts_in_use",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="banen",
        value_fn=lambda c, now: len(_courts([b for b in c.data.active(now) if b.is_tennis])),
    ),
    BoardSensorDescription(
        key="padel_courts_in_use",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="banen",
        value_fn=lambda c, now: len(_courts([b for b in c.data.active(now) if b.is_padel])),
    ),
    BoardSensorDescription(
        key="players_now",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="spelers",
        value_fn=lambda c, now: sum(b.players or 0 for b in c.data.active(now)),
    ),
    BoardSensorDescription(
        key="courts_in_use_upcoming",
        native_unit_of_measurement="banen",
        value_fn=lambda c, now: len(_courts(c.data.overlapping(now, now + _lookahead(c)))),
        attrs_fn=lambda c, now: _now_attrs(c.data.overlapping(now, now + _lookahead(c)))
        | {"minuten_vooruit": int(_lookahead(c).total_seconds() // 60)},
    ),
    BoardSensorDescription(
        key="bookings_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c, now: len(_today(c)),
        attrs_fn=lambda c, now: {
            "per_soort": {
                k: sum(1 for b in _today(c) if b.kind == k) for k in sorted({b.kind for b in _today(c)})
            }
        },
    ),
    BoardSensorDescription(
        key="first_booking_today",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, now: min((b.start for b in _today(c)), default=None),
    ),
    BoardSensorDescription(
        key="last_booking_end_today",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, now: max((b.end for b in _today(c)), default=None),
    ),
    BoardSensorDescription(
        key="next_activity_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, now: _next_start(c, now),
    ),
    BoardSensorDescription(
        key="current_activity_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c, now: _current_block_end(c, now),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WitteSchareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    c = entry.runtime_data
    entities: list = [BoardSensor(c, d) for d in SENSORS]
    if c.tasks is not None:
        from .tasks_entity import NextOpenDutySensor, OpenDutiesSensor, SourceSensor

        entities += [OpenDutiesSensor(c.tasks), NextOpenDutySensor(c.tasks), SourceSensor(c.tasks)]
    async_add_entities(entities)


class BoardSensor(WitteSchareEntity, SensorEntity):
    entity_description: BoardSensorDescription

    def __init__(self, coordinator: BookingCoordinator, description: BoardSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator, dt_util.now())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if fn := self.entity_description.attrs_fn:
            return fn(self.coordinator, dt_util.now())
        return None
