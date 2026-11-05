"""Config flow for De Witte Schare."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .api import ClubSiteClient, ClubSiteError
from .const import (
    CLUB_TIMEZONE,
    CONF_BASE_URL,
    CONF_DAYS_AHEAD,
    CONF_LOOKAHEAD,
    DEFAULT_BASE_URL,
    DEFAULT_DAYS_AHEAD,
    DEFAULT_LOOKAHEAD,
    DOMAIN,
)


class WitteSchareConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the integration with the club site URL."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_BASE_URL].strip().rstrip("/")
            if not url.startswith("http"):
                url = f"https://{url}"
            host = urlparse(url).netloc.lower()
            await self.async_set_unique_id(host)
            self._abort_if_unique_id_configured()
            client = ClubSiteClient(
                async_get_clientsession(self.hass), url, dt_util.get_time_zone(CLUB_TIMEZONE)
            )
            try:
                await client.bookings(dt_util.now(dt_util.get_time_zone(CLUB_TIMEZONE)).date())
            except ClubSiteError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=host, data={CONF_BASE_URL: url})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_BASE_URL, default=DEFAULT_BASE_URL): str}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return WitteSchareOptionsFlow()


class WitteSchareOptionsFlow(OptionsFlow):
    """Lookahead window and number of days to fetch."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOOKAHEAD, default=options.get(CONF_LOOKAHEAD, DEFAULT_LOOKAHEAD)
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=480)),
                    vol.Required(
                        CONF_DAYS_AHEAD, default=options.get(CONF_DAYS_AHEAD, DEFAULT_DAYS_AHEAD)
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=14)),
                }
            ),
        )
