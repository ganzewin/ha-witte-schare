"""Config flow for De Witte Schare."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from aiohttp import DummyCookieJar
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import (
    async_create_clientsession,
    async_get_clientsession,
)
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .api import ClubSiteClient, ClubSiteError, LoginError, MemberClient
from .const import (
    CLUB_TIMEZONE,
    CONF_BASE_URL,
    CONF_DAYS_AHEAD,
    CONF_LOOKAHEAD,
    CONF_MEMBERSHIP_NUMBER,
    CONF_PASSWORD,
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
        errors: dict[str, str] = {}
        options = dict(self.config_entry.options)
        if user_input is not None:
            data = {
                CONF_LOOKAHEAD: int(user_input[CONF_LOOKAHEAD]),
                CONF_DAYS_AHEAD: int(user_input[CONF_DAYS_AHEAD]),
            }
            number = (user_input.get(CONF_MEMBERSHIP_NUMBER) or "").strip()
            password = user_input.get(CONF_PASSWORD) or ""
            if number and not password:
                # Keep the stored password when only the number is shown again.
                password = options.get(CONF_PASSWORD, "")
            if number and password:
                client = MemberClient(
                    async_create_clientsession(self.hass, cookie_jar=DummyCookieJar()),
                    self.config_entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
                    number,
                    password,
                )
                try:
                    await client.login()
                except LoginError:
                    errors["base"] = "invalid_auth"
                except ClubSiteError:
                    errors["base"] = "cannot_connect"
                data[CONF_MEMBERSHIP_NUMBER] = number
                data[CONF_PASSWORD] = password
            if not errors:
                return self.async_create_entry(data=data)
            options = {**options, **user_input}

        return self.async_show_form(
            step_id="init",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOOKAHEAD, default=options.get(CONF_LOOKAHEAD, DEFAULT_LOOKAHEAD)
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=480, step=5, mode=NumberSelectorMode.BOX,
                            unit_of_measurement="min",
                        )
                    ),
                    vol.Required(
                        CONF_DAYS_AHEAD, default=options.get(CONF_DAYS_AHEAD, DEFAULT_DAYS_AHEAD)
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=14, step=1, mode=NumberSelectorMode.BOX,
                            unit_of_measurement="d",
                        )
                    ),
                    vol.Optional(
                        CONF_MEMBERSHIP_NUMBER,
                        description={"suggested_value": options.get(CONF_MEMBERSHIP_NUMBER)},
                    ): str,
                    vol.Optional(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
        )
