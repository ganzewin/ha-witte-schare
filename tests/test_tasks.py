"""Member calendar parsing and setup."""

from datetime import date
import re
from zoneinfo import ZoneInfo

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant

from custom_components.witte_schare.const import DOMAIN
from custom_components.witte_schare.tasks import STATUS_FULL, STATUS_OPEN, parse_events

TZ = ZoneInfo("Europe/Amsterdam")

SAMPLE = [
    {"id": 101, "title": "Bardienst", "start": "2026-11-09T20:00:00", "end": "2026-11-09T23:00:00",
     "color": "#27c24c", "type": 1},
    {"id": 102, "title": "Bardienst", "start": "2026-11-12T20:00:00", "end": "2026-11-13T00:00:00",
     "color": "#a2a2a2", "type": 1},
    {"id": 7, "title": "Jeugd Pietentennis", "start": "2026-12-05", "allDay": True,
     "color": "#23b7e5", "type": 3},
]


def test_parse_sample():
    events = parse_events(SAMPLE, TZ)
    assert [e.uid for e in events] == ["101", "102", "7"]
    assert events[0].status == STATUS_OPEN and events[0].is_task
    assert events[1].status == STATUS_FULL
    assert events[1].end.date() == date(2026, 11, 13)
    assert not events[2].is_task and events[2].all_day


def test_parse_pascal_case_and_wrapped():
    payload = {"data": [{"Id": 5, "Title": "Bardienst", "Start": "2026-11-15T10:00:00",
                         "End": "2026-11-15T13:00:00", "BackgroundColor": "#27C24C"}]}
    (e,) = parse_events(payload, TZ)
    assert e.uid == "5" and e.status == STATUS_OPEN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


async def test_setup_with_login(hass: HomeAssistant, aioclient_mock, freezer) -> None:
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-11-08T11:00:00+01:00")
    from pathlib import Path
    empty = (Path(__file__).parent / "fixtures" / "bookings_empty.html").read_text()
    aioclient_mock.get(re.compile(r".*/courtbooking-overview/GetBookings.*"), text=empty.replace('value="7-11-2026', 'value="x'))
    aioclient_mock.get("https://www.witteschare.nl/mijn", text='<input name="Login.Password">')
    aioclient_mock.get("https://www.witteschare.nl/mijn/Tasks", text="<title>Fout</title>", status=500)
    aioclient_mock.post("https://www.witteschare.nl/mijn", text="<html>Uitloggen</html>")
    aioclient_mock.post("https://www.witteschare.nl/Ajax/Profile/GetTasks", text="<div>Bardienst</div>")
    aioclient_mock.post(
        "https://www.witteschare.nl/Ajax/Calendar/GetEvents",
        json=SAMPLE,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"base_url": "https://www.witteschare.nl"},
        options={"lookahead_minutes": 90, "days_ahead": 0, "membership_number": "123", "password": "x"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    states = {s.entity_id: s for s in hass.states.async_all() if "diensten" in s.entity_id}
    for eid, s in sorted(states.items()):
        print(eid, s.state, dict(s.attributes))
    assert hass.states.get("sensor.diensten_open_duties_next_7_days").state == "1"
    assert hass.states.get("calendar.diensten_bar_duties").attributes["message"] == "Bardienst (open)"
    source = hass.states.get("sensor.diensten_duties_source")
    assert source.state == "3"
    assert "'Bardienst' 1x" in source.attributes["takenlijst"]
    assert "als browser: HTTP 500" in source.attributes["takenpagina"]
    assert source.attributes["na_inloggen"].startswith("titel=")


async def test_login_rejected_keeps_board(hass: HomeAssistant, aioclient_mock, freezer) -> None:
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    from pathlib import Path
    empty = (Path(__file__).parent / "fixtures" / "bookings_empty.html").read_text()
    aioclient_mock.get(re.compile(r".*/courtbooking-overview/GetBookings.*"), text=empty)
    aioclient_mock.get("https://www.witteschare.nl/mijn", text='<input name="Login.Password">')
    aioclient_mock.get("https://www.witteschare.nl/mijn/Tasks", text='<input name="Login.Password">')
    aioclient_mock.post("https://www.witteschare.nl/mijn", text='<input name="Login.Password">')
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"base_url": "https://www.witteschare.nl"},
        options={"days_ahead": 0, "membership_number": "123", "password": "bad"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.afhangbord_courts_in_use") is not None
    src = hass.states.get("sensor.diensten_duties_source")
    assert src.state == "fout"
    assert "niet geaccepteerd" in src.attributes["laatste_fout"]


async def test_login_sends_login_type(hass: HomeAssistant, aioclient_mock) -> None:
    from homeassistant.helpers.aiohttp_client import async_get_clientsession
    from custom_components.witte_schare.api import MemberClient

    aioclient_mock.get("https://www.witteschare.nl/mijn", text="form")
    aioclient_mock.get("https://www.witteschare.nl/mijn/Tasks", text="<a>Uitloggen</a>")
    aioclient_mock.post("https://www.witteschare.nl/mijn", text="<a>Logout</a>")
    client = MemberClient(async_get_clientsession(hass), "https://www.witteschare.nl", "123", "pw")
    await client.login()
    method, url, data, _ = next(c for c in aioclient_mock.mock_calls if c[0] == "POST")
    assert data["Login.LoginType"] == "FedmembershipNumber"
    assert data["Login.MembershipNumber"] == "123"
