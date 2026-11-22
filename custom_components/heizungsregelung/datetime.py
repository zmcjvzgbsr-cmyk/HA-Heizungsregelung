"""Beginn und Ende der nächsten Rhythmus-Abwesenheit je Raum."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeizungConfigEntry
from .entity import HeizungEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeizungConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    entities = []
    for room in c.rooms:
        if room.rhythm:
            entities += [RhythmTime(c, room, "von"), RhythmTime(c, room, "bis")]
    async_add_entities(entities)


class RhythmTime(HeizungEntity, DateTimeEntity):
    def __init__(self, c, room, which: str) -> None:
        name = "Abwesend von" if which == "von" else "Abwesend bis"
        super().__init__(c, f"abwesend_{which}", name, room)
        self._which = which
        self._attr_icon = "mdi:calendar-start" if which == "von" else "mdi:calendar-end"

    @property
    def native_value(self) -> datetime | None:
        r = self.controller.rhythm.get(self.room.room_id)
        if r is None:
            return None
        return r.von if self._which == "von" else r.bis

    async def async_set_value(self, value: datetime) -> None:
        await self.controller.async_set_rhythm_time(self.room.room_id, self._which, value)
