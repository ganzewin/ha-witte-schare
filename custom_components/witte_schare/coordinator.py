"""Data coordinator for the court booking board."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ClubSiteClient, ClubSiteError
from .const import (
    CACHE_TTL,
    MAX_CALENDAR_DAYS,
    CLUB_TIMEZONE,
    CONF_BASE_URL,
    CONF_DAYS_AHEAD,
    DEFAULT_BASE_URL,
    DEFAULT_DAYS_AHEAD,
    DOMAIN,
    FUTURE_REFRESH,
    UPDATE_INTERVAL,
)
from .parser import Booking

_LOGGER = logging.getLogger(__name__)

type WitteSchareConfigEntry = ConfigEntry[BookingCoordinator]


@dataclass
class BoardData:
    """Bookings for today and the coming days."""

    days: dict[date, list[Booking]] = field(default_factory=dict)

    def all(self) -> list[Booking]:
        return [b for d in sorted(self.days) for b in self.days[d]]

    def active(self, at: datetime) -> list[Booking]:
        return [b for b in self.all() if not b.is_closed and b.start <= at < b.end]

    def overlapping(self, start: datetime, end: datetime) -> list[Booking]:
        return [b for b in self.all() if not b.is_closed and b.overlaps(start, end)]

    def on(self, day: date) -> list[Booking]:
        return [b for b in self.days.get(day, []) if not b.is_closed]


class BookingCoordinator(DataUpdateCoordinator[BoardData]):
    """Fetches the board: today every update, later days hourly."""

    config_entry: WitteSchareConfigEntry

    def __init__(self, hass: HomeAssistant, entry: WitteSchareConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.tz = dt_util.get_time_zone(CLUB_TIMEZONE)
        self.client = ClubSiteClient(
            async_get_clientsession(hass),
            entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            self.tz,
        )
        self._fetched: dict[date, datetime] = {}
        self._cache: dict[date, list[Booking]] = {}

    @property
    def days_ahead(self) -> int:
        return int(self.config_entry.options.get(CONF_DAYS_AHEAD, DEFAULT_DAYS_AHEAD))

    def today(self) -> date:
        return dt_util.now(self.tz).date()

    async def _fetch(self, day: date) -> list[Booking]:
        bookings = await self.client.bookings(day)
        self._cache[day] = bookings
        self._fetched[day] = dt_util.utcnow()
        return bookings

    def _stale(self, day: date, max_age: timedelta) -> bool:
        fetched = self._fetched.get(day)
        return fetched is None or dt_util.utcnow() - fetched > max_age

    async def _async_update_data(self) -> BoardData:
        today = self.today()
        try:
            await self._fetch(today)
            for offset in range(1, self.days_ahead + 1):
                day = today + timedelta(days=offset)
                if self._stale(day, FUTURE_REFRESH):
                    await self._fetch(day)
        except ClubSiteError as err:
            if today not in self._cache:
                raise UpdateFailed(str(err)) from err
            _LOGGER.warning("%s; oude gegevens worden gebruikt", err)

        # Yesterday is kept so a booking running past midnight still counts.
        keep = {today + timedelta(days=o) for o in range(-1, self.days_ahead + 1)}
        self._prune(keep)
        return BoardData(days={d: self._cache[d] for d in sorted(keep) if d in self._cache})

    def _prune(self, keep: set[date]) -> None:
        for day in list(self._cache):
            if day not in keep and self._stale(day, CACHE_TTL):
                self._cache.pop(day, None)
                self._fetched.pop(day, None)

    async def async_bookings_between(self, start: datetime, end: datetime) -> list[Booking]:
        """Bookings in a range, fetching days that are not cached (for the calendar)."""
        first = start.astimezone(self.tz).date() - timedelta(days=1)
        last = end.astimezone(self.tz).date()
        if (last - first).days > MAX_CALENDAR_DAYS:
            last = first + timedelta(days=MAX_CALENDAR_DAYS)
        result: list[Booking] = []
        day = first
        while day <= last:
            bookings = self._cache.get(day)
            if bookings is None or self._stale(day, CACHE_TTL):
                try:
                    bookings = await self._fetch(day)
                except ClubSiteError as err:
                    _LOGGER.debug("Calendar fetch %s failed: %s", day, err)
                    bookings = self._cache.get(day, [])
            result.extend(b for b in bookings if b.overlaps(start, end))
            day += timedelta(days=1)
        return result
