"""Parser tests against saved pages."""

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from custom_components.witte_schare.parser import merge_activity, page_date, parse_bookings, parse_courts

TZ = ZoneInfo("Europe/Amsterdam")
FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def test_courts():
    assert parse_courts(load("bookings_2026-11-05.html")) == [
        *(f"Baan {i}" for i in range(1, 9)), "Padel 1", "Padel 2"
    ]


def test_bookings_regular_evening():
    page = load("bookings_2026-11-05.html")
    assert page_date(page) == date(2026, 11, 5)
    bookings = parse_bookings(page, date(2026, 11, 5), TZ)
    assert len(bookings) == 18
    training = [b for b in bookings if b.kind == "Training"]
    assert {b.court for b in training} == {"Baan 1", "Baan 2"}
    b6 = [b for b in bookings if b.court == "Baan 6"]
    assert [(b.start.strftime("%H:%M"), b.end.strftime("%H:%M"), b.players) for b in b6] == [
        ("19:30", "20:30", 4), ("20:30", "21:30", 2)
    ]
    blocks = merge_activity(bookings)
    assert [(s.strftime("%H:%M"), e.strftime("%H:%M")) for s, e, _ in blocks] == [("18:00", "22:00")]


def test_closed_courts_not_activity():
    bookings = parse_bookings(load("bookings_2026-10-09.html"), date(2026, 10, 9), TZ)
    assert sum(b.is_closed for b in bookings) == 2
    blocks = merge_activity(bookings)
    assert [(s.strftime("%H:%M"), e.strftime("%H:%M")) for s, e, _ in blocks] == [
        ("10:30", "11:30"), ("13:00", "16:00"), ("18:00", "23:00")
    ]


def test_empty_day():
    assert parse_bookings(load("bookings_empty.html"), date(2026, 11, 7), TZ) == []
