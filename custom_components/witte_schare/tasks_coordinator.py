"""Coordinator for the member calendar (bardiensten, clubagenda)."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from aiohttp import DummyCookieJar

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import ClubSiteError, LoginError, MemberClient
from .const import (
    CLUB_TIMEZONE,
    CONF_BASE_URL,
    CONF_MEMBERSHIP_NUMBER,
    CONF_PASSWORD,
    DEFAULT_BASE_URL,
    DOMAIN,
    TASKS_DAYS_AHEAD,
    TASKS_UPDATE_INTERVAL,
)
from .tasks import ClubEvent, parse_events

_LOGGER = logging.getLogger(__name__)

# Keys whose values could hold a person's name; masked in the debug sample.
_PERSONAL = ("name", "user", "member", "person", "assigned", "volunteer", "email", "phone")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if any(p in k.lower() for p in _PERSONAL) and k.lower() != "title" else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value[:3]]
    return value


class TasksCoordinator(DataUpdateCoordinator[list[ClubEvent]]):
    """Logs in and fetches the next weeks of the member calendar."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_tasks",
            update_interval=TASKS_UPDATE_INTERVAL,
        )
        self.tz = dt_util.get_time_zone(CLUB_TIMEZONE)
        session = async_create_clientsession(hass, cookie_jar=DummyCookieJar())
        self.client = MemberClient(
            session,
            entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            entry.options[CONF_MEMBERSHIP_NUMBER],
            entry.options[CONF_PASSWORD],
        )
        self.raw_sample: Any = None
        self.raw_keys: list[str] = []
        self.raw_count = 0

    async def _async_update_data(self) -> list[ClubEvent]:
        today = dt_util.now(self.tz).date()
        try:
            payload = await self.client.events(
                today - timedelta(days=1), today + timedelta(days=TASKS_DAYS_AHEAD)
            )
        except LoginError as err:
            raise UpdateFailed(f"{err}; pas het aan bij Configureren") from err
        except ClubSiteError as err:
            raise UpdateFailed(str(err)) from err

        items = payload if isinstance(payload, list) else payload
        self.raw_sample = _redact(items)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            self.raw_keys = sorted({k for i in items if isinstance(i, dict) for k in i})
            self.raw_count = len(items)
        elif isinstance(items, dict):
            self.raw_keys = sorted(items)
        try:
            return parse_events(payload, self.tz)
        except ValueError as err:
            raise UpdateFailed(f"Diensten niet te lezen: {err}") from err

    def upcoming(self, *, tasks: bool, days: int | None = None) -> list[ClubEvent]:
        now = dt_util.now()
        until = now + timedelta(days=days) if days else None
        return [
            e for e in (self.data or [])
            if e.is_task == tasks and e.end > now and (until is None or e.start < until)
        ]
