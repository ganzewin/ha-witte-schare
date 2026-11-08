"""Parser for the member calendar (bardiensten en clubagenda).

``POST /Ajax/Calendar/GetEvents`` feeds a FullCalendar (v3) widget on
``/mijn/Tasks``. The exact JSON has not been seen yet, so parsing is
defensive: it accepts the usual FullCalendar keys and keeps unknown keys.

What is known from the rendered calendar:
* tasks (bardiensten) are green ``#27c24c`` when a place is still open and
  grey ``#a2a2a2`` when filled;
* club agenda items are mixed in; the page treats ``type == 3`` as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, tzinfo
from typing import Any

OPEN_COLORS = frozenset({"#27c24c"})
FULL_COLORS = frozenset({"#a2a2a2"})
AGENDA_TYPES = frozenset({"3"})

STATUS_OPEN = "open"
STATUS_FULL = "bezet"
STATUS_UNKNOWN = "onbekend"


@dataclass(frozen=True, slots=True)
class ClubEvent:
    """One item from the member calendar."""

    uid: str
    title: str
    start: datetime
    end: datetime
    all_day: bool
    is_task: bool
    status: str
    color: str | None
    raw_type: str | None
    extra: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @property
    def is_open(self) -> bool:
        return self.status == STATUS_OPEN

    @property
    def summary(self) -> str:
        if self.is_task:
            return f"{self.title} ({self.status})"
        return self.title


def _first(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
        # case-insensitive fallback (ASP.NET often uses PascalCase)
        for dk in d:
            if dk.lower() == k.lower() and d[dk] not in (None, ""):
                return d[dk]
    return None


def _parse_dt(value: Any, tz: tzinfo) -> tuple[datetime, bool] | None:
    """Return (datetime, date_only)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):  # epoch ms or s
        ts = value / 1000 if value > 1e11 else value
        return datetime.fromtimestamp(ts, tz), False
    text = str(value).strip()
    if text.startswith("/Date("):  # old ASP.NET JSON date
        ms = int(text[6:].split(")")[0].split("+")[0].split("-")[0])
        return datetime.fromtimestamp(ms / 1000, tz), False
    try:
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), time(0), tz), True
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt, False


def _color(d: dict[str, Any]) -> str | None:
    c = _first(d, "color", "backgroundColor", "background", "borderColor")
    return str(c).strip().lower() if c else None


def parse_events(payload: Any, tz: tzinfo) -> list[ClubEvent]:
    """Parse the GetEvents response."""
    if isinstance(payload, dict):
        for key in ("events", "data", "items", "result"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValueError(f"unexpected payload type {type(payload).__name__}")

    events: list[ClubEvent] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        start = _parse_dt(_first(item, "start", "startDate", "from"), tz)
        if start is None:
            continue
        end = _parse_dt(_first(item, "end", "endDate", "to"), tz)
        start_dt, date_only = start
        end_dt = end[0] if end else start_dt
        all_day = bool(_first(item, "allDay")) or date_only
        if end_dt <= start_dt:
            end_dt = start_dt.replace(hour=23, minute=59) if all_day else start_dt
        raw_type = _first(item, "type", "eventType", "typeId")
        raw_type = None if raw_type is None else str(raw_type)
        color = _color(item)
        is_task = raw_type not in AGENDA_TYPES
        if color in OPEN_COLORS:
            status = STATUS_OPEN
        elif color in FULL_COLORS:
            status = STATUS_FULL
        else:
            status = STATUS_UNKNOWN
        title = str(_first(item, "title", "name", "description") or "Onbekend").strip()
        uid = str(_first(item, "id", "Id", "taskId") or f"{title}-{start_dt.isoformat()}")
        known = {"id", "title", "start", "end", "allday", "color", "backgroundcolor",
                 "bordercolor", "type", "url"}
        extra = {k: v for k, v in item.items() if k.lower() not in known}
        events.append(
            ClubEvent(uid, title, start_dt, end_dt, all_day, is_task, status, color, raw_type, extra)
        )
    events.sort(key=lambda e: e.start)
    return events
