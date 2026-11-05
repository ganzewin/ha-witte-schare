"""Client for the club website."""

from __future__ import annotations

from datetime import date, tzinfo
import logging

import aiohttp

from .const import BOOKINGS_PATH, USER_AGENT
from .parser import Booking, ParseError, page_date, parse_bookings

_LOGGER = logging.getLogger(__name__)


class ClubSiteError(Exception):
    """Club site could not be read."""


class ClubSiteClient:
    """Reads public data from a KNLTB.Club club site."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, tz: tzinfo) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._tz = tz

    async def _get(self, path: str, params: dict[str, str] | None = None) -> str:
        url = f"{self._base_url}{path}"
        try:
            async with self._session.get(
                url,
                params=params,
                headers={"User-Agent": USER_AGENT, "X-Requested-With": "XMLHttpRequest"},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                resp.raise_for_status()
                return await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ClubSiteError(f"Fout bij ophalen {url}: {err}") from err

    async def bookings(self, day: date) -> list[Booking]:
        """Return all bookings on ``day``."""
        page = await self._get(
            BOOKINGS_PATH, {"date": day.strftime("%m/%d/%Y 00:00:00")}
        )
        shown = page_date(page)
        if shown and shown != day:
            _LOGGER.debug("Asked for %s, site returned %s", day, shown)
            day = shown
        try:
            return parse_bookings(page, day, self._tz)
        except ParseError as err:
            raise ClubSiteError(f"Afhangbord niet te lezen: {err}") from err
