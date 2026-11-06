"""Parser for the KNLTB.Club court booking overview (afhangbord).

The club site serves an HTML fragment at ``/courtbooking-overview/GetBookings``.
It has two parts:

* ``#courtTop``: one ``courtholder`` per court with the court name.
* ``#courtMain``: one ``courtholder`` per court (same order) holding the
  reservations for that court.

This module has no Home Assistant dependencies so it can be tested on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
import html
import re

_COURT_NAME = re.compile(r'class="ground">\s*([^<]+?)\s*<')
_RESERVATION = re.compile(
    r'class="time[^"]*">\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*<'
    r'(?P<body>.*?)'
    r'class="label"(?:\s+style="(?P<style>[^"]*)")?\s*>\s*(?P<label>[^<]*?)\s*<',
    re.S,
)
_PLAYERS = re.compile(r'class="playswith[^"]*">\s*(\d+)\s*speler', re.S)
_BG_COLOR = re.compile(r"background-color:\s*(#[0-9a-fA-F]{3,8})")
_HEADING_DATE = re.compile(r'id="dayBookingsDatePicker"[^>]*value="(\d{1,2})-(\d{1,2})-(\d{4})')

MAIN_MARKER = 'id="courtMain"'
HOLDER_MARKER = '<div class="courtholder">'

# Labels that mean the court is not available for play.
CLOSED_KINDS = frozenset({"Gesloten"})


class ParseError(Exception):
    """Raised when the page does not look like a booking overview."""


@dataclass(frozen=True, slots=True)
class Booking:
    """One block on the court booking board."""

    court: str
    start: datetime
    end: datetime
    kind: str
    players: int | None = None
    color: str | None = None

    @property
    def is_tennis(self) -> bool:
        return not self.is_padel

    @property
    def is_padel(self) -> bool:
        return self.court.lower().startswith("padel")

    @property
    def is_closed(self) -> bool:
        return self.kind in CLOSED_KINDS

    @property
    def summary(self) -> str:
        text = f"{self.court}: {self.kind}"
        if self.players:
            text += f" ({self.players} {'speler' if self.players == 1 else 'spelers'})"
        return text

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and self.end > start


def page_date(page: str) -> date | None:
    """Return the date shown in the overview, if present."""
    if m := _HEADING_DATE.search(page):
        day, month, year = (int(x) for x in m.groups())
        return date(year, month, day)
    return None


def parse_courts(page: str) -> list[str]:
    """Return the court names in display order."""
    if MAIN_MARKER not in page:
        raise ParseError("courtMain not found")
    top = page.split(MAIN_MARKER, 1)[0]
    return [html.unescape(n) for n in _COURT_NAME.findall(top)]


def parse_bookings(page: str, day: date, tz: tzinfo) -> list[Booking]:
    """Parse all bookings of one day from the overview HTML."""
    courts = parse_courts(page)
    main = page.split(MAIN_MARKER, 1)[1]
    holders = main.split(HOLDER_MARKER)[1:]
    if courts and len(holders) != len(courts):
        raise ParseError(f"{len(courts)} courts but {len(holders)} columns")

    midnight = datetime.combine(day, time(0), tz)
    bookings: list[Booking] = []
    for index, chunk in enumerate(holders):
        court = courts[index] if index < len(courts) else f"Baan {index + 1}"
        for m in _RESERVATION.finditer(chunk):
            sh, sm, eh, em = (int(x) for x in m.groups()[:4])
            start = midnight + timedelta(hours=sh, minutes=sm)
            end = midnight + timedelta(hours=eh, minutes=em)
            if end <= start:  # ends at or after midnight
                end += timedelta(days=1)
            players = None
            if pm := _PLAYERS.search(m.group("body")):
                players = int(pm.group(1))
            color = None
            if (style := m.group("style")) and (cm := _BG_COLOR.search(style)):
                color = cm.group(1)
            bookings.append(
                Booking(
                    court=court,
                    start=start,
                    end=end,
                    kind=html.unescape(m.group("label")) or "Onbekend",
                    players=players,
                    color=color,
                )
            )
    bookings.sort(key=lambda b: (b.start, b.court))
    return bookings


def merge_activity(
    bookings: list[Booking], gap: timedelta = timedelta(0)
) -> list[tuple[datetime, datetime, list[Booking]]]:
    """Merge overlapping (or nearly touching) bookings into activity blocks.

    Closed blocks are ignored. Useful for heating: one block per period in
    which at least one court is in use.
    """
    blocks: list[tuple[datetime, datetime, list[Booking]]] = []
    for b in sorted((b for b in bookings if not b.is_closed), key=lambda b: b.start):
        if blocks and b.start <= blocks[-1][1] + gap:
            start, end, items = blocks[-1]
            blocks[-1] = (start, max(end, b.end), [*items, b])
        else:
            blocks.append((b.start, b.end, [b]))
    return blocks
