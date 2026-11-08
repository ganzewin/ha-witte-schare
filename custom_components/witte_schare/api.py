"""Client for the club website."""

from __future__ import annotations

from datetime import date, tzinfo
import json
import logging
from typing import Any

import aiohttp

from .const import BOOKINGS_PATH, EVENTS_PATH, LOGIN_PATH, USER_AGENT
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


class LoginError(ClubSiteError):
    """Membership number or password rejected."""


class MemberClient:
    """Logged-in access to the member part of the club site."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        membership_number: str,
        password: str,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._number = membership_number
        self._password = password
        self._logged_in = False

    @property
    def _headers(self) -> dict[str, str]:
        return {"User-Agent": USER_AGENT}

    async def login(self) -> None:
        """Post the login form; the site sets a session cookie."""
        url = f"{self._base_url}{LOGIN_PATH}"
        try:
            async with self._session.post(
                url,
                data={"Login.MembershipNumber": self._number, "Login.Password": self._password},
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                resp.raise_for_status()
                page = await resp.text()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ClubSiteError(f"Inloggen mislukt: {err}") from err
        if 'name="Login.Password"' in page:
            self._logged_in = False
            raise LoginError("Bondsnummer of wachtwoord niet geaccepteerd")
        self._logged_in = True

    async def _post_events(self, start: date, end: date) -> tuple[int, str, str]:
        url = f"{self._base_url}{EVENTS_PATH}"
        async with self._session.post(
            url,
            data={"start": start.isoformat(), "end": end.isoformat()},
            headers=self._headers | {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=False,
        ) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), await resp.text()

    async def events(self, start: date, end: date) -> Any:
        """Return the raw (decoded JSON) calendar payload, logging in when needed."""
        try:
            if not self._logged_in:
                await self.login()
            status, ctype, body = await self._post_events(start, end)
            if status in (301, 302, 401, 403) or "json" not in ctype:
                await self.login()
                status, ctype, body = await self._post_events(start, end)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ClubSiteError(f"Diensten ophalen mislukt: {err}") from err
        if status != 200:
            raise ClubSiteError(f"Diensten ophalen gaf HTTP {status}")
        try:
            return json.loads(body)
        except ValueError as err:
            raise ClubSiteError(f"Geen JSON van diensten ({ctype}): {body[:120]!r}") from err
