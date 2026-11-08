"""Client for the club website."""

from __future__ import annotations

from datetime import date, tzinfo
import html
import json
import logging
import re
from typing import Any

import aiohttp

from .const import (
    BOOKINGS_PATH,
    BROWSER_USER_AGENT,
    EVENTS_PATH,
    LOGIN_PATH,
    TASKS_LIST_PATH,
    TASKS_PAGE_PATH,
    USER_AGENT,
)
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


def _logged_in(page: str) -> bool:
    """After posting the form, the login form only comes back when rejected.

    The logout link text depends on the site language (Uitloggen/Logout),
    so it is not required.
    """
    return 'name="Login.Password"' not in page


def _visible_text(page: str) -> str:
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S | re.I)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _title(page: str) -> str:
    m = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    return " ".join(html.unescape(m.group(1)).split()) if m else ""


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
        self._browser_ua = False
        self.diagnostics: dict[str, Any] = {}

    @property
    def _headers(self) -> dict[str, str]:
        agent = BROWSER_USER_AGENT if self._browser_ua else USER_AGENT
        return {"User-Agent": agent, "Accept-Language": "nl-NL,nl;q=0.9"}

    async def login(self) -> None:
        """Post the login form; the site sets a session cookie.

        The form has a "login with" choice (bondsnummer or clublidnummer);
        try the bondsnummer first and fall back to the clublidnummer.
        """
        url = f"{self._base_url}{LOGIN_PATH}"
        timeout = aiohttp.ClientTimeout(total=20)
        attempts: list[str] = []
        try:
            async with self._session.get(url, headers=self._headers, timeout=timeout) as resp:
                await resp.read()
            for login_type in ("FedmembershipNumber", "ClubmembershipNumber"):
                async with self._session.post(
                    url,
                    data={
                        "Login.LoginType": login_type,
                        "Login.MembershipNumber": self._number,
                        "Login.Password": self._password,
                    },
                    headers=self._headers | {"Origin": self._base_url, "Referer": url},
                    timeout=timeout,
                ) as resp:
                    resp.raise_for_status()
                    page = await resp.text()
                    post_info = (
                        f"{login_type}: POST {resp.status} -> {resp.url.path}"
                        f" (redirects {len(getattr(resp, "history", ()))}, form={'Login.Password' in page},"
                        f" uitloggen={'Uitloggen' in page})"
                    )
                cookies = sorted(c.key for c in self._session.cookie_jar)
                attempts.append(f"{post_info}; cookies={cookies}")
                if _logged_in(page):
                    self._logged_in = True
                    await self._open_tasks_page()
                    return
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ClubSiteError(f"Inloggen mislukt: {err}") from err
        self._logged_in = False
        _LOGGER.warning("Inloggen op %s afgewezen: %s", self._base_url, " | ".join(attempts))
        raise LoginError("Bondsnummer of wachtwoord niet geaccepteerd")

    @property
    def _tasks_page(self) -> str:
        return f"{self._base_url}{TASKS_PAGE_PATH}"

    async def _get_page(self, path: str) -> tuple[int, str]:
        async with self._session.get(
            f"{self._base_url}{path}",
            headers=self._headers
            | {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": f"{self._base_url}{LOGIN_PATH}",
            },
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=False,
        ) as resp:
            return resp.status, await resp.text()

    async def _open_tasks_page(self) -> None:
        """Open the duties page like a browser does before its calendar loads.

        The site answered this page with HTTP 500 for the integration while
        browsers get it fine; retry with a browser user agent and keep that
        one when it helps.
        """
        try:
            status, page = await self._get_page(TASKS_PAGE_PATH)
            info = f"HTTP {status}, kalender={'data-source-url' in page}"
            if status >= 500 and not self._browser_ua:
                self._browser_ua = True
                status, page = await self._get_page(TASKS_PAGE_PATH)
                info += f"; als browser: HTTP {status}, kalender={'data-source-url' in page}"
                if status >= 500:
                    self._browser_ua = False
            if status >= 500:
                info += f"; foutpagina: {_visible_text(page)[:200]!r}"
            self.diagnostics["takenpagina"] = info
        except (aiohttp.ClientError, TimeoutError) as err:
            self.diagnostics["takenpagina"] = f"fout: {err}"

    def _ajax_headers(self, accept: str) -> dict[str, str]:
        return self._headers | {
            "X-Requested-With": "XMLHttpRequest",
            "Accept": accept,
            "Origin": self._base_url,
            "Referer": self._tasks_page,
        }

    async def _post_events(self, start: date, end: date) -> tuple[int, str, str]:
        url = f"{self._base_url}{EVENTS_PATH}"
        async with self._session.post(
            url,
            data={"start": start.isoformat(), "end": end.isoformat()},
            headers=self._ajax_headers("application/json, text/javascript, */*; q=0.01"),
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=False,
        ) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), await resp.text()

    async def probe_task_list(self) -> None:
        """Record what the member pages return, to see why duties are missing.

        Only status codes, sizes and counts are kept, plus the visible text
        of a short (empty) list.
        """
        try:
            status, page = await self._get_page(LOGIN_PATH)
            self.diagnostics["mijn"] = (
                f"HTTP {status}, uitlogknop={'/mijn/logoff' in page.lower()},"
                f" titel={_title(page)!r}"
            )
            lists = []
            for show_all in ("false", "true"):
                async with self._session.post(
                    f"{self._base_url}{TASKS_LIST_PATH}",
                    data={"showAllDuties": show_all},
                    headers=self._ajax_headers("text/html, */*; q=0.01"),
                    timeout=aiohttp.ClientTimeout(total=20),
                    allow_redirects=False,
                ) as resp:
                    body = await resp.text()
                info = (
                    f"alle={show_all}: HTTP {resp.status}, {len(body)} tekens,"
                    f" 'Bardienst' {body.count('Bardienst')}x"
                )
                if len(body) < 1500:
                    info += f", tekst={_visible_text(body)[:300]!r}"
                lists.append(info)
            self.diagnostics["takenlijst"] = " | ".join(lists)
        except (aiohttp.ClientError, TimeoutError) as err:
            self.diagnostics["takenlijst"] = f"fout: {err}"

    async def events(self, start: date, end: date) -> Any:
        """Return the raw (decoded JSON) calendar payload, logging in when needed."""
        try:
            if self._logged_in:
                await self._open_tasks_page()
            else:
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
