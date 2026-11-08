"""Calendars: every booking, and merged activity blocks."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import BookingCoordinator, WitteSchareConfigEntry
from .entity import WitteSchareEntity
from .parser import Booking, merge_activity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WitteSchareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    c = entry.runtime_data
    entities: list = [BookingsCalendar(c), ActivityCalendar(c)]
    if c.tasks is not None:
        from .tasks_entity import ClubCalendar

        entities += [ClubCalendar(c.tasks, True), ClubCalendar(c.tasks, False)]
    async_add_entities(entities)


def _booking_event(b: Booking) -> CalendarEvent:
    return CalendarEvent(
        start=b.start,
        end=b.end,
        summary=b.summary,
        location=b.court,
        uid=f"{b.court}-{b.start.isoformat()}",
    )


def _block_event(start: datetime, end: datetime, items: list[Booking]) -> CalendarEvent:
    courts = sorted({b.court for b in items})
    kinds = sorted({b.kind for b in items})
    return CalendarEvent(
        start=start,
        end=end,
        summary=f"Activiteit ({', '.join(kinds)})",
        description=f"{len(items)} reserveringen op {', '.join(courts)}",
        uid=f"activity-{start.isoformat()}",
    )


class BookingsCalendar(WitteSchareEntity, CalendarEntity):
    """Every reservation on the board."""

    def __init__(self, coordinator: BookingCoordinator) -> None:
        super().__init__(coordinator, "bookings")

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [b for b in self.coordinator.data.all() if b.end > now]
        return _booking_event(min(upcoming, key=lambda b: b.start)) if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        bookings = await self.coordinator.async_bookings_between(start_date, end_date)
        return [_booking_event(b) for b in bookings]


class ActivityCalendar(WitteSchareEntity, CalendarEntity):
    """Periods in which at least one court is in use. Handy for heating."""

    def __init__(self, coordinator: BookingCoordinator) -> None:
        super().__init__(coordinator, "activity")

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        for start, end, items in merge_activity(self.coordinator.data.all()):
            if end > now:
                return _block_event(start, end, items)
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        bookings = await self.coordinator.async_bookings_between(start_date, end_date)
        return [
            _block_event(s, e, items)
            for s, e, items in merge_activity(bookings)
            if s < end_date and e > start_date
        ]
