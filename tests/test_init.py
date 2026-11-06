"""Setup and entity tests with a mocked club site."""

import re
from pathlib import Path

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntryState

from custom_components.witte_schare.const import DOMAIN

FIX = Path(__file__).parent / "fixtures"

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


URL = re.compile(r"https://www\.witteschare\.nl/courtbooking-overview/GetBookings.*")


@pytest.fixture
async def setup(hass: HomeAssistant, aioclient_mock, freezer: FrozenDateTimeFactory):
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    freezer.move_to("2026-11-05T20:15:00+01:00")
    today = (FIX / "bookings_2026-11-05.html").read_text()
    empty = (FIX / "bookings_empty.html").read_text()

    async def pick(method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse
        q = str(url)
        body = today if "11%2F05%2F2026" in q or "11/05/2026" in q else empty.replace(
            'value="7-11-2026', 'value="x'
        )
        return AiohttpClientMockResponse(method, url, text=body)

    aioclient_mock.get(URL, side_effect=pick)
    entry = MockConfigEntry(domain=DOMAIN, data={"base_url": "https://www.witteschare.nl"}, unique_id="www.witteschare.nl")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities(hass: HomeAssistant, setup) -> None:
    assert setup.state is ConfigEntryState.LOADED
    states = {s.entity_id: s for s in hass.states.async_all() if "afhangbord" in s.entity_id}
    for eid, s in sorted(states.items()):
        print(eid, s.state, dict(s.attributes))
    assert hass.states.get("sensor.afhangbord_courts_in_use").state == "9"
    assert hass.states.get("sensor.afhangbord_tennis_courts_in_use").state == "7"
    assert hass.states.get("sensor.afhangbord_padel_courts_in_use").state == "2"
    assert hass.states.get("sensor.afhangbord_bookings_today").state == "18"
    assert hass.states.get("binary_sensor.afhangbord_activity_now").state == "on"
    assert hass.states.get("sensor.afhangbord_current_activity_end").state == "2026-11-05T21:00:00+00:00"
    cal = hass.states.get("calendar.afhangbord_activity")
    assert cal.state == "on"
