"""Entities for the member calendar (device 'Diensten')."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN
from .tasks import ClubEvent
from .tasks_coordinator import TasksCoordinator


class TasksEntity(CoordinatorEntity[TasksCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: TasksCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_tasks")},
            name="Diensten",
            manufacturer="KNLTB.Club",
            model="Diensten en clubagenda",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL) + "/mijn/Tasks",
        )


def _event(e: ClubEvent) -> CalendarEvent:
    if e.all_day:
        first = e.start.date()
        last = max(e.end.date(), first + timedelta(days=1))
        return CalendarEvent(start=first, end=last, summary=e.summary, uid=e.uid)
    return CalendarEvent(start=e.start, end=e.end, summary=e.summary, uid=e.uid)


class ClubCalendar(TasksEntity, CalendarEntity):
    """Bardiensten (tasks=True) or clubagenda (tasks=False)."""

    def __init__(self, coordinator: TasksCoordinator, tasks: bool) -> None:
        super().__init__(coordinator, "duties" if tasks else "club_agenda")
        self._tasks = tasks

    @property
    def event(self) -> CalendarEvent | None:
        items = self.coordinator.upcoming(tasks=self._tasks)
        return _event(items[0]) if items else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            _event(e) for e in (self.coordinator.data or [])
            if e.is_task == self._tasks and e.start < end_date and e.end > start_date
        ]


class OpenDutiesSensor(TasksEntity, SensorEntity):
    """Open bardiensten in the coming 7 days."""

    _attr_native_unit_of_measurement = "diensten"

    def __init__(self, coordinator: TasksCoordinator) -> None:
        super().__init__(coordinator, "open_duties_week")

    def _items(self) -> list[ClubEvent]:
        return [e for e in self.coordinator.upcoming(tasks=True, days=7) if e.is_open]

    @property
    def native_value(self) -> int:
        return len(self._items())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"diensten": [f"{e.start:%a %d-%m %H:%M} {e.title}" for e in self._items()]}


class NextOpenDutySensor(TasksEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: TasksCoordinator) -> None:
        super().__init__(coordinator, "next_open_duty")

    @property
    def native_value(self) -> datetime | None:
        items = [e for e in self.coordinator.upcoming(tasks=True) if e.is_open]
        return items[0].start if items else None


class SourceSensor(TasksEntity, SensorEntity):
    """Diagnostic: how many items came in and what the raw data looks like."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: TasksCoordinator) -> None:
        super().__init__(coordinator, "duties_source")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> int | str:
        if not self.coordinator.last_update_success:
            return "fout"
        return len(self.coordinator.data or [])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.coordinator
        statuses: dict[str, int] = {}
        for e in c.data or []:
            key = f"{'dienst' if e.is_task else 'agenda'}:{e.status}:{e.color}:{e.raw_type}"
            statuses[key] = statuses.get(key, 0) + 1
        return {
            "laatste_fout": None if c.last_update_success else str(c.last_exception),
            "ruwe_velden": c.raw_keys,
            "ruw_aantal": c.raw_count,
            "ruw_voorbeeld": c.raw_sample,
            "indeling": statuses,
            **c.client.diagnostics,
        }
