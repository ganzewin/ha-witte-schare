"""Constants for the Witte Schare integration."""

from datetime import timedelta

DOMAIN = "witte_schare"

CONF_BASE_URL = "base_url"
CONF_LOOKAHEAD = "lookahead_minutes"
CONF_DAYS_AHEAD = "days_ahead"

DEFAULT_BASE_URL = "https://www.witteschare.nl"
DEFAULT_LOOKAHEAD = 90
DEFAULT_DAYS_AHEAD = 7

BOOKINGS_PATH = "/courtbooking-overview/GetBookings"
CLUB_TIMEZONE = "Europe/Amsterdam"

UPDATE_INTERVAL = timedelta(minutes=5)
# Days other than today change rarely; refresh them less often.
FUTURE_REFRESH = timedelta(hours=1)
# Calendar views may ask for other dates; keep those for a while.
CACHE_TTL = timedelta(hours=6)
MAX_CALENDAR_DAYS = 42

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"
    " (KHTML, like Gecko) Version/18.0 Safari/605.1.15"
)
USER_AGENT = "HomeAssistant-WitteSchare/1.0 (+https://github.com/ganzewin/ha-witte-schare)"

CONF_MEMBERSHIP_NUMBER = "membership_number"
CONF_PASSWORD = "password"
LOGIN_PATH = "/mijn"
TASKS_PAGE_PATH = "/mijn/Tasks"
EVENTS_PATH = "/Ajax/Calendar/GetEvents"
TASKS_LIST_PATH = "/Ajax/Profile/GetTasks"
TASKS_UPDATE_INTERVAL = timedelta(minutes=30)
TASKS_DAYS_AHEAD = 28
