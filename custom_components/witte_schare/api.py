"""Client for the club website."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, tzinfo
from email.utils import parsedate_to_datetime
from http.cookies import CookieError, SimpleCookie
import html
import json
import logging
import re
from typing import Any

import aiohttp
from yarl import URL

from .const import (
    BOOKINGS_PATH,
    BROWSER_USER_AGENT,
    EVENTS_PATH,
    LOGIN_PATH,
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


def _page_outline(page: str) -> str:
    """Describe a page by its structure only (no names or other content)."""
    body = page.split("<body", 1)[-1]
    parts = [f"titel={_title(page)!r}", f"{len(page)} tekens"]
    heads = [_visible_text(h)[:60] for h in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", body, re.S | re.I)]
    parts.append(f"koppen={heads[:6]}")
    for form in re.findall(r"<form\b[^>]*>.*?</form>", body, re.S | re.I)[:4]:
        action = re.search(r'action="([^"]*)"', form)
        names = re.findall(r'name="([^"]+)"', form)
        parts.append(f"form {action.group(1) if action else '?'} velden={names[:12]}")
    links = sorted({h for h in re.findall(r'href="(/(?:mijn|me|Ajax|Account|Profile)[^"?#]*)', body, re.I)})
    parts.append(f"links={links[:20]}")
    scripts = re.findall(r"(location(?:\.href)?\s*=\s*['\"][^'\"]+|/Ajax/[A-Za-z/]+)", body)
    parts.append(f"scripts={sorted(set(scripts))[:10]}")
    return "; ".join(parts)


class LoginError(ClubSiteError):
    """Membership number or password rejected."""


@dataclass(slots=True)
class _Reply:
    status: int
    content_type: str
    text: str


def _cookie_attrs(header: str) -> str:
    """Describe a Set-Cookie header without its value."""
    name, _, rest = header.partition("=")
    attrs = [a.strip().split("=", 1)[0].lower() for a in rest.split(";")[1:] if a.strip()]
    extra = ""
    for key in ("path", "domain", "expires", "max-age", "samesite"):
        if m := re.search(rf";\s*{key}=([^;]*)", header, re.I):
            extra += f" {key}={m.group(1).strip()}"
    return f"{name.strip()}[{','.join(attrs)}{extra}]"


class MemberClient:
    """Logged-in access to the member part of the club site.

    Cookies are kept here instead of in aiohttp's cookie jar: with the jar
    the site's login cookie was not sent back on the next request (the page
    after login showed the member menu, the next one did not).
    """

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
        # A browser has these after accepting the cookie bar.
        self._cookies: dict[str, str] = {"_acceptCookie": "1", "_calendarViewType": "calendar"}
        self.diagnostics: dict[str, Any] = {}

    @property
    def _headers(self) -> dict[str, str]:
        agent = BROWSER_USER_AGENT if self._browser_ua else USER_AGENT
        return {"User-Agent": agent, "Accept-Language": "nl-NL,nl;q=0.9"}

    def _store_cookies(self, resp: aiohttp.ClientResponse) -> list[str]:
        seen = []
        for header in resp.headers.getall("Set-Cookie", []):
            seen.append(_cookie_attrs(header))
            cookie = SimpleCookie()
            try:
                cookie.load(header)
            except CookieError:
                name, _, rest = header.partition("=")
                self._cookies[name.strip()] = rest.split(";", 1)[0].strip()
                continue
            for name, morsel in cookie.items():
                expired = morsel["max-age"].strip() in ("0", "-1")
                if not expired and morsel["expires"]:
                    try:
                        expired = parsedate_to_datetime(morsel["expires"]) < datetime.now(UTC)
                    except (TypeError, ValueError):
                        expired = False
                if expired or morsel.value == "":
                    self._cookies.pop(name, None)
                else:
                    self._cookies[name] = morsel.value
        return seen

    async def _send(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        data: dict[str, str] | None = None,
        follow: bool = False,
    ) -> _Reply:
        """Do one request with our own cookies, optionally following redirects."""
        url = f"{self._base_url}{path}" if path.startswith("/") else path
        for _ in range(5):
            cookie = "; ".join(f"{k}={v}" for k, v in self._cookies.items())
            async with self._session.request(
                method,
                url,
                data=data,
                headers=headers | {"Cookie": cookie},
                timeout=aiohttp.ClientTimeout(total=20),
                allow_redirects=False,
            ) as resp:
                seen = self._store_cookies(resp)
                if method == "POST" and path == LOGIN_PATH:
                    self.diagnostics["cookies_na_inloggen"] = seen
                text = await resp.text()
                if follow and resp.status in (301, 302, 303, 307) and "Location" in resp.headers:
                    url = str(resp.url.join(URL(resp.headers["Location"])))
                    method, data = "GET", None
                    continue
                return _Reply(resp.status, resp.headers.get("Content-Type", ""), text)
        raise ClubSiteError("Te veel doorverwijzingen")

    async def login(self) -> None:
        """Post the login form; the site sets a session cookie.

        The form has a "login with" choice (bondsnummer or clublidnummer);
        try the bondsnummer first and fall back to the clublidnummer.
        """
        url = f"{self._base_url}{LOGIN_PATH}"
        attempts: list[str] = []
        try:
            await self._send("GET", LOGIN_PATH, self._headers, follow=True)
            for login_type in ("FedmembershipNumber", "ClubmembershipNumber"):
                reply = await self._send(
                    "POST",
                    LOGIN_PATH,
                    self._headers | {"Origin": self._base_url, "Referer": url},
                    data={
                        "Login.LoginType": login_type,
                        "Login.MembershipNumber": self._number,
                        "Login.Password": self._password,
                    },
                    follow=True,
                )
                if reply.status >= 400:
                    raise ClubSiteError(f"Inloggen gaf HTTP {reply.status}")
                attempts.append(
                    f"{login_type}: POST {reply.status}, form={'Login.Password' in reply.text};"
                    f" cookies={sorted(self._cookies)}"
                )
                if _logged_in(reply.text):
                    self.diagnostics["na_inloggen"] = _page_outline(reply.text)
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
        reply = await self._send(
            "GET",
            path,
            self._headers
            | {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": f"{self._base_url}{LOGIN_PATH}",
            },
        )
        return reply.status, reply.text

    async def _open_tasks_page(self) -> None:
        """Open the duties page like a browser does before its calendar loads.

        If the site answers with a server error, retry once with a browser
        user agent and keep that one when it helps.
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
                info += f"; {_page_outline(page)}"
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
        reply = await self._send(
            "POST",
            EVENTS_PATH,
            self._ajax_headers("application/json, text/javascript, */*; q=0.01"),
            data={"start": start.isoformat(), "end": end.isoformat()},
        )
        return reply.status, reply.content_type, reply.text

    async def events(self, start: date, end: date) -> Any:
        """Return the raw (decoded JSON) calendar payload, logging in when needed.

        An expired session is not refused: the site then answers like for a
        visitor, with only the public club agenda. So when a reply holds no
        duties at all, log in again once and ask again.
        """
        fresh = not self._logged_in
        try:
            if fresh:
                await self.login()
            payload = await self._events_once(start, end)
            if payload is None or (not fresh and not _has_duties(payload)):
                await self.login()
                payload = await self._events_once(start, end)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ClubSiteError(f"Diensten ophalen mislukt: {err}") from err
        if payload is None:
            raise ClubSiteError("Diensten ophalen gaf geen geldig antwoord")
        return payload

    async def _events_once(self, start: date, end: date) -> Any:
        """One calendar request; None when the reply looks like a logged-out one."""
        status, ctype, body = await self._post_events(start, end)
        if status in (301, 302, 401, 403) or "json" not in ctype:
            return None
        if status != 200:
            raise ClubSiteError(f"Diensten ophalen gaf HTTP {status}")
        try:
            return json.loads(body)
        except ValueError as err:
            raise ClubSiteError(f"Geen JSON van diensten ({ctype}): {body[:120]!r}") from err


def _has_duties(payload: Any) -> bool:
    """True when the payload holds anything besides public agenda items (type 3)."""
    items = payload if isinstance(payload, list) else []
    return any(isinstance(i, dict) and str(i.get("type")) != "3" for i in items)
